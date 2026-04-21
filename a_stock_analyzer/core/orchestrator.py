"""Orchestrator agent that coordinates sub-agents for A-stock analysis.

V2 features:
- Human-in-the-loop intent clarification
- Session memory integration
- Context compression support
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Optional

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.agent import ReActAgent, SimpleAgent
from a_stock_analyzer.core.base import AgentContext, BaseAgent, BaseSkill, BaseTool
from a_stock_analyzer.core.context_compactor import ContextCompactor
from a_stock_analyzer.core.intent_clarifier import (
    ClarificationResult,
    IntentClarifier,
)
from a_stock_analyzer.core.message import AgentMessage
from a_stock_analyzer.core.report_generator import ReportGenerator
from a_stock_analyzer.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """Main orchestrator that breaks down tasks and coordinates sub-agents.

    V2 features:
    1. Intent clarification (Human-in-the-loop)
    2. Session memory (task tracking, findings, user preferences)
    3. Context compression (auto-compact at 80% threshold)
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
        self._sub_agents: dict[str, BaseAgent] = {}

        # V2 components
        self.intent_clarifier = IntentClarifier()
        self.context_compactor = ContextCompactor()
        self.memory = MemoryManager(
            session_id=session_id or self._generate_session_id(),
            user_id=user_id,
        )
        self.memory.init_session()

        # Clarification state
        self._clarification_result: Optional[ClarificationResult] = None
        self._total_clarification_rounds: int = 0

    def _generate_session_id(self) -> str:
        import uuid
        from datetime import datetime
        return f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    def register_sub_agent(self, agent: BaseAgent) -> None:
        """Register a sub-agent."""
        self._sub_agents[agent.name] = agent
        logger.info(f"Registered sub-agent: {agent.name}")

    def get_sub_agent(self, name: str) -> Optional[BaseAgent]:
        """Get a registered sub-agent."""
        return self._sub_agents.get(name)

    async def run(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run the full analysis pipeline with HITL, memory, and compression.

        Pipeline:
        1. Check for ongoing clarification and process user response
        2. If no ongoing clarification, analyze intent for missing info
        3. If missing info, return clarification prompt (HITL)
        4. If intent is clear, inject memory context and execute
        5. Track tasks in memory, compress context as needed
        6. Synthesize final report
        """
        logger.info(f"Orchestrator received request: {user_input[:100]}...")

        # Record user message in memory
        self.memory.add_user_message(user_input)

        # Detect and update user preferences from query
        detected_prefs = self.memory.detect_preferences_from_query(user_input)
        if detected_prefs:
            self.memory.update_preferences(**detected_prefs)

        # Step 1: Handle ongoing clarification
        if self._clarification_result and not self._clarification_result.complete:
            return await self._handle_clarification_response(user_input)

        # New query: reset clarification counter
        if self._clarification_result is None:
            self._total_clarification_rounds = 0

        # Step 2: Analyze intent for missing information
        # If we've already done too many rounds, skip clarification
        if self._total_clarification_rounds >= IntentClarifier.MAX_ROUNDS:
            logger.info("Max clarification rounds reached, forcing completion")
            clarification = ClarificationResult(
                complete=True,
                original_query=user_input,
                merged_query=user_input,
            )
        else:
            clarification = await self.intent_clarifier.analyze(user_input)

        if not clarification.complete:
            # Need clarification - HITL
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

        # Intent is clear - proceed to execution
        merged_query = clarification.merged_query or user_input
        return await self._execute_query(merged_query, user_input, context)

    async def _execute_query(
        self,
        merged_query: str,
        original_query: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Execute analysis with a clarified query (skip re-analysis)."""
        logger.info(f"Merged query: {merged_query[:100]}...")

        # Build context from memory
        memory_context = self.memory.build_context_prompt()

        # Inject current date so LLM agents can self-resolve relative temporal words
        from datetime import datetime
        now = datetime.now()
        date_context = f"【当前真实日期：{now.strftime('%Y年%m月%d日')}】"

        if memory_context:
            merged_query = f"{date_context}\n\n{memory_context}\n\n---\n\n当前请求: {merged_query}"
        else:
            merged_query = f"{date_context}\n\n当前请求: {merged_query}"

        # Classify task and execute
        task_type = await self._classify_task(merged_query)
        logger.info(f"Classified task type: {task_type}")

        # Record task start in memory
        main_task = self.memory.start_task(
            task_type=task_type,
            agent=self.name,
            inputs={"query": original_query, "merged_query": merged_query},
        )

        # Execute based on task type
        if task_type == "full_analysis":
            result = await self._run_full_analysis(merged_query, context, task_type="full_analysis")
        elif task_type == "market_only":
            result = await self._run_sub_agent("market_analysis", merged_query, context)
        elif task_type == "company_qa":
            # For company-specific questions, run full analysis but focus on the target company
            result = await self._run_full_analysis(merged_query, context, task_type="company_qa")
        elif task_type == "industry_recommend":
            result = await self._run_industry_recommendation(merged_query, context)
        else:
            result = await self._run_sub_agent("financial_rag", merged_query, context)

        # Record task completion
        content = result.content
        summary = content.get("report", str(content)) if isinstance(content, dict) else str(content)
        self.memory.update_task(
            task_id=main_task.task_id,
            status="completed",
            result={"summary": summary[:500]},
        )

        # Add key finding
        self.memory.add_finding(
            source="orchestrator",
            content=summary[:1000],
            confidence=0.7,
            expires_hours=24,
        )

        # Record assistant response
        self.memory.add_assistant_message(summary[:500])

        # Save session state
        await self.memory.save()

        return result

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

        # Process user response
        result = await self.intent_clarifier.process_user_response(
            self._clarification_result,
            user_response,
        )
        self._clarification_result = result
        self._total_clarification_rounds += 1

        if result.complete:
            # All clarified, rewrite query with LLM and proceed
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

            # Clear clarification state and proceed directly to execution,
            # bypassing re-analysis to avoid infinite loops
            self._clarification_result = None

            return await self._execute_query(merged_query, result.original_query)

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

    async def _classify_task(self, user_input: str) -> str:
        """Classify the user request into a task type."""
        # Deterministic pre-check: if query contains a 6-digit stock code, it's company_qa
        if re.search(r"(?<!\d)\d{6}(?!\d)", user_input):
            logger.info("[Orchestrator] Detected stock code in query, classifying as company_qa")
            return "company_qa"

        prompt = f"""请分析以下用户需求，判断其类型。只返回以下类型之一，不要解释：

类型选项：
- full_analysis: 完整投资分析（包含市场、行业、公司、财报）
- market_only: 仅市场分析
- industry_recommend: 行业推荐
- company_qa: 针对具体公司的问答
- other: 其他

用户需求：{user_input}

类型："""

        try:
            result = await self.llm_agent.run_simple(prompt)
            result = result.strip().lower()

            valid_types = ["full_analysis", "market_only", "industry_recommend", "company_qa"]
            for vt in valid_types:
                if vt in result:
                    return vt
            return "full_analysis"
        except Exception as e:
            logger.warning(f"Task classification failed: {e}, defaulting to full_analysis")
            return "full_analysis"

    async def _run_full_analysis(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
        task_type: str = "full_analysis",
    ) -> AgentMessage:
        """Run the complete analysis pipeline with all sub-agents."""
        is_company_focused = task_type == "company_qa"

        logger.info(f"[Orchestrator] Phase 1: Market + Industry (parallel), task_type={task_type}")
        # Phase 1: Market and Industry analysis in parallel
        market_task = self._dispatch_sub_agent(
            "market_analysis",
            f"分析当前A股市场情况，重点关注：{user_input}",
            context,
        )
        industry_task = self._dispatch_sub_agent(
            "industry_screening",
            f"筛选最具投资价值的A股行业，考虑：{user_input}",
            context,
        )

        market_result, industry_result = await asyncio.gather(
            market_task, industry_task, return_exceptions=True
        )

        # Extract summaries
        market_summary = self._extract_summary(market_result)
        industry_summary = self._extract_summary(industry_result)
        logger.info(f"[Orchestrator] Phase 1 done: market_summary_len={len(market_summary)}, industry_summary_len={len(industry_summary)}")

        # Record findings
        if market_summary:
            self.memory.add_finding(
                source="market_analysis",
                content=market_summary[:500],
                related_entities=["A股", "市场"],
            )
        if industry_summary:
            self.memory.add_finding(
                source="industry_screening",
                content=industry_summary[:500],
                related_entities=["行业", "投资"],
            )

        # Phase 2: Company selection
        if is_company_focused:
            # User has specified a company — analyze it directly with industry context
            logger.info("[Orchestrator] Phase 2: Company analysis (focused)")
            company_prompt = (
                f"用户关注的公司：{user_input}\n\n"
                f"相关行业背景：\n\n{industry_summary}\n\n"
                "请重点分析用户关注的公司，包括：\n"
                "1. 公司基本面和核心业务\n"
                "2. 所属行业景气度\n"
                "3. 关键财务指标\n"
                "4. 同行业对比\n"
                "5. 竞争优势和风险"
            )
        else:
            # General stock-picking flow
            logger.info("[Orchestrator] Phase 2: Company selection (screening)")
            company_prompt = f"基于以下行业分析结果，选取TopN值得投资的公司：\n\n{industry_summary}"

        company_task = self._dispatch_sub_agent(
            "company_selection",
            company_prompt,
            context,
        )

        # Phase 3: Financial RAG analysis
        if is_company_focused:
            financial_prompt = (
                f"用户原始需求：{user_input}\n\n"
                f"对该公司进行财报深度分析。行业背景：\n\n{industry_summary}"
            )
        else:
            financial_prompt = (
                f"用户原始需求：{user_input}\n\n"
                f"对推荐的公司进行财报深度分析。行业分析：\n\n{industry_summary}"
            )

        logger.info("[Orchestrator] Phase 3: Financial RAG")
        financial_task = self._dispatch_sub_agent(
            "financial_rag",
            financial_prompt,
            context,
        )

        company_result, financial_result = await asyncio.gather(
            company_task, financial_task, return_exceptions=True
        )

        company_summary = self._extract_summary(company_result)
        financial_summary = self._extract_summary(financial_result)
        logger.info(f"[Orchestrator] Phase 2+3 done: company_summary_len={len(company_summary)}, financial_summary_len={len(financial_summary)}")

        # Record findings
        if company_summary:
            self.memory.add_finding(
                source="company_selection",
                content=company_summary[:500],
                related_entities=["公司", "股票"],
            )
        if financial_summary:
            self.memory.add_finding(
                source="financial_rag",
                content=financial_summary[:500],
                related_entities=["财报", "财务分析"],
            )

        # Phase 4: Synthesize final report
        logger.info("[Orchestrator] Phase 4: Synthesizing final report")
        final_report = await self._synthesize_report(
            user_input=user_input,
            market_summary=market_summary,
            industry_summary=industry_summary,
            company_summary=company_summary,
            financial_summary=financial_summary,
        )
        logger.info(f"[Orchestrator] Final report synthesized, length={len(final_report)}")

        # Phase 5: Generate and save report files
        sections = {
            "market": market_summary,
            "industry": industry_summary,
            "company": company_summary,
            "financial": financial_summary,
        }
        md_path, pdf_path = await self._generate_and_save_report(
            user_input=user_input,
            final_report=final_report,
            sections=sections,
        )

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
            },
            task_id=context.task_id if context else None,
            metadata=metadata,
        )

    async def _run_industry_recommendation(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run industry recommendation with market context."""
        market_task = self._dispatch_sub_agent(
            "market_analysis",
            f"分析当前市场情况：{user_input}",
            context,
        )
        industry_task = self._dispatch_sub_agent(
            "industry_screening",
            f"推荐投资价值行业：{user_input}",
            context,
        )

        market_result, industry_result = await asyncio.gather(
            market_task, industry_task, return_exceptions=True
        )

        market_summary = self._extract_summary(market_result)
        industry_summary = self._extract_summary(industry_result)

        report = await self._synthesize_report(
            user_input=user_input,
            market_summary=market_summary,
            industry_summary=industry_summary,
            company_summary="",
            financial_summary="",
        )

        # Generate and save report files
        sections = {
            "market": market_summary,
            "industry": industry_summary,
        }
        md_path, pdf_path = await self._generate_and_save_report(
            user_input=user_input,
            final_report=report,
            sections=sections,
        )

        metadata: dict[str, Any] = {}
        if md_path:
            metadata["report_md_path"] = str(md_path)
        if pdf_path:
            metadata["report_pdf_path"] = str(pdf_path)

        return AgentMessage.create_result(
            sender=self.name,
            receiver="user",
            result={
                "report": report,
                "sections": sections,
            },
            task_id=context.task_id if context else None,
            metadata=metadata,
        )

    async def _run_sub_agent(
        self,
        agent_name: str,
        task_description: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run a single sub-agent."""
        logger.info(f"[Orchestrator] Dispatching sub-agent '{agent_name}', input_len={len(task_description)}")
        agent = self._sub_agents.get(agent_name)
        if not agent:
            logger.error(f"[Orchestrator] Sub-agent '{agent_name}' not found")
            return AgentMessage.create_error(
                sender=self.name,
                receiver="user",
                error_message=f"Sub-agent '{agent_name}' not found",
            )

        sub_context = AgentContext(
            agent_name=agent_name,
            parent_agent=self.name,
            task_id=context.task_id if context else None,
            metadata=context.metadata if context else {},
        )

        result = await agent.run(task_description, sub_context)
        summary = self._extract_summary(result)
        logger.info(f"[Orchestrator] Sub-agent '{agent_name}' finished, summary_len={len(summary)}")
        return result

    async def _dispatch_sub_agent(
        self,
        agent_name: str,
        task_description: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Dispatch a task to a sub-agent."""
        return await self._run_sub_agent(agent_name, task_description, context)

    def _extract_summary(self, result: Any) -> str:
        """Extract summary from sub-agent result."""
        if isinstance(result, Exception):
            return f"Error: {str(result)}"

        if isinstance(result, AgentMessage):
            content = result.content
            if isinstance(content, dict):
                return content.get("summary", "") or content.get("answer", "") or str(content)
            return str(content)

        return str(result)

    async def _generate_and_save_report(
        self,
        user_input: str,
        final_report: str,
        sections: dict[str, str],
    ) -> tuple[Path | None, Path | None]:
        """Generate markdown/PDF report and save to output directory.

        Returns:
            (md_path, pdf_path) or (None, None) on failure
        """
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

    async def _synthesize_report(
        self,
        user_input: str,
        market_summary: str,
        industry_summary: str,
        company_summary: str,
        financial_summary: str,
    ) -> str:
        """Synthesize final investment report from sub-agent summaries."""
        sections = []
        if market_summary:
            sections.append(f"## 市场分析\n\n{market_summary}")
        if industry_summary:
            sections.append(f"## 行业推荐\n\n{industry_summary}")
        if company_summary:
            sections.append(f"## 公司选取\n\n{company_summary}")
        if financial_summary:
            sections.append(f"## 财报深度分析\n\n{financial_summary}")

        combined = "\n\n---\n\n".join(sections)

        prompt = f"""你是一位资深投资顾问。请基于以下各模块的分析摘要，生成一份完整、专业、结构化的投资分析报告。

原始需求：{user_input}

各模块分析摘要：

{combined}

请生成最终报告，要求：
1. 报告结构清晰，包含执行摘要、详细分析和投资建议
2. 数据支撑充分，逻辑严谨
3. 风险提示明确
4. 语言专业但易懂

最终报告："""

        try:
            report = await self.llm_agent.run_simple(prompt)
            return report
        except Exception as e:
            logger.error(f"Report synthesis failed: {e}")
            return combined
