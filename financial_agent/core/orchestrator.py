"""Orchestrator agent — Planner-Worker-Synthesizer (PWS) architecture.

V3 features:
- Dynamic research planning via LLM (no hard-coded pipeline)
- Generic workers with role-based prompts
- DAG-based parallel task execution
- Layered context management with token budgets
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient, SimpleAgent
from financial_agent.core.base import AgentContext, BaseAgent, BaseSkill, BaseTool
from financial_agent.core.context_manager import ContextManager
from financial_agent.core.intent_clarifier import (
    ClarificationResult,
    IntentClarifier,
)
from financial_agent.core.message import AgentMessage
from financial_agent.core.planner import PlanUpdate, ResearchPlanner
from financial_agent.core.report_generator import ReportGenerator
from financial_agent.core.research_plan import DAGScheduler, ResearchPlan, TaskNode
from financial_agent.core.worker import GenericWorker
from financial_agent.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """Main orchestrator using Planner-Worker-Synthesizer pattern.

    Pipeline:
    1. Intent clarification (HITL)
    2. Planner generates research plan (DAG)
    3. DAGScheduler dispatches GenericWorkers in parallel
    4. Planner evaluates findings, optionally adds tasks
    5. Synthesizer generates final report
    6. Report exported to MD/PDF
    """

    def __init__(
        self,
        name: str = "orchestrator",
        system_prompt: str = "",
        tools: Optional[list[BaseTool]] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: str = "anonymous",
    ):
        cfg = get_settings().agents.orchestrator
        super().__init__(
            name=name,
            system_prompt=system_prompt or cfg.system_prompt,
            tools=tools,
            skills=skills,
        )
        self.model = model or cfg.model
        self.llm_agent = SimpleAgent(
            name=f"{name}_llm",
            system_prompt=self.system_prompt,
            model=self.model,
        )

        # V3 components
        self.intent_clarifier = IntentClarifier()
        self.planner = ResearchPlanner()
        self.scheduler = DAGScheduler(max_parallel=3, max_retries=2)
        self.context_manager = ContextManager()
        self.memory = MemoryManager(
            session_id=session_id or self._generate_session_id(),
            user_id=user_id,
        )
        self.memory.init_session()

        # Clarification state
        self._clarification_result: Optional[ClarificationResult] = None
        self._total_clarification_rounds: int = 0

    def _generate_session_id(self) -> str:
        return f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    async def run(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run the full deepresearch pipeline."""
        logger.info(f"Orchestrator received request: {user_input[:100]}...")

        # Record user message
        self.memory.add_user_message(user_input)
        detected_prefs = self.memory.detect_preferences_from_query(user_input)
        if detected_prefs:
            self.memory.update_preferences(**detected_prefs)

        # Step 1: Handle ongoing clarification
        if self._clarification_result and not self._clarification_result.complete:
            return await self._handle_clarification_response(user_input)

        if self._clarification_result is None:
            self._total_clarification_rounds = 0

        # Step 2: Intent clarification
        if self._total_clarification_rounds >= IntentClarifier.MAX_ROUNDS:
            clarification = ClarificationResult(
                complete=True,
                original_query=user_input,
                merged_query=user_input,
            )
        else:
            clarification = await self.intent_clarifier.analyze(user_input)

        if not clarification.complete:
            self._clarification_result = clarification
            self.memory.session.clarification_state = {
                "status": "clarifying",
                "round": clarification.rounds_completed,
                "missing_slots": [
                    {"name": s.slot_name, "question": s.question}
                    for s in clarification.get_unconfirmed_slots()
                ],
            }
            await self.memory.save(sync_long_term=False)

            prompt = self.intent_clarifier.generate_clarification_prompt(clarification)
            self.memory.add_assistant_message(prompt)

            return AgentMessage.create_result(
                sender=self.name,
                receiver="user",
                result={
                    "requires_clarification": True,
                    "prompt": prompt,
                    "missing_slots": [
                        s.slot_name for s in clarification.get_unconfirmed_slots()
                    ],
                },
            )

        # Step 3: Execute deepresearch
        merged_query = clarification.merged_query or user_input
        return await self._execute_research(merged_query, user_input, context)

    async def _execute_research(
        self,
        merged_query: str,
        original_query: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Execute research via Planner-Worker-Synthesizer."""
        # Inject current date
        from datetime import datetime
        now = datetime.now()
        date_context = f"【当前真实日期：{now.strftime('%Y年%m月%d日')}】"
        enriched_query = f"{date_context}\n\n{merged_query}"

        logger.info(f"[Orchestrator] Starting deepresearch for: {enriched_query[:100]}...")
        logger.debug(f"[Orchestrator] Full enriched query: {enriched_query}")
        self.context_manager.reset()

        # Record main task
        main_task = self.memory.start_task(
            task_type="deepresearch",
            agent=self.name,
            inputs={"query": original_query, "enriched_query": enriched_query},
        )

        # --- Phase 1: Generate plan ---
        logger.info("[Orchestrator] Phase 1: Generating research plan")
        plan = await self.planner.generate_plan(enriched_query)
        logger.info(f"[Orchestrator] Plan generated: {len(plan.tasks)} tasks, strategy={plan.strategy}")
        for t in plan.tasks:
            logger.debug(f"[Orchestrator] Plan task: {t.task_id} role={t.role} deps={t.depends_on} goal={t.goal[:60]}")

        # --- Phase 2: Execute plan ---
        logger.info("[Orchestrator] Phase 2: Executing research plan")
        self._current_plan = plan.tasks
        findings = await self.scheduler.execute(
            plan,
            worker_factory=self._create_worker,
        )

        # --- Phase 3: Evaluate and optionally extend ---
        logger.info(f"[Orchestrator] Phase 3: Evaluating {len(findings)} findings")
        plan_update = await self.planner.evaluate(plan, findings)

        if not plan_update.is_complete and plan_update.new_tasks:
            logger.info(f"[Orchestrator] Extending plan with {len(plan_update.new_tasks)} new tasks")
            plan.tasks.extend(plan_update.new_tasks)
            additional_findings = await self.scheduler.execute(
                plan,
                worker_factory=self._create_worker,
            )
            findings.extend(additional_findings)

        # --- Phase 4: Synthesize report ---
        logger.info("[Orchestrator] Phase 4: Synthesizing report")
        logger.debug(f"[Orchestrator] Synthesizer input: {len(findings)} findings, query={original_query[:100]}")
        final_report = await self._synthesize_from_findings(original_query, findings)

        # --- Phase 5: Generate and save report ---
        sections = self._build_sections(findings)
        md_path, pdf_path = await self._generate_and_save_report(
            user_input=original_query,
            final_report=final_report,
            sections=sections,
        )

        # Record completion
        self.memory.update_task(
            task_id=main_task.task_id,
            status="completed",
            result={"summary": final_report[:500]},
        )
        self.memory.add_finding(
            source="orchestrator",
            content=final_report[:1000],
            confidence=0.7,
            expires_hours=24,
        )
        self.memory.add_assistant_message(final_report[:500])
        await self.memory.save()

        metadata: dict[str, Any] = {}
        if md_path:
            metadata["report_md_path"] = str(md_path)
        if pdf_path:
            metadata["report_pdf_path"] = str(pdf_path)

        return AgentMessage.create_result(
            sender=self.name,
            receiver="user",
            result={
                "report": final_report,
                "sections": sections,
                "findings_count": len(findings),
            },
            task_id=context.task_id if context else None,
            metadata=metadata,
        )

    def _create_worker(self, task: TaskNode):
        """Factory for DAGScheduler — returns a callable that executes the task."""
        async def execute():
            # Build dependency inputs
            dep_inputs = {}
            for dep_id in task.depends_on:
                # Find completed task with this ID
                for t in getattr(self, "_current_plan", []):
                    if t.task_id == dep_id and t.output:
                        dep_inputs[dep_id] = t.output
                        break

            worker = GenericWorker(task, context_manager=self.context_manager)
            return await worker.execute(dep_inputs)
        return execute

    async def _handle_clarification_response(
        self,
        user_response: str,
    ) -> AgentMessage:
        """Handle user's response to a clarification prompt."""
        if self._clarification_result is None:
            return AgentMessage.create_error(
                sender=self.name,
                receiver="user",
                error_message="No active clarification session",
            )

        result = await self.intent_clarifier.process_user_response(
            self._clarification_result,
            user_response,
        )
        self._clarification_result = result
        self._total_clarification_rounds += 1

        if result.complete:
            confirmed_slots = [s for s in result.missing_slots if s.confirmed]
            rewritten = await self.intent_clarifier.rewrite_query(
                result.original_query,
                confirmed_slots,
            )
            merged_query = rewritten or result.merged_query
            logger.info(f"Clarified query (LLM rewritten): {merged_query[:100]}...")

            self.memory.session.clarification_state = {
                "status": "completed",
                "rounds": result.rounds_completed,
                "merged_query": merged_query,
            }
            await self.memory.save()
            self._clarification_result = None
            return await self._execute_research(merged_query, result.original_query)

        # Still needs more clarification
        self.memory.session.clarification_state = {
            "status": "clarifying",
            "round": result.rounds_completed,
        }
        await self.memory.save(sync_long_term=False)

        prompt = self.intent_clarifier.generate_clarification_prompt(result)
        self.memory.add_assistant_message(prompt)

        return AgentMessage.create_result(
            sender=self.name,
            receiver="user",
            result={
                "requires_clarification": True,
                "prompt": prompt,
                "round": result.rounds_completed,
            },
        )

    async def _synthesize_from_findings(
        self,
        user_query: str,
        findings: list,
    ) -> str:
        """Generate final report from all findings."""
        if not findings:
            return "未能获取足够的研究信息来生成报告。"

        # Build synthesizer context with budget
        findings_dicts = [f.to_dict() for f in findings]
        context = self.context_manager.build_synthesizer_context(
            user_query=user_query,
            findings=findings_dicts,
        )

        prompt = f"""你是一位资深投资分析师。请基于以下研究发现，生成一份完整、专业、结构化的分析报告。

{context}

请生成最终报告，要求：
1. 报告结构清晰，包含执行摘要、详细分析和结论
2. 数据支撑充分，逻辑严谨
3. 每个关键结论标注数据来源和置信度
4. 承认信息缺口和不确定性
5. 语言专业但易懂

最终报告："""

        try:
            report = await self.llm_agent.run_simple(prompt)
            return report
        except Exception as e:
            logger.error(f"Report synthesis failed: {e}")
            # Fallback: concatenate summaries
            summaries = [f"[{f.role}] {f.summary}" for f in findings]
            return "\n\n".join(summaries)

    def _build_sections(self, findings: list) -> dict[str, str]:
        """Group findings by role for section display."""
        sections: dict[str, list[str]] = {}
        for f in findings:
            role = f.role
            if role not in sections:
                sections[role] = []
            sections[role].append(f.summary)
        return {k: "\n\n".join(v) for k, v in sections.items()}

    async def _generate_and_save_report(
        self,
        user_input: str,
        final_report: str,
        sections: dict[str, str],
    ) -> tuple[Path | None, Path | None]:
        """Generate markdown/PDF report and save."""
        try:
            output_dir = Path(get_settings().output.output_dir)
            generator = ReportGenerator()
            markdown = generator.generate_markdown(
                user_query=user_input,
                final_report=final_report,
                sections=sections,
                session_id=self.memory.session_id,
            )
            md_path, pdf_path = generator.save(
                output_dir=output_dir,
                session_id=self.memory.session_id,
                markdown=markdown,
            )
            logger.info(f"[Orchestrator] Report saved: md={md_path}, pdf={pdf_path}")
            return md_path, pdf_path
        except Exception as e:
            logger.warning(f"[Orchestrator] Report generation failed: {e}")
            return None, None
