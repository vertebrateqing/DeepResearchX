"""Market analysis skill."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from financial_agent.config.settings import get_settings
from financial_agent.core.base import BaseSkill, SkillContext
from financial_agent.core.agent import SimpleAgent

logger = logging.getLogger(__name__)


class MarketAnalysisInput(BaseModel):
    focus_areas: list[str] = Field(default_factory=list, description="重点关注领域")
    time_horizon: str = Field(default="短期", description="时间维度: 短期/中期/长期")


class MarketAnalysisOutput(BaseModel):
    market_overview: str = Field(default="", description="市场整体概况")
    hot_sectors: list[dict[str, Any]] = Field(default_factory=list, description="热点板块")
    macro_factors: list[str] = Field(default_factory=list, description="宏观影响因素")
    sentiment: str = Field(default="", description="市场情绪")
    risks: list[str] = Field(default_factory=list, description="风险因素")


class MarketAnalysisSkill(BaseSkill):
    """Analyze A-share market conditions."""

    name = "market_analysis"
    description = "分析A股市场整体情况，包括大盘走势、热点板块、宏观因素和市场情绪"
    input_schema = MarketAnalysisInput
    output_schema = MarketAnalysisOutput

    def __init__(self) -> None:
        cfg = get_settings().agents.market_analysis
        self.agent = SimpleAgent(
            name="market_analysis_skill",
            system_prompt=cfg.system_prompt,
            model=cfg.model,
        )

    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        """Execute market analysis."""
        parsed = MarketAnalysisInput(**inputs)

        prompt = f"""请对当前A股市场进行全面分析。

分析维度：
- 重点关注：{', '.join(parsed.focus_areas) if parsed.focus_areas else '全面分析'}
- 时间维度：{parsed.time_horizon}

请提供以下方面的分析：
1. 市场整体走势和关键指数表现
2. 当前热点板块和领涨行业
3. 宏观经济数据和政策影响
4. 市场情绪和资金流向
5. 主要风险因素

请以结构化JSON格式返回分析结果。"""

        try:
            result = await self.agent.run_simple(prompt)
            # Try to parse as JSON, fallback to text
            try:
                data = json.loads(result)
            except json.JSONDecodeError:
                data = {"raw_analysis": result}

            output = MarketAnalysisOutput(**data)
            return output.model_dump()
        except Exception as e:
            logger.error(f"Market analysis failed: {e}")
            return MarketAnalysisOutput(
                market_overview=f"分析失败: {str(e)}",
            ).model_dump()
