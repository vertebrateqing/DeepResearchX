"""Research Planner: generates and manages research plans using LLM.

The Planner is the only decision-making agent in the pipeline.
It decides WHAT to research and WHEN, while Workers decide HOW.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from deep_research.config.settings import get_settings
from deep_research.core.agent import LLMClient
from deep_research.core.finding import Finding
from deep_research.core.research_plan import ResearchPlan, TaskNode

logger = logging.getLogger(__name__)

# Valid roles for task nodes
VALID_ROLES = {"tavily_search", "doc_analysis", "cross_verify", "synthesis"}


class PlanUpdate:
    """Result of Planner evaluation — either complete or suggest new tasks."""

    def __init__(
        self,
        is_complete: bool,
        new_tasks: list[TaskNode] | None = None,
        reason: str = "",
    ) -> None:
        self.is_complete = is_complete
        self.new_tasks = new_tasks or []
        self.reason = reason


class ResearchPlanner:
    """Generates research plans and evaluates intermediate findings."""

    MAX_PLAN_RETRIES = 2
    MAX_EVAL_RETRIES = 2

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.model = get_settings().llm.model

    async def generate_plan(self, user_query: str) -> ResearchPlan:
        """Generate a research plan from user query using LLM.

        The plan is a DAG of TaskNodes that covers all aspects of the
        user's research request.
        """
        from datetime import datetime
        today = datetime.now().strftime("%Y年%m月%d日")

        prompt = f"""你是一个研究规划专家。请根据用户需求，设计一份深度调研计划。

【当前真实日期】{today}

用户需求：{user_query}

要求：
1. 将调研拆分为多个子任务，每个子任务有明确的 role 和 goal
2. role 只能从以下选择：[tavily_search, doc_analysis, cross_verify, synthesis]
   - tavily_search: 通过网络搜索获取最新资讯和观点
   - doc_analysis: 分析文档/报告中的关键信息
   - cross_verify: 交叉验证多个来源的数据一致性
   - synthesis: 综合多个信息源生成结论
3. 标注任务依赖关系（哪些任务可以并行，哪些必须串行）
4. 每个子任务只负责获取/分析一小部分信息，不要在一个任务里混合太多目标
5. 控制任务数量：简单查询2-3个任务，深度研究5-8个任务
6. 对于深度研究，建议拆分：
   - tavily_search: 搜索背景资料和最新动态
   - doc_analysis: 深度分析关键信息
   - cross_verify: 验证数据一致性
   - synthesis: 生成研究结论

输出格式（严格JSON，不要解释）：
{{
  "strategy": "整体策略说明",
  "tasks": [
    {{
      "task_id": "t1",
      "role": "tavily_search",
      "goal": "搜索...",
      "depends_on": [],
      "inputs": {{}}
    }}
  ]
}}"""

        messages = [
            {"role": "system", "content": f"你是一个研究规划助手。当前真实日期是{today}。你只输出JSON格式的研究计划。"},
            {"role": "user", "content": prompt},
        ]

        t0 = time.perf_counter()
        for attempt in range(self.MAX_PLAN_RETRIES + 1):
            try:
                response = await self.llm.chat(messages=messages, model=self.model)
                content = response["choices"][0]["message"].get("content", "")
                plan = self._parse_plan(content, user_query)
                if plan:
                    logger.info(f"[Planner] Generated plan with {len(plan.tasks)} tasks in {time.perf_counter()-t0:.2f}s")
                    return plan
            except Exception as e:
                logger.warning(f"[Planner] Plan generation attempt {attempt + 1} failed: {e}")

        # Fallback: create a minimal single-task plan
        logger.error(f"[Planner] Failed to generate plan after {time.perf_counter()-t0:.2f}s, using fallback")
        return self._fallback_plan(user_query)

    def _parse_plan(self, content: str, user_query: str) -> ResearchPlan | None:
        """Parse LLM response into ResearchPlan."""
        # Extract JSON
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = json.loads(content.strip().lstrip('\ufeff'))
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"[Planner] Failed to parse plan JSON: {content}")
            return None

        if not isinstance(data, dict) or "tasks" not in data:
            return None

        tasks = []
        seen_ids = set()
        for t_data in data["tasks"]:
            task_id = t_data.get("task_id", f"t{len(tasks) + 1}")
            # Deduplicate IDs
            if task_id in seen_ids:
                task_id = f"{task_id}_{len(seen_ids)}"
            seen_ids.add(task_id)

            role = t_data.get("role", "tavily_search")
            if role not in VALID_ROLES:
                role = "tavily_search"

            tasks.append(TaskNode(
                task_id=task_id,
                role=role,
                goal=t_data.get("goal", "调研"),
                depends_on=t_data.get("depends_on", []),
                inputs=t_data.get("inputs", {}),
            ))

        # Validate DAG (no cycles)
        if not self._is_valid_dag(tasks):
            logger.warning("[Planner] Invalid DAG detected, using fallback")
            return None

        return ResearchPlan(
            plan_id=f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            user_query=user_query,
            tasks=tasks,
            strategy=data.get("strategy", ""),
        )

    def _is_valid_dag(self, tasks: list[TaskNode]) -> bool:
        """Check if task dependencies form a valid DAG (no cycles)."""
        graph = {t.task_id: set(t.depends_on) for t in tasks}
        task_ids = {t.task_id for t in tasks}

        # Check all dependencies exist
        for deps in graph.values():
            for dep in deps:
                if dep not in task_ids:
                    return False

        # Topological sort (Kahn's algorithm)
        in_degree = {t: 0 for t in task_ids}
        for task_id, deps in graph.items():
            in_degree[task_id] = len(deps)

        queue = [t for t, d in in_degree.items() if d == 0]
        visited = 0

        while queue:
            node = queue.pop(0)
            visited += 1
            for t in task_ids:
                if node in graph.get(t, set()):
                    in_degree[t] -= 1
                    if in_degree[t] == 0:
                        queue.append(t)

        return visited == len(task_ids)

    def _fallback_plan(self, user_query: str) -> ResearchPlan:
        """Create a minimal fallback plan when LLM fails."""
        return ResearchPlan(
            plan_id=f"plan_fallback_{uuid.uuid4().hex[:6]}",
            user_query=user_query,
            tasks=[
                TaskNode(task_id="t1", role="tavily_search", goal=f"搜索{user_query}相关信息", depends_on=[]),
                TaskNode(task_id="t2", role="doc_analysis", goal=f"分析{user_query}相关文档", depends_on=["t1"]),
                TaskNode(task_id="t3", role="synthesis", goal="综合分析生成报告", depends_on=["t1", "t2"]),
            ],
            strategy="_fallback",
        )

    async def evaluate(
        self,
        plan: ResearchPlan,
        findings: list[Finding],
    ) -> PlanUpdate:
        """Evaluate if findings are sufficient or need supplementation.

        Returns PlanUpdate with new tasks if more research is needed.
        """
        if not findings:
            logger.debug("[Planner] Evaluate: no findings yet")
            return PlanUpdate(is_complete=False, reason="No findings yet")

        # Build evaluation context
        context_lines = [f"用户请求: {plan.user_query}", f"整体策略: {plan.strategy}"]
        context_lines.append("\n【已完成的任务】")
        for f in findings:
            context_lines.append(f"- {f.task_id} [{f.role}]: {f.summary}")

        prompt = f"""作为研究评估专家，请评估当前调研结果是否充分。

{chr(10).join(context_lines)}

请判断：
1. 当前发现是否充分回答了用户的原始请求？
2. 是否有重要信息缺失或需要进一步验证？
3. 是否需要补充新的调研任务？

如果结果充分，输出：
{{"is_complete": true, "reason": "原因"}}

如果需要补充，输出：
{{"is_complete": false, "reason": "原因", "new_tasks": [
  {{"task_id": "t_new_1", "role": "tavily_search", "goal": "补充调研目标", "depends_on": []}}
]}}

只输出JSON，不要解释。"""

        t0 = time.perf_counter()
        for attempt in range(self.MAX_EVAL_RETRIES + 1):
            try:
                response = await self.llm.chat(
                    messages=[
                        {"role": "system", "content": "你是一个研究评估助手，判断调研是否充分。只输出JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    model=self.model,
                )
                content = response["choices"][0]["message"].get("content", "")
                result = self._parse_evaluation(content, plan)
                logger.info(f"[Planner] Evaluation done in {time.perf_counter()-t0:.2f}s: complete={result.is_complete}")
                return result
            except Exception as e:
                logger.warning(f"[Planner] Evaluation attempt {attempt + 1} failed: {e}")

        # Fallback: assume complete if we have findings
        logger.info(f"[Planner] Evaluation failed after {time.perf_counter()-t0:.2f}s, assuming complete")
        return PlanUpdate(is_complete=True, reason="Evaluation failed, assuming complete")

    def _parse_evaluation(self, content: str, plan: ResearchPlan) -> PlanUpdate:
        """Parse evaluation response into PlanUpdate."""
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = json.loads(content.strip().lstrip('\ufeff'))
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"[Planner] Failed to parse evaluation: {content}")
            return PlanUpdate(is_complete=True, reason="Parse failed")

        is_complete = data.get("is_complete", True)
        if is_complete:
            return PlanUpdate(is_complete=True, reason=data.get("reason", ""))

        # Parse new tasks
        new_tasks = []
        existing_ids = {t.task_id for t in plan.tasks}
        for t_data in data.get("new_tasks", []):
            task_id = t_data.get("task_id", f"t_new_{len(new_tasks) + 1}")
            # Ensure unique ID
            if task_id in existing_ids:
                task_id = f"{task_id}_{uuid.uuid4().hex[:4]}"

            role = t_data.get("role", "tavily_search")
            if role not in VALID_ROLES:
                role = "tavily_search"

            new_tasks.append(TaskNode(
                task_id=task_id,
                role=role,
                goal=t_data.get("goal", "补充调研"),
                depends_on=t_data.get("depends_on", []),
                inputs=t_data.get("inputs", {}),
            ))

        return PlanUpdate(
            is_complete=False,
            new_tasks=new_tasks,
            reason=data.get("reason", ""),
        )
