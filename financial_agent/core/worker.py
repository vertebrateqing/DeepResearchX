"""Generic research worker with dynamic role-based system prompts.

All sub-agents in the deepresearch pipeline are instances of GenericWorker.
The specific behaviour is determined by the ``role`` injected at construction
time, not by a fixed class hierarchy.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient, ReActAgent
from financial_agent.core.base import AgentContext, BaseSkill, BaseTool
from financial_agent.core.context_manager import ContextManager, TokenBudget
from financial_agent.core.finding import Finding, Source
from financial_agent.core.message import AgentMessage
from financial_agent.core.research_plan import TaskNode
from financial_agent.tools.akshare_data import AKShareTool
from financial_agent.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role prompts — extracted from the legacy hard-coded agent classes.
# Each prompt describes *capabilities*, not a fixed business workflow.
# ---------------------------------------------------------------------------

ROLE_PROMPTS: dict[str, str] = {
    "web_search": """你是一个信息检索专家。你的职责是通过网络搜索获取最新、最相关的信息。

能力范围：
1. 搜索市场动态、行业新闻、公司公告
2. 搜索分析师报告和投资观点
3. 搜索宏观经济数据和政策变化

输出要求：
- 只输出与任务目标直接相关的信息
- 每条信息标注来源（URL/标题）
- 如果搜索结果不足，明确说明
- 最终输出必须是 JSON 格式：{"summary": "...", "details": {...}, "sources": [...]}""",

    "data_fetch": """你是一个数据获取专家。你的职责是从结构化数据源提取精确的财务和市场数据。

能力范围：
1. 获取股票行情、财务指标、行业数据
2. 获取宏观经济指标
3. 对比历史数据进行趋势分析

输出要求：
- 数据必须准确，注明统计口径
- 对异常数据进行标记
- 最终输出必须是 JSON 格式：{"summary": "...", "details": {...}, "sources": [...]}""",

    "doc_analysis": """你是一个文档分析专家。你的职责是从财报、研报等长文档中提取关键信息并进行深度分析。

能力范围：
1. 提取核心财务指标（营收、利润、ROE、现金流等）
2. 分析财务趋势和变化原因
3. 对比同行业公司进行竞争分析
4. 识别潜在风险和机会

输出要求：
- 分析要有数据支撑
- 结论要明确，避免模糊表述
- 最终输出必须是 JSON 格式：{"summary": "...", "details": {...}, "sources": [...]}""",

    "cross_verify": """你是一个事实核查专家。你的职责是交叉验证多个信息源的数据一致性。

能力范围：
1. 对比不同来源的同一指标
2. 识别数据矛盾和不一致
3. 评估数据可靠性

输出要求：
- 明确指出一致/不一致的地方
- 给出可信度评估
- 最终输出必须是 JSON 格式：{"summary": "...", "details": {...}, "sources": [...]}""",

    "synthesis": """你是一个综合分析专家。你的职责是将多个信息源整合为连贯、有深度的结论。

能力范围：
1. 整合不同维度的分析结果
2. 发现信息之间的关联和矛盾
3. 生成投资建议和风险提示

输出要求：
- 逻辑清晰，论证充分
- 承认不确定性和信息缺口
- 最终输出必须是 JSON 格式：{"summary": "...", "details": {...}, "sources": [...]}""",
}


class GenericWorker(ReActAgent):
    """A general-purpose research worker whose role is injected at runtime."""

    def __init__(
        self,
        task: TaskNode,
        tools: Optional[list[BaseTool]] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
        max_iterations: int = 10,
        context_manager: Optional[ContextManager] = None,
    ):
        role_prompt = ROLE_PROMPTS.get(task.role, ROLE_PROMPTS["web_search"])

        # Build dynamic system prompt
        system_prompt = f"""{role_prompt}

【当前任务】
任务ID: {task.task_id}
角色: {task.role}
目标: {task.goal}

【输出格式要求】
你必须在最终回答中输出以下 JSON 格式：
{{
  "summary": "100-200字的执行摘要，概述关键发现",
  "details": {{
    "key_points": ["要点1", "要点2", ...],
    "data": {{}}
  }},
  "sources": [
    {{"type": "web", "url": "...", "title": "..."}}
  ],
  "confidence": 0.85
}}

注意事项：
1. summary 要简洁，方便上级 Planner 快速理解
2. details 可以包含完整的数据和分析
3. sources 必须真实，只列出你实际使用的来源
4. confidence 用 0-1 表示你对结论的信心程度
"""
        super().__init__(
            name=f"worker_{task.task_id}",
            system_prompt=system_prompt,
            tools=tools or [AKShareTool(), WebSearchTool()],
            skills=skills,
            model=model or get_settings().llm.model,
            max_iterations=max_iterations,
        )
        self.task = task
        self.context_manager = context_manager

    async def execute(self, dependency_inputs: dict[str, Any]) -> Finding:
        """Execute the task and return a structured Finding.

        Args:
            dependency_inputs: Mapping of task_id -> Finding from completed
                dependency tasks.  The worker can use these to build context.

        Returns:
            A Finding with summary, details, sources and confidence.
        """
        # Build user prompt from goal + dependency context
        if self.context_manager:
            dep_findings = []
            for dep_id, finding in dependency_inputs.items():
                dep_findings.append({
                    "task_id": dep_id,
                    "role": finding.role,
                    "summary": finding.summary,
                    "details": finding.details,
                    "sources": [s.to_dict() for s in finding.sources],
                    "confidence": finding.confidence,
                })
            budget = TokenBudget(self.context_manager.worker_budget.max_tokens)
            user_input = self.context_manager.build_worker_context(
                task_goal=self.task.goal,
                task_inputs=self.task.inputs,
                dependency_findings=dep_findings,
                budget=budget,
            )
            user_input += "\n\n请完成上述任务，并在最终回答中输出符合要求的 JSON 格式结果。"
        else:
            prompt_parts = [f"任务目标: {self.task.goal}"]

            if dependency_inputs:
                prompt_parts.append("\n【前置任务结果】")
                for dep_id, finding in dependency_inputs.items():
                    prompt_parts.append(f"\n来自 {dep_id}:")
                    prompt_parts.append(finding.to_planner_context())
                    if finding.details:
                        details_json = json.dumps(finding.details, ensure_ascii=False, indent=2)
                        prompt_parts.append(f"详细数据: {details_json[:2000]}")

            prompt_parts.append(
                "\n请完成上述任务，并在最终回答中输出符合要求的 JSON 格式结果。"
            )
            user_input = "\n".join(prompt_parts)

        logger.info(f"[Worker {self.task.task_id}] Executing role={self.task.role}, goal={self.task.goal[:60]}...")

        # Run ReAct loop
        agent_msg: AgentMessage = await self.run(user_input, context=None)

        # Parse result into Finding
        content = agent_msg.content
        if isinstance(content, dict):
            # ReActAgent returns {"answer": str, "summary": str}
            answer = content.get("answer", "")
            if answer:
                raw_result = self._extract_json_from_text(answer)
            else:
                raw_result = {"summary": content.get("summary", ""), "details": {}}
        elif isinstance(content, str):
            raw_result = self._extract_json_from_text(content)
        else:
            raw_result = {"summary": str(content)[:200], "details": {}}

        finding = Finding.from_agent_result(
            task_id=self.task.task_id,
            role=self.task.role,
            result=raw_result,
        )

        logger.info(
            f"[Worker {self.task.task_id}] Completed: summary_len={len(finding.summary)}, "
            f"confidence={finding.confidence:.2f}, sources={len(finding.sources)}"
        )
        return finding

    def _extract_json_from_text(self, text: str) -> dict[str, Any]:
        """Try to extract JSON from agent text output."""
        # Try markdown code block
        for marker in ("```json", "```"):
            if marker in text:
                try:
                    json_part = text.split(marker, 1)[1].split("```", 1)[0]
                    return json.loads(json_part.strip())
                except (IndexError, json.JSONDecodeError):
                    continue

        # Try raw JSON array/object with stack-based bracket matching
        for start_char in ("{", "["):
            idx = text.find(start_char)
            if idx == -1:
                continue
            end_char = "}" if start_char == "{" else "]"
            stack = 0
            in_string = False
            escape = False
            for i, ch in enumerate(text[idx:], start=idx):
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == start_char:
                    stack += 1
                elif ch == end_char:
                    stack -= 1
                    if stack == 0:
                        try:
                            return json.loads(text[idx:i + 1])
                        except json.JSONDecodeError:
                            break

        # Fallback: wrap text as summary
        return {
            "summary": text[:500] + "..." if len(text) > 500 else text,
            "details": {"raw_text": text},
            "sources": [],
            "confidence": 0.5,
        }
