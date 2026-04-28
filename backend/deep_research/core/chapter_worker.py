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

logger = logging.getLogger(__name__)


def _build_chapter_system_prompt(outline: ChapterOutline) -> str:
    """Build a system prompt tailored to the chapter's objectives."""
    questions_text = "\n".join(f"- {q}" for q in outline.key_questions)

    return f"""你是一位专业的研究分析师，负责撰写分析报告的一个独立章节。

【当前章节】
章节标题: {outline.title}
研究目标: {outline.objective}
建议字数: {outline.word_count} 字

【关键问题】（本章必须回答）
{questions_text}

【写作要求】
1. 基于提供的预检索资料撰写完整章节，不要泛泛而谈
2. 内容必须直接回答关键问题，提供数据支撑的深度分析
3. 所有数据必须标注来源，使用 [来源: 标题 / URL] 格式，URL 从预检索资料中获取；若无 URL 则使用 [来源: 标题]
4. 承认信息缺口和不确定性，不要编造数据
5. 使用 Markdown 格式，包含必要的小标题、列表、表格
6. 最终输出必须是完整的 Markdown 文本（不要包装在代码块中）
7. 内容要有深度，提供数据支撑的分析，而不是简单的信息罗列

【输出格式】
在最终回答中，直接输出 Markdown 格式的章节正文。不需要 JSON 格式。
章节正文应以二级标题（##）开头。"""


def _build_react_system_prompt(outline: ChapterOutline) -> str:
    """Build ReAct system prompt for revise()."""
    tools_hint = "、".join(outline.suggested_tools)
    questions_text = "\n".join(f"- {q}" for q in outline.key_questions)

    return f"""你是一位专业的研究分析师，负责修订分析报告的一个独立章节。

【当前章节】
章节标题: {outline.title}
研究目标: {outline.objective}
建议字数: {outline.word_count} 字

【关键问题】（本章必须回答）
{questions_text}

【可用工具】
建议工具: {tools_hint}
- tavily_search: 搜索互联网获取最新资讯、行业动态、相关信息
- web_scraper: 抓取搜索结果网页全文，获取深度内容

【写作要求】
1. 针对评审反馈进行修改，基于工具收集的额外信息补充内容
2. 内容必须直接回答关键问题，不要泛泛而谈
3. 所有数据必须标注来源，使用 [来源: 标题 / URL] 格式；URL 在 web_search 结果的 "url" 字段、web_scraper 结果的 "url" 字段中；若无 URL 则使用 [来源: 标题]
4. 承认信息缺口和不确定性，不要编造数据
5. 使用 Markdown 格式，包含必要的小标题、列表、表格
6. 最终输出必须是完整的 Markdown 文本（不要包装在代码块中）
7. 内容要有深度，提供数据支撑的分析，而不是简单的信息罗列

【输出格式】
在最终回答中，直接输出 Markdown 格式的章节正文。不需要 JSON 格式。
章节正文应以二级标题（##）开头。"""


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
    ):
        self.outline = chapter_outline
        self.session_dir = session_dir
        self.chapter_file = session_dir / f"chapter_{chapter_outline.chapter_id}.md"
        self.model = model or get_settings().llm.model
        self.llm = LLMClient()
        self.max_iterations = max_iterations
        self.tools = tools or _default_tools()
        self.skills = skills
        self._sources: list[Source] = []

    async def execute(self) -> Finding:
        """Write chapter content using a single-shot LLM call.

        Returns:
            Finding with chapter metadata and file path.
        """
        system_prompt = _build_chapter_system_prompt(self.outline)

        user_input = (
            f"请完成章节撰写：{self.outline.title}\n"
            f"研究目标：{self.outline.objective}\n\n"
            f"请撰写 '{self.outline.title}' 章节，目标字数约 {self.outline.word_count} 字。"
        )

        logger.info(
            f"[ChapterWorker {self.outline.chapter_id}] Starting (single-shot): "
            f"'{self.outline.title}'"
        )

        # Single-shot LLM call (no ReAct tool loop)
        t0 = time.perf_counter()
        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
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
        chapter_text = _unwrap_markdown(chapter_text)

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

        prompt = f"""请根据评审反馈，修改和完善以下章节内容。

【章节要求】
标题: {self.outline.title}
研究目标: {self.outline.objective}

【当前内容】
{current_text}

【评审反馈】
{feedback}

请输出修改后的完整章节 Markdown 文本。要求：
1. 针对反馈中指出的问题进行修改
2. 可以调用工具收集额外信息来补充内容
3. 保持章节的核心内容和结构
4. 直接输出 Markdown，不要包装在代码块中"""

        logger.info(f"[ChapterWorker {self.outline.chapter_id}] Revising via ReAct")
        t0 = time.perf_counter()

        try:
            # Use ReActAgent for revision (preserving ReAct framework)
            filtered_tools = _filter_tools(self.tools, self.outline.suggested_tools)
            react_agent = ReActAgent(
                name=f"chapter_worker_{self.outline.chapter_id}_reviser",
                system_prompt=_build_react_system_prompt(self.outline),
                tools=filtered_tools,
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


def _default_tools() -> list[BaseTool]:
    """Get default set of tools for chapter workers."""
    from deep_research.tools.web_scraper import WebScraperTool

    return [
        WebSearchTool(),
        WebScraperTool(),
    ]


def _filter_tools(
    all_tools: list[BaseTool],
    suggested: list[str],
) -> list[BaseTool]:
    """Filter tools based on chapter's suggested tools."""
    # Map suggested tool names to actual tool instances
    name_map = {t.name: t for t in all_tools}
    filtered = []
    for name in suggested:
        if name in name_map:
            filtered.append(name_map[name])
    # Always include tavily_search as fallback
    if "tavily_search" in name_map and "tavily_search" not in suggested:
        filtered.append(name_map["tavily_search"])
    return filtered if filtered else all_tools[:2]


def _unwrap_markdown(text: str) -> str:
    """Remove Markdown code block wrapper if present."""
    text = text.strip()
    if text.startswith("```markdown"):
        text = text[len("```markdown"):]
    elif text.startswith("```"):
        text = text[len("```"):]
    if text.endswith("```"):
        text = text[:-len("```")]
    return text.strip()


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
