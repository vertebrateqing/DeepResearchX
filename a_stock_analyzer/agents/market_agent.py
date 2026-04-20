"""Market analysis sub-agent."""

import json
import logging
from typing import Any, Optional

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.agent import ReActAgent
from a_stock_analyzer.core.base import AgentContext, BaseSkill
from a_stock_analyzer.core.message import AgentMessage
from a_stock_analyzer.tools.akshare_data import AKShareTool
from a_stock_analyzer.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)


class MarketAnalysisAgent(ReActAgent):
    """Sub-agent for A-share market analysis.

    Analyzes market conditions, hot sectors, macro factors, and sentiment.
    """

    def __init__(
        self,
        name: str = "market_analysis",
        tools: Optional[list] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
    ):
        cfg = get_settings().agents.market_analysis
        super().__init__(
            name=name,
            system_prompt=cfg.system_prompt,
            tools=tools or [AKShareTool(), WebSearchTool()],
            skills=skills,
            model=model or cfg.model,
        )

    async def run(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run market analysis with real data."""
        logger.info(f"MarketAgent analyzing: {user_input[:100]}...")

        # First, fetch real market data
        akshare = AKShareTool()
        web_search = WebSearchTool()

        data_parts = []

        # Get market sentiment data
        try:
            sentiment_data = await akshare.execute(data_type="market_sentiment")
            data_parts.append(f"市场指数数据:\n{json.dumps(sentiment_data, ensure_ascii=False, indent=2)[:2000]}")
        except Exception as e:
            logger.warning(f"Failed to get market sentiment: {e}")

        # Search for latest market news
        try:
            news_data = await web_search.execute(
                query="A股市场 今日行情 热点板块",
                max_results=5,
            )
            news_content = "\n".join([
                f"- {r['title']}: {r['content'][:200]}"
                for r in news_data.get("results", [])
            ])
            data_parts.append(f"最新市场资讯:\n{news_content}")
        except Exception as e:
            logger.warning(f"Web search failed: {e}")

        # Combine data with user query
        combined_input = f"""{user_input}

【实时数据】
{"\n\n".join(data_parts)}

请基于以上实时数据，提供结构化的市场分析摘要，包含：
1. 市场概况
2. 热点板块
3. 宏观因素
4. 市场情绪
5. 风险提示"""

        # Run with ReAct agent
        result = await super().run(combined_input, context)

        # Ensure summary format
        if isinstance(result.content, dict):
            result.content["summary"] = self._format_summary(result.content.get("answer", ""))

        return result

    def _format_summary(self, analysis: str) -> str:
        """Format analysis into structured summary."""
        return f"""## 市场分析摘要

{analysis[:2000]}

---
*数据来源: AKShare实时数据 + Web搜索*
"""
