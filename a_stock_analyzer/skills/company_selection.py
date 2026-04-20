"""Company selection skill."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.base import BaseSkill, SkillContext
from a_stock_analyzer.core.agent import SimpleAgent

logger = logging.getLogger(__name__)


class CompanySelectionInput(BaseModel):
    industries: list[dict[str, Any]] = Field(default_factory=list, description="推荐行业列表")
    num_companies: int = Field(default=10, description="选取公司数量")
    selection_criteria: list[str] = Field(default_factory=list, description="选取标准")


class CompanySelectionOutput(BaseModel):
    selected_companies: list[dict[str, Any]] = Field(default_factory=list, description="选取的公司")
    selection_rationale: str = Field(default="", description="选取理由")
    risk_assessment: list[dict[str, Any]] = Field(default_factory=list, description="风险评估")


class CompanySelectionSkill(BaseSkill):
    """Select top companies from recommended industries."""

    name = "company_selection"
    description = "从推荐行业中选取TopN值得投资的公司，基于基本面和估值分析"
    input_schema = CompanySelectionInput
    output_schema = CompanySelectionOutput

    def __init__(self) -> None:
        cfg = get_settings().agents.company_selection
        self.agent = SimpleAgent(
            name="company_selection_skill",
            system_prompt=cfg.system_prompt,
            model=cfg.model,
        )

    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        """Execute company selection."""
        parsed = CompanySelectionInput(**inputs)

        industries_text = json.dumps(parsed.industries, ensure_ascii=False, indent=2)

        prompt = f"""请从以下推荐行业中选取Top {parsed.num_companies} 家值得投资的公司。

推荐行业：
{industries_text}

选取标准：{', '.join(parsed.selection_criteria) if parsed.selection_criteria else '基本面优秀、估值合理、成长性良好'}

每家公司请包含：
1. 公司名称和代码
2. 所属行业
3. 核心推荐理由
4. 关键财务指标（ROE、PE、营收增速等，如有数据）
5. 主要风险

请以结构化JSON格式返回。"""

        try:
            result = await self.agent.run_simple(prompt)
            try:
                data = json.loads(result)
            except json.JSONDecodeError:
                data = {"raw_analysis": result}

            output = CompanySelectionOutput(**data)
            return output.model_dump()
        except Exception as e:
            logger.error(f"Company selection failed: {e}")
            return CompanySelectionOutput(
                selection_rationale=f"选取失败: {str(e)}",
            ).model_dump()
