"""Company selection sub-agent."""

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


class CompanySelectionAgent(ReActAgent):
    """Sub-agent for selecting top companies from industries.

    Analyzes company fundamentals, valuation, and competitive advantages.
    """

    def __init__(
        self,
        name: str = "company_selection",
        tools: Optional[list] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
    ):
        cfg = get_settings().agents.company_selection
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
        """Run company selection with real data."""
        logger.info(f"CompanyAgent selecting: {user_input[:100]}...")

        akshare = AKShareTool()
        web_search = WebSearchTool()

        data_parts = []

        # Get stock list with industry info
        try:
            stock_list = await akshare.execute(data_type="stock_list", limit=100)
            data_parts.append(f"A股股票列表:\n{json.dumps(stock_list, ensure_ascii=False, indent=2)[:2000]}")
        except Exception as e:
            logger.warning(f"Failed to get stock list: {e}")

        # Search for company analysis
        try:
            search_data = await web_search.execute(
                query="A股优质公司 基本面分析 投资价值",
                max_results=5,
            )
            search_content = "\n".join([
                f"- {r['title']}: {r['content'][:200]}"
                for r in search_data.get("results", [])
            ])
            data_parts.append(f"公司分析资讯:\n{search_content}")
        except Exception as e:
            logger.warning(f"Web search failed: {e}")

        combined_input = f"""{user_input}

【实时数据】
{"\n\n".join(data_parts)}

请基于以上数据，选取Top 10 值得投资的公司。

每家公司需包含：
1. 公司名称和代码
2. 所属行业
3. 核心投资逻辑
4. 关键财务指标（如有数据）
5. 估值评估
6. 竞争优势
7. 风险因素"""

        result = await super().run(combined_input, context)

        if isinstance(result.content, dict):
            result.content["summary"] = self._format_summary(result.content.get("answer", ""))

        return result

    def _format_summary(self, analysis: str) -> str:
        """Format analysis into structured summary."""
        return f"""## 公司选取摘要

{analysis[:3000]}

---
*数据来源: AKShare + Web搜索*
"""
