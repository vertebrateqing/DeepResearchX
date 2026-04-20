"""Industry screening skill."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.base import BaseSkill, SkillContext
from a_stock_analyzer.core.agent import SimpleAgent

logger = logging.getLogger(__name__)


class IndustryScreeningInput(BaseModel):
    market_context: str = Field(default="", description="市场分析上下文")
    num_industries: int = Field(default=5, description="推荐行业数量")
    exclude_industries: list[str] = Field(default_factory=list, description="排除的行业")


class IndustryScreeningOutput(BaseModel):
    recommended_industries: list[dict[str, Any]] = Field(default_factory=list, description="推荐行业")
    ranking_rationale: str = Field(default="", description="排序理由")
    industry_trends: list[dict[str, Any]] = Field(default_factory=list, description="行业趋势")


class IndustryScreeningSkill(BaseSkill):
    """Screen and rank A-share industries for investment."""

    name = "industry_screening"
    description = "筛选和排序A股行业，评估行业景气度、估值水平和政策支持"
    input_schema = IndustryScreeningInput
    output_schema = IndustryScreeningOutput

    def __init__(self) -> None:
        cfg = get_settings().agents.industry_screening
        self.agent = SimpleAgent(
            name="industry_screening_skill",
            system_prompt=cfg.system_prompt,
            model=cfg.model,
        )

    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        """Execute industry screening."""
        parsed = IndustryScreeningInput(**inputs)

        prompt = f"""请基于以下市场分析，筛选和推荐最具投资价值的A股行业。

市场分析上下文：
{parsed.market_context}

要求：
- 推荐行业数量：Top {parsed.num_industries}
- 排除行业：{', '.join(parsed.exclude_industries) if parsed.exclude_industries else '无'}

每个推荐行业请包含：
1. 行业名称
2. 推荐理由（景气度、政策支持、估值等）
3. 风险因素
4. 代表性公司（可选）

请以结构化JSON格式返回。"""

        try:
            result = await self.agent.run_simple(prompt)
            try:
                data = json.loads(result)
            except json.JSONDecodeError:
                data = {"raw_analysis": result}

            output = IndustryScreeningOutput(**data)
            return output.model_dump()
        except Exception as e:
            logger.error(f"Industry screening failed: {e}")
            return IndustryScreeningOutput(
                ranking_rationale=f"筛选失败: {str(e)}",
            ).model_dump()
