from __future__ import annotations
"""ChapterWorker: chapter research and writing agent.

Phase 2 of V4 architecture. Each worker handles one chapter:
1. Receives chapter outline + pre-fetched research context
2. Writes complete chapter content in Markdown (single-shot LLM)
3. Saves to file and returns structured finding
4. revise() uses ReAct framework for iterative improvement
"""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from deep_research.config.settings import get_settings
from deep_research.core.agent import LLMClient, ReActAgent
from deep_research.core.base import BaseSkill, BaseTool
from deep_research.core.finding import Finding, Source
from deep_research.core.message import AgentMessage
from deep_research.core.outline_planner import ChapterOutline
from deep_research.tools.web_search import WebSearchTool
from deep_research.utils import unwrap_markdown

logger = logging.getLogger(__name__)


# Static system prompts — chapter-specific details go into user prompt for KV cache efficiency
CHAPTER_SYSTEM_PROMPT = """你是一位专业的研究分析师，负责撰写分析报告的独立章节。

【写作要求】
1. 基于提供的章节要求撰写完整章节，不要泛泛而谈
2. 内容必须直接回答关键问题，提供数据支撑的深度分析
3. 所有数据必须标注来源，使用 [来源: 标题 / URL] 格式，URL 从资料中获取；若无 URL 则使用 [来源: 标题]
4. 承认信息缺口和不确定性，不要编造数据
5. 使用 Markdown 格式，包含必要的小标题、列表、表格
6. 最终输出必须是完整的 Markdown 文本（不要包装在代码块中）
7. 内容要有深度，提供数据支撑的分析，而不是简单的信息罗列

【输出格式】
直接输出 Markdown 格式的章节正文。不需要 JSON 格式。章节正文应以二级标题（##）开头。"""

REACT_SYSTEM_PROMPT = """你是一位专业的研究分析师，负责修订分析报告的独立章节。

【可用工具】
- document_search: 在用户上传的本地文档（PDF / Word / 文本）中检索最相关段落，优先使用
- tavily_search: 搜索互联网获取最新资讯、行业动态、相关信息
- web_scraper: 抓取搜索结果网页全文，获取深度内容

【写作要求】
1. 针对评审反馈进行修改，基于工具收集的额外信息补充内容
2. 优先调用 document_search 获取用户上传文档中的素材；联网搜索作为补充
3. 内容必须直接回答关键问题，不要泛泛而谈
4. 所有数据必须标注来源；引用上传文档时用 [来源: 文件名]，引用网页时用 [来源: 标题 / URL]
5. 承认信息缺口和不确定性，不要编造数据
6. 使用 Markdown 格式，包含必要的小标题、列表、表格
7. 最终输出必须是完整的 Markdown 文本（不要包装在代码块中）
8. 内容要有深度，提供数据支撑的分析，而不是简单的信息罗列

【输出格式】
直接输出 Markdown 格式的章节正文。不需要 JSON 格式。章节正文应以二级标题（##）开头。"""


def _build_chapter_user_prompt(
    outline: ChapterOutline,
    document_context: str = "",
    dependency_contents: dict[str, str] | None = None,
) -> str:
    """Build user prompt with chapter-specific details (keeps system prompt static)."""
    questions_text = "\n".join(f"- {q}" for q in outline.key_questions)
    parts: list[str] = []

    # Layer dependency contents before chapter requirements so the model sees context first
    if dependency_contents:
        parts.append("【前置章节内容】")
        parts.append(
            "以下是你依赖的上游章节已完成的研究内容。"
            "请基于这些结果继续深入分析，不要简单重复已有内容，而是进行延伸、对比或综合判断。"
        )
        for dep_id, dep_text in dependency_contents.items():
            parts.append("")
            parts.append(f"--- [{dep_id}] ---")
            parts.append(dep_text)
        parts.append("")

    parts.extend([
        "【章节要求】",
        f"标题: {outline.title}",
        f"研究目标: {outline.objective}",
        f"建议字数: {outline.word_count} 字",
        "",
        "【关键问题】（本章必须回答）",
        questions_text,
    ])
    if document_context:
        parts.append("")
        parts.append("【用户上传文档检索结果】（请优先据此撰写并标注 [来源: 文件名]）")
        parts.append(document_context)
    parts.append("")
    parts.append(f"请撰写 '{outline.title}' 章节。")
    return "\n".join(parts)


def _build_react_user_prompt(outline: ChapterOutline, feedback: str, current_text: str) -> str:
    """Build user prompt for ReAct revision with chapter-specific details."""
    questions_text = "\n".join(f"- {q}" for q in outline.key_questions)
    return (
        f"【章节要求】\n"
        f"标题: {outline.title}\n"
        f"研究目标: {outline.objective}\n"
        f"建议字数: {outline.word_count} 字\n\n"
        f"【关键问题】（本章必须回答）\n{questions_text}\n\n"
        f"【当前内容】\n{current_text}\n\n"
        f"【评审反馈】\n{feedback}\n\n"
        f"请根据评审反馈修改章节，可调用工具补充信息。"
    )


class ChapterWorker:
    """Worker that writes a single report chapter."""

    def __init__(
        self,
        chapter_outline: ChapterOutline,
        session_dir: Path,
        tools: Optional[list[BaseTool]] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
        max_iterations: int = 10,
        trace_id: Optional[str] = None,
        document_collection: Optional[str] = None,
        document_ids: Optional[list[str]] = None,
        dependency_contents: Optional[dict[str, str]] = None,
        documents_only: bool = False,
    ):
        self.outline = chapter_outline
        self.session_dir = session_dir
        self.chapter_file = session_dir / f"chapter_{chapter_outline.chapter_id}.md"
        self.dependency_contents = dependency_contents or {}
        self.model = model or get_settings().llm.model
        self.llm = LLMClient()
        self.llm._trace_id = trace_id
        self.max_iterations = max_iterations
        self.document_collection = document_collection
        self.document_ids = list(document_ids) if document_ids else None
        self.documents_only = documents_only
        self.tools = tools or _default_tools(
            document_collection=self.document_collection,
            allowed_doc_ids=self.document_ids,
            documents_only=self.documents_only,
        )
        # Propagate trace_id to all tools
        for tool in self.tools:
            if hasattr(tool, "_trace_id"):
                tool._trace_id = trace_id
        self.skills = skills
        self._sources: list[Source] = []

    async def execute(self) -> Finding:
        """Write chapter content using a single-shot LLM call.

        When user-uploaded documents are available, retrieve relevant chunks
        first and include them as context in the user prompt so the
        single-shot writer can quote them.

        Returns:
            Finding with chapter metadata and file path.
        """
        document_context = await self._fetch_document_context()
        user_input = _build_chapter_user_prompt(
            self.outline, document_context, self.dependency_contents
        )

        logger.info(
            f"[ChapterWorker {self.outline.chapter_id}] Starting (single-shot): "
            f"'{self.outline.title}' doc_ctx_chars={len(document_context)}"
        )

        # Single-shot LLM call (no ReAct tool loop)
        t0 = time.perf_counter()
        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": CHAPTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_input},
                ],
                model=self.model,
                max_tokens=4096,
            )
            chapter_text = response["choices"][0]["message"].get("content", "")
        except Exception as e:
            logger.error(f"[ChapterWorker {self.outline.chapter_id}] LLM call failed: {e}")
            chapter_text = f"## {self.outline.title}\n\n章节生成失败，请稍后重试。"

        latency = time.perf_counter() - t0

        # Clean up - remove code block wrappers if present
        chapter_text = unwrap_markdown(chapter_text)

        # Add chapter header if missing
        if not chapter_text.strip().startswith("##"):
            chapter_text = f"## {self.outline.title}\n\n{chapter_text}"

        # Save to file
        word_count = len(chapter_text)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        with open(self.chapter_file, "w", encoding="utf-8") as f:
            f.write(chapter_text)

        logger.info(
            f"[ChapterWorker {self.outline.chapter_id}] Completed in {latency:.2f}s: "
            f"word_count={word_count}, saved to {self.chapter_file}"
        )

        # Build finding
        self._sources = _extract_sources_from_text(chapter_text)

        return Finding(
            task_id=self.outline.chapter_id,
            role="chapter_writer",
            summary=f"{self.outline.title}: {chapter_text[:150]}...",
            details={
                "chapter_id": self.outline.chapter_id,
                "title": self.outline.title,
                "file_path": str(self.chapter_file),
                "word_count": word_count,
                "latency_s": round(latency, 2),
            },
            sources=self._sources,
            confidence=0.8,
        )

    async def revise(self, feedback: str) -> None:
        """Revise the chapter based on reviewer feedback using ReAct framework.

        Preserved per user request: uses ReActAgent for iterative tool use
        during revision. Reads current chapter, incorporates feedback,
        and rewrites the file.
        """
        if not self.chapter_file.exists():
            logger.warning(f"[ChapterWorker {self.outline.chapter_id}] No existing chapter to revise")
            return

        current_text = self.chapter_file.read_text(encoding="utf-8")
        prompt = _build_react_user_prompt(self.outline, feedback, current_text)

        logger.info(f"[ChapterWorker {self.outline.chapter_id}] Revising via ReAct")
        t0 = time.perf_counter()

        try:
            react_agent = ReActAgent(
                name=f"chapter_worker_{self.outline.chapter_id}_reviser",
                system_prompt=REACT_SYSTEM_PROMPT,
                tools=self.tools,
                skills=self.skills,
                model=self.model,
                max_iterations=self.max_iterations,
            )
            agent_msg: AgentMessage = await react_agent.run(prompt, context=None)
            content = agent_msg.content
            if isinstance(content, dict):
                revised = content.get("answer", "") or content.get("summary", "")
            elif isinstance(content, str):
                revised = content
            else:
                revised = str(content)

            revised = _unwrap_markdown(revised)
            if not revised.strip().startswith("##"):
                revised = f"## {self.outline.title}\n\n{revised}"

            with open(self.chapter_file, "w", encoding="utf-8") as f:
                f.write(revised)

            # Re-extract sources from revised content
            self._sources = _extract_sources_from_text(revised)

            logger.info(
                f"[ChapterWorker {self.outline.chapter_id}] Revised in "
                f"{time.perf_counter() - t0:.2f}s, new length={len(revised)}, "
                f"sources={len(self._sources)}"
            )
        except Exception as e:
            logger.error(f"[ChapterWorker {self.outline.chapter_id}] Revision failed: {e}")

    async def _fetch_document_context(self, top_k: int = 6) -> str:
        """Pre-fetch top relevant chunks from uploaded documents for this chapter.

        Returns a Markdown-formatted block that the single-shot LLM can quote
        verbatim. Empty string when no documents are configured.
        """
        if not self.document_collection:
            return ""

        from deep_research.tools.document_search import DocumentSearchTool

        # Build the retrieval query from chapter title + key questions so we
        # surface the most relevant chunks for what this chapter has to answer.
        parts: list[str] = [self.outline.title]
        if self.outline.objective:
            parts.append(self.outline.objective)
        parts.extend(self.outline.key_questions or [])
        query = "\n".join(p for p in parts if p)

        try:
            tool = DocumentSearchTool(
                collection_name=self.document_collection,
                allowed_doc_ids=self.document_ids,
            )
            tool._trace_id = self.llm._trace_id
            result = await tool.execute(query=query, top_k=top_k)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[ChapterWorker {self.outline.chapter_id}] doc retrieval failed: {e}"
            )
            return ""

        chunks = result.get("chunks", []) or []
        if not chunks:
            return ""

        lines: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            filename = chunk.get("filename") or chunk.get("doc_id") or "uploaded_document"
            text = (chunk.get("text") or "").strip()
            if not text:
                continue
            lines.append(f"[{i}] [来源: {filename}] (相关度 {chunk.get('score', 0)})")
            lines.append(text)
            lines.append("")
        return "\n".join(lines).strip()


def _default_tools(
    document_collection: Optional[str] = None,
    allowed_doc_ids: Optional[list[str]] = None,
    documents_only: bool = False,
) -> list[BaseTool]:
    """Get default set of tools for chapter workers.

    When ``document_collection`` is provided, prepend ``DocumentSearchTool``
    so the LLM can retrieve from user-uploaded documents.
    When ``documents_only`` is true, skip web search / scraper tools.
    """
    from deep_research.tools.web_scraper import WebScraperTool

    tools: list[BaseTool] = []
    if document_collection:
        from deep_research.tools.document_search import DocumentSearchTool

        tools.append(
            DocumentSearchTool(
                collection_name=document_collection,
                allowed_doc_ids=allowed_doc_ids,
            )
        )
    if not documents_only:
        tools.extend([WebSearchTool(), WebScraperTool()])
    return tools



def _extract_sources_from_text(text: str) -> list[Source]:
    """Extract source references from chapter text.

    Looks for patterns like [来源: title] or [来源: title / url].
    """
    import re

    sources = []
    # Pattern: [来源: something] or [来源: title / url]
    pattern = r"\[来源[:：]\s*([^\]]+)\]"
    matches = re.findall(pattern, text)

    seen = set()
    for match in matches:
        parts = match.split("/")
        title = parts[0].strip()
        url = parts[1].strip() if len(parts) > 1 else ""
        key = f"{title}:{url}"
        if key not in seen:
            seen.add(key)
            sources.append(Source(type="web", title=title, url=url))

    return sources
