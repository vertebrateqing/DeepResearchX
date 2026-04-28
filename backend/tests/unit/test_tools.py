"""Unit tests for tools."""

import pytest

from deep_research.core.registry import reset_registry


class TestAKShareTool:
    def setup_method(self):
        reset_registry()

    @pytest.mark.asyncio
    async def test_tool_schema(self):
        from deep_research.tools.akshare_data import AKShareTool

        tool = AKShareTool()
        schema = tool.get_schema()
        assert schema["function"]["name"] == "data_fetch"
        assert "data_type" in schema["function"]["parameters"]["properties"]


class TestWebSearchTool:
    def setup_method(self):
        reset_registry()

    def test_tool_schema(self):
        from deep_research.tools.web_search import WebSearchTool

        tool = WebSearchTool()
        schema = tool.get_schema()
        assert schema["function"]["name"] == "tavily_search"
        assert "query" in schema["function"]["parameters"]["properties"]


class TestEmbeddingTool:
    def setup_method(self):
        reset_registry()

    def test_tool_schema(self):
        from deep_research.tools.embedding_call import EmbeddingTool

        tool = EmbeddingTool()
        schema = tool.get_schema()
        assert schema["function"]["name"] == "embedding"
        assert "texts" in schema["function"]["parameters"]["properties"]
