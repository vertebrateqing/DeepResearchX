"""Industry screening sub-agent."""

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


class IndustryScreeningAgent(ReActAgent):
    """Sub-agent for industry screening and ranking.

    Evaluates industries based on prosperity, valuation, and policy support.
    """

    def __init__(
        self,
        name: str = "industry_screening",
        tools: Optional[list] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
    ):
        cfg = get_settings().agents.industry_screening
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
        """Run industry screening with real data."""
        logger.info(f"IndustryAgent screening: {user_input[:100]}...")

        akshare = AKShareTool()
        web_search = WebSearchTool()

        data_parts = []

        # Get industry board data
        try:
            industry_data = await akshare.execute(data_type="industry_board", limit=50)
            data_parts.append(f"行业板块数据:\n{json.dumps(industry_data, ensure_ascii=False, indent=2)[:3000]}")
        except Exception as e:
            logger.warning(f"Failed to get industry data: {e}")

        # Search for industry news
        try:
            news_data = await web_search.execute(
                query="A股行业 景气度 政策支持 2024",
                max_results=5,
            )
            news_content = "\n".join([
                f"- {r['title']}: {r['content'][:200]}"
                for r in news_data.get("results", [])
            ])
            data_parts.append(f"行业最新资讯:\n{news_content}")
        except Exception as e:
            logger.warning(f"Web search failed: {e}")

        combined_input = f"""{user_input}

【实时数据】
{"\n\n".join(data_parts)}

请基于以上数据，筛选并推荐最具投资价值的A股行业（Top 5-10）。

每个行业需包含：
1. 行业名称
2. 景气度评估
3. 估值水平
4. 政策支持情况
5. 推荐逻辑
6. 主要风险"""

        result = await super().run(combined_input, context)

        if isinstance(result.content, dict):
            result.content["summary"] = self._format_summary(result.content.get("answer", ""))

        return result

    def _format_summary(self, analysis: str) -> str:
        """Format analysis into structured summary."""
        return f"""## 行业筛选摘要

{analysis[:2500]}

---
*数据来源: AKShare行业数据 + Web搜索*
"""
