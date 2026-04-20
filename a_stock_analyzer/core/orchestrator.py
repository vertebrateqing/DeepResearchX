"""Orchestrator agent that coordinates sub-agents for A-stock analysis."""

import asyncio
import logging
from typing import Any, Optional

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.agent import ReActAgent, SimpleAgent
from a_stock_analyzer.core.base import AgentContext, BaseAgent, BaseSkill, BaseTool
from a_stock_analyzer.core.message import AgentMessage

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """Main orchestrator that breaks down tasks and coordinates sub-agents.

    The orchestrator:
    1. Receives user request
    2. Breaks it into sub-tasks
    3. Dispatches sub-tasks to specialized sub-agents in parallel
    4. Collects structured summaries from sub-agents
    5. Synthesizes final investment report
    """

    def __init__(
        self,
        name: str = "orchestrator",
        system_prompt: str = "",
        tools: Optional[list[BaseTool]] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
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
        """Run the full analysis pipeline.

        Pipeline:
        1. Parse user intent and determine analysis type
        2. Route to appropriate sub-agents
        3. Collect results in parallel
        4. Synthesize final report
        """
        logger.info(f"Orchestrator received request: {user_input[:100]}...")

        # Step 1: Determine the task type
        task_type = await self._classify_task(user_input)
        logger.info(f"Classified task type: {task_type}")

        # Step 2: Route to sub-agents based on task type
        if task_type == "full_analysis":
            return await self._run_full_analysis(user_input, context)
        elif task_type == "market_only":
            return await self._run_sub_agent("market_analysis", user_input, context)
        elif task_type == "company_qa":
            return await self._run_sub_agent("financial_rag", user_input, context)
        elif task_type == "industry_recommend":
            return await self._run_industry_recommendation(user_input, context)
        else:
            # Default: try to answer directly or dispatch to financial RAG
            return await self._run_sub_agent("financial_rag", user_input, context)

    async def _classify_task(self, user_input: str) -> str:
        """Classify the user request into a task type."""
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
    ) -> AgentMessage:
        """Run the complete analysis pipeline with all sub-agents."""
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

        # Phase 2: Company selection based on industry results
        company_task = self._dispatch_sub_agent(
            "company_selection",
            f"基于以下行业分析结果，选取TopN值得投资的公司：\n\n{industry_summary}",
            context,
        )

        # Phase 3: Financial RAG analysis for top companies
        financial_task = self._dispatch_sub_agent(
            "financial_rag",
            f"对推荐的公司进行财报深度分析。行业分析：\n\n{industry_summary}",
            context,
        )

        company_result, financial_result = await asyncio.gather(
            company_task, financial_task, return_exceptions=True
        )

        company_summary = self._extract_summary(company_result)
        financial_summary = self._extract_summary(financial_result)

        # Phase 4: Synthesize final report
        final_report = await self._synthesize_report(
            user_input=user_input,
            market_summary=market_summary,
            industry_summary=industry_summary,
            company_summary=company_summary,
            financial_summary=financial_summary,
        )

        return AgentMessage.create_result(
            sender=self.name,
            receiver="user",
            result={
                "report": final_report,
                "sections": {
                    "market": market_summary,
                    "industry": industry_summary,
                    "company": company_summary,
                    "financial": financial_summary,
                },
            },
            task_id=context.task_id if context else None,
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

        return AgentMessage.create_result(
            sender=self.name,
            receiver="user",
            result={
                "report": report,
                "sections": {
                    "market": market_summary,
                    "industry": industry_summary,
                },
            },
            task_id=context.task_id if context else None,
        )

    async def _run_sub_agent(
        self,
        agent_name: str,
        task_description: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run a single sub-agent."""
        agent = self._sub_agents.get(agent_name)
        if not agent:
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

        return await agent.run(task_description, sub_context)

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
                # Try to get summary or answer
                return content.get("summary", "") or content.get("answer", "") or str(content)
            return str(content)

        return str(result)

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
            return combined  # Fallback to combined summaries
