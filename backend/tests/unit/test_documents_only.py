"""Tests for documents-only research mode."""

from deep_research.core.chapter_worker import _default_tools
from deep_research.tools.web_search import WebSearchTool
from deep_research.tools.web_scraper import WebScraperTool
from deep_research.tools.document_search import DocumentSearchTool


class TestDocumentsOnlyMode:
    def test_default_tools_without_documents(self):
        """Without document_collection, tools include web search + scraper."""
        tools = _default_tools(document_collection=None, allowed_doc_ids=None, documents_only=False)
        assert any(isinstance(t, WebSearchTool) for t in tools)
        assert any(isinstance(t, WebScraperTool) for t in tools)
        assert not any(isinstance(t, DocumentSearchTool) for t in tools)

    def test_default_tools_with_documents(self):
        """With document_collection, DocumentSearchTool is prepended."""
        tools = _default_tools(
            document_collection="test_col",
            allowed_doc_ids=["d1"],
            documents_only=False,
        )
        assert any(isinstance(t, DocumentSearchTool) for t in tools)
        assert any(isinstance(t, WebSearchTool) for t in tools)
        assert any(isinstance(t, WebScraperTool) for t in tools)

    def test_documents_only_excludes_web_tools(self):
        """When documents_only=True, web tools are excluded."""
        tools = _default_tools(
            document_collection="test_col",
            allowed_doc_ids=["d1"],
            documents_only=True,
        )
        assert any(isinstance(t, DocumentSearchTool) for t in tools)
        assert not any(isinstance(t, WebSearchTool) for t in tools)
        assert not any(isinstance(t, WebScraperTool) for t in tools)

    def test_documents_only_without_collection(self):
        """documents_only without collection still excludes web tools."""
        tools = _default_tools(
            document_collection=None,
            allowed_doc_ids=None,
            documents_only=True,
        )
        assert not any(isinstance(t, DocumentSearchTool) for t in tools)
        assert not any(isinstance(t, WebSearchTool) for t in tools)
        assert not any(isinstance(t, WebScraperTool) for t in tools)
