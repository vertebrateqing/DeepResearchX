"""Unit tests for ChapterWorker tool/prompt consistency."""

from pathlib import Path

import pytest

from deep_research.core.chapter_worker import (
    ChapterWorker,
    _build_react_system_prompt,
    _default_tools,
)
from deep_research.core.outline_planner import ChapterOutline
from deep_research.tools.document_search import DocumentSearchTool
from deep_research.tools.web_search import WebSearchTool
from deep_research.tools.web_scraper import WebScraperTool


def _make_outline(chapter_id: str = "c1") -> ChapterOutline:
    return ChapterOutline(
        chapter_id=chapter_id,
        title="测试章节",
        objective="测试目标",
        word_count=500,
        key_questions=["问题1"],
    )


class TestDefaultTools:
    def test_no_document_collection_excludes_document_search(self):
        tools = _default_tools(document_collection=None)
        names = {t.name for t in tools}
        assert "document_search" not in names
        assert "tavily_search" in names
        assert "web_scraper" in names

    def test_with_document_collection_includes_document_search(self):
        tools = _default_tools(document_collection="test_col")
        names = {t.name for t in tools}
        assert "document_search" in names
        assert "tavily_search" in names
        assert "web_scraper" in names

    def test_documents_only_excludes_web_tools(self):
        tools = _default_tools(document_collection="test_col", documents_only=True)
        names = {t.name for t in tools}
        assert "document_search" in names
        assert "tavily_search" not in names
        assert "web_scraper" not in names


class TestBuildReactSystemPrompt:
    def test_no_document_search_omits_tool_hint(self):
        tools = [WebSearchTool(), WebScraperTool()]
        prompt = _build_react_system_prompt(tools)
        assert "document_search" not in prompt
        assert "tavily_search" in prompt
        assert "web_scraper" in prompt

    def test_with_document_search_includes_tool_hint(self):
        tools = [DocumentSearchTool("col"), WebSearchTool(), WebScraperTool()]
        prompt = _build_react_system_prompt(tools)
        assert "document_search" in prompt
        assert "优先调用 document_search" in prompt

    def test_empty_tools_no_tool_section(self):
        prompt = _build_react_system_prompt([])
        assert "【可用工具】" not in prompt
        assert "写作要求" in prompt


class TestChapterWorkerToolSync:
    def test_worker_without_docs_no_document_search(self, tmp_path):
        worker = ChapterWorker(
            chapter_outline=_make_outline(),
            session_dir=tmp_path,
            document_collection=None,
        )
        names = {t.name for t in worker.tools}
        assert "document_search" not in names

    def test_worker_with_docs_has_document_search(self, tmp_path):
        worker = ChapterWorker(
            chapter_outline=_make_outline(),
            session_dir=tmp_path,
            document_collection="test_collection",
        )
        names = {t.name for t in worker.tools}
        assert "document_search" in names
