"""Unit tests for skills.

NOTE: The skills package (deep_research.skills) is currently orphaned
and not used by the V4 orchestrator. All tests are skipped until
skills are re-integrated.
"""

import pytest

pytestmark = pytest.mark.skip(reason="skills package is orphaned — not used by V4 orchestrator")


class TestMarketAnalysisSkill:
    @pytest.mark.asyncio
    async def test_skill_init(self):
        from deep_research.skills.market_analysis import MarketAnalysisSkill

        skill = MarketAnalysisSkill()
        assert skill.name == "market_analysis"

    def test_input_schema(self):
        from deep_research.skills.market_analysis import MarketAnalysisInput

        inp = MarketAnalysisInput(focus_areas=["科技", "消费"], time_horizon="中期")
        assert inp.focus_areas == ["科技", "消费"]
        assert inp.time_horizon == "中期"


class TestIndustryScreeningSkill:
    @pytest.mark.asyncio
    async def test_skill_init(self):
        from deep_research.skills.industry_screening import IndustryScreeningSkill

        skill = IndustryScreeningSkill()
        assert skill.name == "industry_screening"


class TestCompanySelectionSkill:
    @pytest.mark.asyncio
    async def test_skill_init(self):
        from deep_research.skills.company_selection import CompanySelectionSkill

        skill = CompanySelectionSkill()
        assert skill.name == "company_selection"


class TestRAGQASkill:
    @pytest.mark.asyncio
    async def test_skill_init(self):
        from deep_research.skills.rag_qa import RAGQASkill

        skill = RAGQASkill()
        assert skill.name == "rag_qa"
