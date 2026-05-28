from __future__ import annotations
"""OutlinePlanner: generates structured report outline from user query.

Phase 1 of V4 architecture. Takes a confirmed user query and produces a
ReportOutline with chapters, each having objective, tools, word count,
dependencies, and key questions.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from deep_research.config.settings import get_settings
from deep_research.core.agent import LLMClient, ReActAgent
from deep_research.tools.web_search import WebSearchTool
from deep_research.utils import RobustJSONParser, extract_json_from_markdown

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



RESEARCH_SYSTEM_PROMPT = """你是一位严谨的研究前期调研员，负责在正式规划报告前收集和验证关键信息。

你的核心任务：
1. 通过搜索了解研究主题的真实信息 landscape
2. 识别可信的数据来源、权威机构、行业报告
3. 验证可能过时的假设（如"某政策是否仍在执行"、"某报告是否已发布"）
4. 发现真实的研究维度和分析框架
5. 标注无法验证的假设，供后续规划阶段参考

搜索策略：
- 先进行 2-3 次广泛搜索，了解主题整体概况和最新进展
- 针对发现的关键事实进行 1-2 次验证搜索
- 如发现数据缺口或时效性问题，继续深入搜索
- 每次搜索后总结关键发现，决定是否需要进一步搜索

输出格式（Markdown）：
```
# 信息探索笔记

## 关键发现
- [发现1]（来源：xxx）
- [发现2]（来源：xxx）

## 可信数据来源
- [来源1]: 描述
- [来源2]: 描述

## 建议的研究维度
1. [维度1]: 说明
2. [维度2]: 说明

## 已验证的关键事实
- [事实1]: 验证方式和来源
- [事实2]: 验证方式和来源

## 无法验证的假设（风险标注）
- [假设1]: 为什么无法验证，对报告的影响

## 注意事项与数据缺口
- [注意1]
```

请基于搜索结果输出完整的信息探索笔记。如果信息足够充分，直接输出笔记即可，无需继续搜索。"""


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


class OutlineResearchAgent(ReActAgent):
    """ReAct agent for pre-outline information research and validation."""

    def __init__(self, model: str | None = None) -> None:
        super().__init__(
            name="outline_researcher",
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            tools=[WebSearchTool()],
            model=model,
            max_iterations=8,
        )

    async def run_research(self, user_query: str) -> str:
        """Run research phase and return the research note.

        Returns empty string if research fails, allowing fallback to
        no-research mode.
        """
        from deep_research.core.message import AgentContext

        ctx = AgentContext(
            agent_name=self.name,
            metadata={"query": user_query},
        )
        try:
            result_msg = await self.run(user_input=user_query, context=ctx)
            if result_msg.message_type.value == "error":
                logger.warning(f"[OutlineResearchAgent] Research failed: {result_msg.content}")
                return ""
            answer = result_msg.content
            if isinstance(answer, dict):
                answer = answer.get("answer", "")
            return str(answer)
        except Exception as e:
            logger.warning(f"[OutlineResearchAgent] Research error: {e}")
            return ""


class OutlinePlanner:
    """Generates structured report outlines using LLM."""

    MAX_RETRIES = 2
    RESEARCH_TIMEOUT_SECONDS = 60

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.model = get_settings().llm.model
        self.research_agent = OutlineResearchAgent(model=self.model)

    async def generate_outline(
        self,
        user_query: str,
        save_dir: Path | None = None,
    ) -> ReportOutline:
        """Generate a report outline from user query.

        Three-phase pipeline:
        1. ReAct research: gather and validate information via web search
        2. Structured generation: produce ReportOutline with research context
        3. Validation: DAG check, dependency existence, type consistency

        Args:
            user_query: Confirmed user query after intent clarification.
            save_dir: Optional directory to save the outline JSON.

        Returns:
            ReportOutline with chapters and metadata.
        """
        # Phase 1: ReAct information research (with timeout fallback)
        research_note = await self._research_phase(user_query)

        # Phase 2: Generate structured outline with enhanced context
        outline = await self._generate_with_research(user_query, research_note)

        # Phase 3: Validate and auto-fix structural issues
        if outline is not None:
            outline = self._validate_and_fix(outline)
            if outline is not None:
                if save_dir:
                    outline_path = save_dir / "outline.json"
                    outline.save(outline_path)
                return outline

        # Fallback
        return self._fallback_outline(user_query)

    async def _research_phase(self, user_query: str) -> str:
        """Run ReAct research agent with timeout. Returns empty string on failure."""
        import asyncio

        try:
            research_note = await asyncio.wait_for(
                self.research_agent.run_research(user_query),
                timeout=self.RESEARCH_TIMEOUT_SECONDS,
            )
            if research_note:
                logger.info(
                    f"[OutlinePlanner] Research phase completed, note length={len(research_note)}"
                )
            return research_note
        except asyncio.TimeoutError:
            logger.warning(
                f"[OutlinePlanner] Research phase timed out after {self.RESEARCH_TIMEOUT_SECONDS}s, "
                "falling back to no-research mode"
            )
            return ""
        except Exception as e:
            logger.warning(f"[OutlinePlanner] Research phase failed: {e}, falling back to no-research mode")
            return ""

    def _build_enhanced_prompt(self, user_query: str, research_note: str) -> str:
        """Build user prompt with optional research context."""
        today = datetime.now().strftime("%Y年%m月%d日")

        if research_note:
            research_section = f"""
【前期调研发现】（基于真实搜索验证）
{research_note}

请基于以上经过验证的信息设计大纲。要求：
- 章节设计必须与调研发现一致，不得虚构未验证的数据来源
- 对于标注为"无法验证的假设"的信息，相关章节应设计为"探索性分析"而非"确定性结论"
- 优先利用调研发现的可信数据来源设计数据收集章节
"""
        else:
            research_section = ""

        prompt = f"""用户需求：{user_query}
{research_section}

请设计深度分析报告大纲。注意：
- 章节标题必须具体（含研究对象+具体维度），禁止使用"市场分析"、"行业概况"等宽泛标题
- 明确区分数据收集章节（data_collection）和分析推理章节（analysis）和综合结论章节（conclusion）
- 分析/结论章节必须在 depends_on 中标注依赖的数据章节 id
- 每个章节的 key_questions 必须是具体可回答的问题，而非宽泛描述

直接输出JSON。

【当前真实日期】{today}"""
        return prompt

    async def _generate_with_research(
        self, user_query: str, research_note: str
    ) -> ReportOutline | None:
        """Generate outline with research context and retry logic."""
        prompt = self._build_enhanced_prompt(user_query, research_note)
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
                    return outline
            except Exception as e:
                logger.warning(f"[OutlinePlanner] Attempt {attempt + 1} failed: {e}")

        logger.error(f"[OutlinePlanner] Failed after {time.perf_counter() - t0:.2f}s")
        return None

    def _validate_and_fix(self, outline: ReportOutline) -> ReportOutline | None:
        """Validate outline structure and auto-fix issues.

        Checks:
        - DAG acyclicity (Kahn's algorithm)
        - Dependency existence (all deps point to real chapter_ids)
        - Dependency type consistency (analysis -> data_collection, conclusion -> analysis)
        - Word count range (200-2000)

        Returns the fixed outline, or None if unfixable.
        """
        if not outline.chapters:
            logger.warning("[OutlineValidator] Empty outline, cannot validate")
            return None

        chapter_map = {ch.chapter_id: ch for ch in outline.chapters}
        chapter_ids = set(chapter_map.keys())
        fix_log: list[str] = []

        # 1. Fix invalid dependencies (point to non-existent chapters)
        for ch in outline.chapters:
            valid_deps = [d for d in ch.depends_on if d in chapter_ids]
            removed = set(ch.depends_on) - set(valid_deps)
            if removed:
                fix_log.append(f"Removed invalid deps from {ch.chapter_id}: {removed}")
                ch.depends_on = valid_deps

        # 2. Fix dependency type consistency
        for ch in outline.chapters:
            if ch.research_type == "analysis" and ch.depends_on:
                # analysis should depend on data_collection chapters
                dep_types = {dep_id: chapter_map[dep_id].research_type for dep_id in ch.depends_on}
                has_data = any(t == "data_collection" for t in dep_types.values())
                if not has_data:
                    fix_log.append(
                        f"Chapter {ch.chapter_id} (analysis) has no data_collection deps, "
                        "downgrading to data_collection"
                    )
                    ch.research_type = "data_collection"
                    ch.depends_on = []
            elif ch.research_type == "conclusion" and ch.depends_on:
                dep_types = {dep_id: chapter_map[dep_id].research_type for dep_id in ch.depends_on}
                has_analysis = any(t in ("analysis", "conclusion") for t in dep_types.values())
                if not has_analysis:
                    fix_log.append(
                        f"Chapter {ch.chapter_id} (conclusion) has no analysis deps, "
                        "downgrading to analysis"
                    )
                    ch.research_type = "analysis"

        # 3. Fix word_count range
        for ch in outline.chapters:
            if ch.word_count < 200:
                fix_log.append(f"Chapter {ch.chapter_id} word_count {ch.word_count} < 200, clamping to 200")
                ch.word_count = 200
            elif ch.word_count > 2000:
                fix_log.append(f"Chapter {ch.chapter_id} word_count {ch.word_count} > 2000, clamping to 2000")
                ch.word_count = 2000

        # 4. Detect cycles (Kahn's algorithm)
        in_degree: dict[str, int] = {ch.chapter_id: 0 for ch in outline.chapters}
        adj: dict[str, list[str]] = {ch.chapter_id: [] for ch in outline.chapters}
        for ch in outline.chapters:
            for dep in ch.depends_on:
                if dep in adj:
                    adj[dep].append(ch.chapter_id)
                    in_degree[ch.chapter_id] += 1

        queue = [cid for cid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            cid = queue.pop(0)
            visited += 1
            for next_cid in adj[cid]:
                in_degree[next_cid] -= 1
                if in_degree[next_cid] == 0:
                    queue.append(next_cid)

        if visited != len(outline.chapters):
            # Cycle detected — attempt repair by removing edges that form cycles
            fix_log.append("Cycle detected in dependency graph, attempting repair")
            for ch in outline.chapters:
                # Simple heuristic: if a chapter depends on a later chapter (by index), remove it
                # This is a best-effort fix; complex cycles may still remain
                my_index = next(
                    (i for i, c in enumerate(outline.chapters) if c.chapter_id == ch.chapter_id), -1
                )
                bad_deps = [
                    d
                    for d in ch.depends_on
                    if d in chapter_ids
                    and next(
                        (i for i, c in enumerate(outline.chapters) if c.chapter_id == d), -1
                    )
                    > my_index
                ]
                if bad_deps:
                    fix_log.append(f"Removed backward deps from {ch.chapter_id}: {bad_deps}")
                    ch.depends_on = [d for d in ch.depends_on if d not in bad_deps]

            # Re-check after repair
            in_degree = {ch.chapter_id: 0 for ch in outline.chapters}
            adj = {ch.chapter_id: [] for ch in outline.chapters}
            for ch in outline.chapters:
                for dep in ch.depends_on:
                    if dep in adj:
                        adj[dep].append(ch.chapter_id)
                        in_degree[ch.chapter_id] += 1
            queue = [cid for cid, deg in in_degree.items() if deg == 0]
            visited = 0
            while queue:
                cid = queue.pop(0)
                visited += 1
                for next_cid in adj[cid]:
                    in_degree[next_cid] -= 1
                    if in_degree[next_cid] == 0:
                        queue.append(next_cid)

            if visited != len(outline.chapters):
                logger.error("[OutlineValidator] Unfixable cycle detected, returning None")
                return None

        if fix_log:
            logger.info(f"[OutlineValidator] Applied {len(fix_log)} fixes: {fix_log}")
        else:
            logger.info("[OutlineValidator] Outline passed all checks")

        return outline

    def _parse_outline(self, content: str) -> ReportOutline | None:
        """Parse LLM response into ReportOutline."""
        data = RobustJSONParser.parse(content)

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
