"""OutlinePlanner: generates structured report outline from user query.

Phase 1 of V4 architecture. Takes a confirmed user query and produces a
ReportOutline with chapters, each having objective, tools, word count,
dependencies, and key questions.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class ChapterOutline:
    """Outline for a single report chapter."""

    chapter_id: str
    title: str
    objective: str
    suggested_tools: list[str] = field(default_factory=list)
    word_count: int = 800
    key_questions: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "title": self.title,
            "objective": self.objective,
            "suggested_tools": self.suggested_tools,
            "word_count": self.word_count,
            "key_questions": self.key_questions,
            "search_queries": self.search_queries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChapterOutline":
        return cls(
            chapter_id=data.get("chapter_id", ""),
            title=data.get("title", ""),
            objective=data.get("objective", ""),
            suggested_tools=data.get("suggested_tools", []),
            word_count=data.get("word_count", 800),
            key_questions=data.get("key_questions", []),
            search_queries=data.get("search_queries", []),
        )


@dataclass
class ReportOutline:
    """Complete report outline with all chapters."""

    title: str
    executive_summary_points: list[str]
    chapters: list[ChapterOutline]
    strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "executive_summary_points": self.executive_summary_points,
            "strategy": self.strategy,
            "metadata": self.metadata,
            "chapters": [c.to_dict() for c in self.chapters],
        }

    def save(self, path: Path) -> None:
        """Save outline to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"[OutlinePlanner] Outline saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "ReportOutline":
        """Load outline from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chapters = [ChapterOutline.from_dict(c) for c in data.get("chapters", [])]
        return cls(
            title=data.get("title", ""),
            executive_summary_points=data.get("executive_summary_points", []),
            strategy=data.get("strategy", ""),
            metadata=data.get("metadata", {}),
            chapters=chapters,
        )



OUTLINE_SYSTEM_PROMPT = """你是一位资深投研报告规划专家。你的职责是根据用户的研究需求，设计一份专业、结构化的深度分析报告大纲。

要求：
1. 报告大纲必须覆盖用户问题的所有维度
2. 每个章节有明确的 objective（研究目标）和 key_questions（需要回答的核心问题）
3. suggested_tools 从 [web_search, data_fetch, doc_analysis, cross_verify] 中选择
4. word_count 是建议字数，深度研究每章 600-1200 字
5. search_queries 提供 2-4 个用于预搜索的查询变体，从不同角度检索信息
6. 章节数量：简单分析 3-5 章，深度研究 6-10 章
7. 当前真实日期必须被考虑，确保分析具有时效性
8. 所有章节独立设计，不存在相互依赖关系

输出格式（严格JSON，不要任何解释文字）：
{
  "title": "报告标题",
  "executive_summary_points": ["要点1", "要点2"],
  "strategy": "整体研究策略说明",
  "chapters": [
    {
      "chapter_id": "c1",
      "title": "章节标题",
      "objective": "本章节需要完成的研究目标",
      "suggested_tools": ["web_search", "data_fetch"],
      "word_count": 800,
      "key_questions": ["问题1", "问题2"],
      "search_queries": ["查询变体1", "查询变体2"]
    }
  ]
}"""


class OutlinePlanner:
    """Generates structured report outlines using LLM."""

    MAX_RETRIES = 2

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.model = get_settings().llm.model

    async def generate_outline(
        self,
        user_query: str,
        save_dir: Path | None = None,
    ) -> ReportOutline:
        """Generate a report outline from user query.

        Args:
            user_query: Confirmed user query after intent clarification.
            save_dir: Optional directory to save the outline JSON.

        Returns:
            ReportOutline with chapters and metadata.
        """
        today = datetime.now().strftime("%Y年%m月%d日")

        prompt = f"""【当前真实日期】{today}

用户需求：{user_query}

请设计一份深度分析报告大纲。要求：
1. 覆盖用户问题的所有关键维度
2. 每个章节聚焦一个主题，不要混合太多目标
3. 对于公司/个股分析，建议包含：公司概况、行业分析、财务分析、估值分析、风险提示
4. 对于行业研究，建议包含：行业概况、竞争格局、政策环境、发展趋势、投资建议
5. 确保各章节之间有逻辑递进关系

请直接输出JSON格式的报告大纲。"""

        messages = [
            {"role": "system", "content": OUTLINE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        t0 = time.perf_counter()
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self.llm.chat(
                    messages=messages,
                    model=self.model,
                    max_tokens=4096,
                )
                content = response["choices"][0]["message"].get("content", "")
                outline = self._parse_outline(content)
                if outline:
                    latency = time.perf_counter() - t0
                    logger.info(
                        f"[OutlinePlanner] Generated outline in {latency:.2f}s: "
                        f"'{outline.title}', {len(outline.chapters)} chapters"
                    )
                    if save_dir:
                        outline_path = save_dir / "outline.json"
                        outline.save(outline_path)
                    return outline
            except Exception as e:
                logger.warning(f"[OutlinePlanner] Attempt {attempt + 1} failed: {e}")

        # Fallback: create a minimal outline
        logger.error(f"[OutlinePlanner] Failed after {time.perf_counter() - t0:.2f}s, using fallback")
        return self._fallback_outline(user_query)

    def _parse_outline(self, content: str) -> ReportOutline | None:
        """Parse LLM response into ReportOutline."""
        try:
            # Extract JSON from markdown code block or raw text
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = json.loads(content.strip().lstrip("\ufeff"))
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"[OutlinePlanner] Failed to parse outline JSON: {e}")
            return None

        if not isinstance(data, dict) or "chapters" not in data:
            return None

        chapters = []
        seen_ids = set()
        for c_data in data.get("chapters", []):
            cid = c_data.get("chapter_id", f"c{len(chapters) + 1}")
            if cid in seen_ids:
                cid = f"{cid}_{len(seen_ids)}"
            seen_ids.add(cid)

            # Normalize suggested_tools
            valid_tools = {"web_search", "data_fetch", "doc_analysis", "cross_verify"}
            tools = [t for t in c_data.get("suggested_tools", []) if t in valid_tools]
            if not tools:
                tools = ["web_search"]  # Default fallback

            chapters.append(ChapterOutline(
                chapter_id=cid,
                title=c_data.get("title", "未命名章节"),
                objective=c_data.get("objective", ""),
                suggested_tools=tools,
                word_count=c_data.get("word_count", 800),
                key_questions=c_data.get("key_questions", []),
                search_queries=c_data.get("search_queries", []),
            ))

        return ReportOutline(
            title=data.get("title", "投资分析报告"),
            executive_summary_points=data.get("executive_summary_points", []),
            strategy=data.get("strategy", ""),
            chapters=chapters,
            metadata={"generated_at": datetime.now().isoformat(), "source": "llm"},
        )

    def _fallback_outline(self, user_query: str) -> ReportOutline:
        """Create a minimal fallback outline when LLM fails."""
        return ReportOutline(
            title=f"{user_query[:30]}分析报告",
            executive_summary_points=["基于现有信息生成简要分析"],
            strategy="fallback: 最小化分析框架",
            chapters=[
                ChapterOutline(
                    chapter_id="c1",
                    title="市场与行业概况",
                    objective="分析当前市场环境和行业背景",
                    suggested_tools=["web_search", "data_fetch"],
                    word_count=600,
                    key_questions=["当前市场环境如何？", "行业整体发展趋势是什么？"],
                ),
                ChapterOutline(
                    chapter_id="c2",
                    title="核心分析",
                    objective="深入分析用户关注的核心问题",
                    suggested_tools=["web_search", "data_fetch", "doc_analysis"],
                    word_count=800,
                    key_questions=["核心问题的关键因素是什么？", "有何数据支撑？"],
                ),
                ChapterOutline(
                    chapter_id="c3",
                    title="总结与展望",
                    objective="综合结论和未来展望",
                    suggested_tools=["synthesis"],
                    word_count=500,
                    key_questions=["主要结论是什么？", "未来需要注意什么？"],
                ),
            ],
            metadata={"generated_at": datetime.now().isoformat(), "source": "fallback"},
        )
