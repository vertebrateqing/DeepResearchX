from __future__ import annotations
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

from deep_research.config.settings import get_settings
from deep_research.core.agent import LLMClient

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
    depends_on: list[str] = field(default_factory=list)
    research_type: str = "data_collection"  # "data_collection" | "analysis" | "conclusion"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "title": self.title,
            "objective": self.objective,
            "suggested_tools": self.suggested_tools,
            "word_count": self.word_count,
            "key_questions": self.key_questions,
            "depends_on": self.depends_on,
            "research_type": self.research_type,
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
            depends_on=data.get("depends_on", []),
            research_type=data.get("research_type", "data_collection"),
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



OUTLINE_SYSTEM_PROMPT = """你是一位资深研究报告规划专家。你的职责是根据用户的研究需求，设计一份专业、结构化的深度分析报告大纲。

在设计章节前，请先在脑中完成以下分析：
① 用户的核心研究目的是什么（决策支持/知识获取/对比分析/趋势预测）？
② 回答这个问题需要哪些核心维度的信息？
③ 哪些章节负责收集事实数据，哪些章节需要在数据基础上进行推理分析，哪些章节负责综合结论？
④ 章节间是否存在推理依赖链（例如：必须先有市场规模数据，才能做竞争格局分析）？

完成上述思考后，直接输出 JSON。

设计规则：
1. 章节标题必须具体，包含研究对象和具体维度，禁止使用宽泛标题
   - ❌ 错误示例："市场分析"、"行业概况"、"竞争格局"
   - ✅ 正确示例："中国新能源汽车2024年市场规模与增长驱动因素"、"比亚迪vs特斯拉核心技术路线对比"
2. 每个章节有明确的 objective（本章要得出什么结论）和 key_questions（必须回答的具体问题）
3. research_type 区分章节类型：
   - "data_collection"：收集事实、数据、现状（无依赖，可并行）
   - "analysis"：在数据基础上推理分析（依赖数据收集章节）
   - "conclusion"：综合多章结论（依赖分析章节）
4. depends_on 填写本章依赖的 chapter_id 列表，无依赖时填 []
5. suggested_tools 从 [tavily_search, web_scraper] 中选择
6. word_count 根据章节复杂度自行判断，单章上限 2000 字
7. 章节数量根据研究复杂度自行判断，上限 12 章
8. 当前真实日期必须被考虑，确保分析具有时效性

输出格式（严格JSON，不要任何解释文字）：
{
  "title": "报告标题",
  "research_purpose": "用户研究目的的一句话说明",
  "executive_summary_points": ["要点1", "要点2"],
  "strategy": "整体研究策略说明，包括章节依赖链的设计逻辑",
  "chapters": [
    {
      "chapter_id": "c1",
      "title": "具体的章节标题（含研究对象+维度）",
      "objective": "本章需要得出的结论或收集的信息",
      "research_type": "data_collection",
      "suggested_tools": ["tavily_search"],
      "word_count": 800,
      "key_questions": ["具体问题1", "具体问题2"],
      "depends_on": []
    }
  ]
}"""


def _fix_json_string_escapes(text: str) -> str:
    """Fix unescaped control characters inside JSON string literals.

    LLMs sometimes emit literal newlines, tabs, or other control chars inside
    JSON string values, which makes json.loads fail with 'Expecting delimiter'.
    This function replaces bare control characters inside string literals with
    their proper JSON escape sequences.
    """
    import re

    result = []
    in_string = False
    escape_next = False
    i = 0
    while i < len(text):
        ch = text[i]
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        elif in_string and ord(ch) < 0x20:
            # Other control characters
            result.append(f'\\u{ord(ch):04x}')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


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

        prompt = f"""用户需求：{user_query}

请设计深度分析报告大纲。注意：
- 章节标题必须具体（含研究对象+具体维度），禁止使用"市场分析"、"行业概况"等宽泛标题
- 明确区分数据收集章节（data_collection）和分析推理章节（analysis）和综合结论章节（conclusion）
- 分析/结论章节必须在 depends_on 中标注依赖的数据章节 id
- 每个章节的 key_questions 必须是具体可回答的问题，而非宽泛描述

直接输出JSON。

【当前真实日期】{today}"""

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
                    max_tokens=8192,
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
        import re

        # Step 1: Extract from markdown code block
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        content = content.strip().lstrip("\ufeff")

        # Step 2: Replace Chinese quotation marks that break JSON
        content = content.replace("\u201c", '"').replace("\u201d", '"')
        content = content.replace("\u2018", "'").replace("\u2019", "'")

        # Step 3: Try direct parse
        data = None
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"[OutlinePlanner] Direct JSON parse failed: {e}, trying repair...")
            logger.warning(f"[OutlinePlanner] Failing content around error (char {e.pos}): {content[max(0,e.pos-80):e.pos+80]!r}")

            # Step 4: Fix unescaped control characters inside JSON strings.
            # LLMs sometimes emit literal newlines/tabs inside string values.
            repaired = _fix_json_string_escapes(content)

            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                # Step 5: Extract outermost {...} and retry on repaired content
                match = re.search(r'\{[\s\S]*\}', repaired)
                if match:
                    try:
                        data = json.loads(match.group(0))
                    except json.JSONDecodeError as e2:
                        logger.warning(f"[OutlinePlanner] Failed to parse outline JSON: {e2}")
                        return None
                else:
                    logger.warning(f"[OutlinePlanner] Failed to parse outline JSON after repair: {e}")
                    return None

        if data is None:
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
            valid_tools = {"tavily_search", "web_scraper"}
            tools = [t for t in c_data.get("suggested_tools", []) if t in valid_tools]
            if not tools:
                tools = ["tavily_search"]  # Default fallback

            valid_types = {"data_collection", "analysis", "conclusion"}
            research_type = c_data.get("research_type", "data_collection")
            if research_type not in valid_types:
                research_type = "data_collection"

            depends_on = [d for d in c_data.get("depends_on", []) if isinstance(d, str)]

            chapters.append(ChapterOutline(
                chapter_id=cid,
                title=c_data.get("title", "未命名章节"),
                objective=c_data.get("objective", ""),
                suggested_tools=tools,
                word_count=c_data.get("word_count", 800),
                key_questions=c_data.get("key_questions", []),
                depends_on=depends_on,
                research_type=research_type,
            ))

        return ReportOutline(
            title=data.get("title", "深度研究报告"),
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
                    title=f"{user_query[:20]}现状与背景数据",
                    objective="收集研究主题的基本事实、数据和背景信息",
                    suggested_tools=["tavily_search"],
                    word_count=800,
                    key_questions=["当前基本情况如何？", "有哪些关键数据指标？"],
                    research_type="data_collection",
                    depends_on=[],
                ),
                ChapterOutline(
                    chapter_id="c2",
                    title=f"{user_query[:20]}核心问题深度分析",
                    objective="基于收集的数据，深入分析核心问题的成因、影响和规律",
                    suggested_tools=["tavily_search", "web_scraper"],
                    word_count=1000,
                    key_questions=["核心问题的关键驱动因素是什么？", "数据反映出哪些规律？"],
                    research_type="analysis",
                    depends_on=["c1"],
                ),
                ChapterOutline(
                    chapter_id="c3",
                    title=f"{user_query[:20]}综合结论与展望",
                    objective="综合前两章分析，得出结论并展望未来",
                    suggested_tools=["tavily_search"],
                    word_count=800,
                    key_questions=["综合分析的主要结论是什么？", "未来趋势如何判断？"],
                    research_type="conclusion",
                    depends_on=["c1", "c2"],
                ),
            ],
            metadata={"generated_at": datetime.now().isoformat(), "source": "fallback"},
        )
