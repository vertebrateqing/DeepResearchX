"""Unit tests for OutlinePlanner."""

import json
import pytest

from deep_research.core.outline_planner import (
    ChapterOutline,
    OutlinePlanner,
    ReportOutline,
    _fix_json_string_escapes,
)


class TestFixJsonStringEscapes:
    def test_escapes_newline_in_string(self):
        raw = '{"text": "hello\nworld"}'
        fixed = _fix_json_string_escapes(raw)
        assert fixed == '{"text": "hello\\nworld"}'

    def test_escapes_tab_in_string(self):
        raw = '{"text": "hello\tworld"}'
        fixed = _fix_json_string_escapes(raw)
        assert fixed == '{"text": "hello\\tworld"}'

    def test_leaves_escaped_chars_alone(self):
        raw = '{"text": "hello\\nworld"}'
        fixed = _fix_json_string_escapes(raw)
        assert fixed == '{"text": "hello\\nworld"}'

    def test_leaves_chars_outside_string_alone(self):
        raw = '{\n  "text": "hello"\n}'
        fixed = _fix_json_string_escapes(raw)
        # newlines outside strings should remain as-is (not inside quotes)
        assert "\n" in fixed


class TestParseOutline:
    @pytest.fixture
    def planner(self):
        return OutlinePlanner()

    def test_parse_valid_json(self, planner):
        data = {
            "title": "Test Report",
            "executive_summary_points": ["p1", "p2"],
            "chapters": [
                {
                    "chapter_id": "c1",
                    "title": "Chapter 1",
                    "objective": "Test objective",
                    "research_type": "data_collection",
                    "suggested_tools": ["tavily_search"],
                    "word_count": 800,
                    "key_questions": ["q1"],
                    "depends_on": [],
                }
            ],
        }
        outline = planner._parse_outline(json.dumps(data, ensure_ascii=False))
        assert outline is not None
        assert outline.title == "Test Report"
        assert len(outline.chapters) == 1
        assert outline.chapters[0].chapter_id == "c1"

    def test_parse_json_with_markdown_code_block(self, planner):
        data = {
            "title": "Test",
            "executive_summary_points": [],
            "chapters": [
                {
                    "chapter_id": "c1",
                    "title": "T1",
                    "objective": "O1",
                    "research_type": "data_collection",
                    "depends_on": [],
                }
            ],
        }
        wrapped = f"```json\n{json.dumps(data)}\n```"
        outline = planner._parse_outline(wrapped)
        assert outline is not None
        assert outline.title == "Test"

    def test_parse_json_with_think_block(self, planner):
        data = {
            "title": "Test",
            "executive_summary_points": [],
            "chapters": [
                {
                    "chapter_id": "c1",
                    "title": "T1",
                    "objective": "O1",
                    "research_type": "data_collection",
                    "depends_on": [],
                }
            ],
        }
        wrapped = f"<think>some reasoning</think>\n{json.dumps(data)}"
        outline = planner._parse_outline(wrapped)
        assert outline is not None
        assert outline.title == "Test"

    def test_parse_json_with_unescaped_newlines(self, planner):
        raw = '{"title": "Test", "executive_summary_points": [], "chapters": [{"chapter_id": "c1", "title": "Line 1\nLine 2", "objective": "O1", "research_type": "data_collection", "depends_on": []}]}'
        outline = planner._parse_outline(raw)
        assert outline is not None
        assert outline.chapters[0].title == "Line 1\nLine 2"

    def test_parse_removes_invalid_tools(self, planner):
        data = {
            "title": "Test",
            "executive_summary_points": [],
            "chapters": [
                {
                    "chapter_id": "c1",
                    "title": "T1",
                    "objective": "O1",
                    "research_type": "data_collection",
                    "suggested_tools": ["invalid_tool", "tavily_search"],
                    "depends_on": [],
                }
            ],
        }
        outline = planner._parse_outline(json.dumps(data))
        assert outline.chapters[0].suggested_tools == ["tavily_search"]

    def test_parse_fallback_invalid_type(self, planner):
        data = {
            "title": "Test",
            "executive_summary_points": [],
            "chapters": [
                {
                    "chapter_id": "c1",
                    "title": "T1",
                    "objective": "O1",
                    "research_type": "invalid_type",
                    "depends_on": [],
                }
            ],
        }
        outline = planner._parse_outline(json.dumps(data))
        assert outline.chapters[0].research_type == "data_collection"

    def test_parse_dedups_duplicate_chapter_ids(self, planner):
        data = {
            "title": "Test",
            "executive_summary_points": [],
            "chapters": [
                {
                    "chapter_id": "c1",
                    "title": "First",
                    "objective": "O1",
                    "research_type": "data_collection",
                    "depends_on": [],
                },
                {
                    "chapter_id": "c1",
                    "title": "Second",
                    "objective": "O2",
                    "research_type": "data_collection",
                    "depends_on": [],
                },
            ],
        }
        outline = planner._parse_outline(json.dumps(data))
        assert outline.chapters[0].chapter_id == "c1"
        assert outline.chapters[1].chapter_id == "c1_1"

    def test_parse_returns_none_for_invalid_json(self, planner):
        outline = planner._parse_outline("not json at all")
        assert outline is None

    def test_parse_returns_none_for_missing_chapters(self, planner):
        outline = planner._parse_outline('{"title": "No chapters"}')
        assert outline is None


class TestValidateAndFix:
    @pytest.fixture
    def planner(self):
        return OutlinePlanner()

    def test_valid_outline_passes(self, planner):
        outline = ReportOutline(
            title="Test",
            executive_summary_points=[],
            chapters=[
                ChapterOutline("c1", "Data", "Obj1", research_type="data_collection"),
                ChapterOutline("c2", "Analysis", "Obj2", research_type="analysis", depends_on=["c1"]),
            ],
        )
        result = planner._validate_and_fix(outline)
        assert result is not None
        assert result.chapters[1].depends_on == ["c1"]

    def test_removes_invalid_dependencies(self, planner):
        outline = ReportOutline(
            title="Test",
            executive_summary_points=[],
            chapters=[
                ChapterOutline("c1", "Data", "Obj1", research_type="data_collection"),
                ChapterOutline("c2", "Analysis", "Obj2", research_type="analysis", depends_on=["c1", "nonexistent"]),
            ],
        )
        result = planner._validate_and_fix(outline)
        assert result.chapters[1].depends_on == ["c1"]

    def test_downgrades_analysis_without_data_deps(self, planner):
        outline = ReportOutline(
            title="Test",
            executive_summary_points=[],
            chapters=[
                ChapterOutline("c1", "Data", "Obj1", research_type="data_collection"),
                ChapterOutline("c2", "Analysis", "Obj2", research_type="analysis", depends_on=["c1"]),
                ChapterOutline("c3", "Bad Analysis", "Obj3", research_type="analysis", depends_on=["c2"]),
            ],
        )
        result = planner._validate_and_fix(outline)
        assert result.chapters[2].research_type == "data_collection"
        assert result.chapters[2].depends_on == []

    def test_downgrades_conclusion_without_analysis_deps(self, planner):
        outline = ReportOutline(
            title="Test",
            executive_summary_points=[],
            chapters=[
                ChapterOutline("c1", "Data", "Obj1", research_type="data_collection"),
                ChapterOutline("c2", "Conclusion", "Obj2", research_type="conclusion", depends_on=["c1"]),
            ],
        )
        result = planner._validate_and_fix(outline)
        assert result.chapters[1].research_type == "analysis"

    def test_clamps_word_count(self, planner):
        outline = ReportOutline(
            title="Test",
            executive_summary_points=[],
            chapters=[
                ChapterOutline("c1", "Too Small", "Obj1", word_count=100),
                ChapterOutline("c2", "Too Big", "Obj2", word_count=5000),
            ],
        )
        result = planner._validate_and_fix(outline)
        assert result.chapters[0].word_count == 200
        assert result.chapters[1].word_count == 2000

    def test_detects_and_repairs_cycle(self, planner):
        outline = ReportOutline(
            title="Test",
            executive_summary_points=[],
            chapters=[
                ChapterOutline("c1", "A", "Obj1", research_type="data_collection", depends_on=["c2"]),
                ChapterOutline("c2", "B", "Obj2", research_type="data_collection", depends_on=["c1"]),
            ],
        )
        result = planner._validate_and_fix(outline)
        # Cycle should be repaired by removing backward dependencies
        assert result is not None

    def test_returns_none_for_empty_outline(self, planner):
        outline = ReportOutline(title="Test", executive_summary_points=[], chapters=[])
        result = planner._validate_and_fix(outline)
        assert result is None


class TestFallbackOutline:
    @pytest.fixture
    def planner(self):
        return OutlinePlanner()

    def test_generates_three_chapters(self, planner):
        outline = planner._fallback_outline("test query")
        assert len(outline.chapters) == 3
        assert outline.chapters[0].research_type == "data_collection"
        assert outline.chapters[1].research_type == "analysis"
        assert outline.chapters[2].research_type == "conclusion"

    def test_includes_query_in_title(self, planner):
        outline = planner._fallback_outline("market analysis")
        assert "market analysis" in outline.title


class TestBuildEnhancedPrompt:
    @pytest.fixture
    def planner(self):
        return OutlinePlanner()

    def test_includes_research_note_when_present(self, planner):
        prompt = planner._build_enhanced_prompt("test query", "research findings")
        assert "前期调研发现" in prompt
        assert "research findings" in prompt
        assert "test query" in prompt

    def test_omits_research_section_when_empty(self, planner):
        prompt = planner._build_enhanced_prompt("test query", "")
        assert "前期调研发现" not in prompt
        assert "test query" in prompt

    def test_includes_current_date(self, planner):
        from datetime import datetime
        prompt = planner._build_enhanced_prompt("test query", "")
        today = datetime.now().strftime("%Y年%m月%d日")
        assert today in prompt
