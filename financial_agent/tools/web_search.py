"""Web search tools for gathering market information."""

import logging
from typing import Any, Optional

from financial_agent.config.settings import get_settings
from financial_agent.core.base import BaseTool

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Tool for web search using Tavily or DuckDuckGo."""

    name = "web_search"
    description = "搜索互联网获取最新的市场信息、行业动态、公司新闻等。适用于获取实时数据和最新资讯。"
    parameters = {
        "query": {
            "type": "string",
            "description": "搜索关键词",
        },
        "max_results": {
            "type": "integer",
            "description": "返回结果数量",
            "default": 10,
        },
        "search_depth": {
            "type": "string",
            "description": "搜索深度: basic 或 advanced",
            "default": "advanced",
        },
    }

    def __init__(self) -> None:
        self.settings = get_settings().data_sources.web_search
        self._tavily_client: Optional[Any] = None

    def _get_tavily_client(self) -> Any:
        if self._tavily_client is None:
            try:
                from tavily import TavilyClient

                self._tavily_client = TavilyClient(api_key=self.settings.api_key)
            except ImportError:
                raise ImportError("tavily-python is required for Tavily search")
        return self._tavily_client

    async def execute(
        self,
        query: str,
        max_results: int = 10,
        search_depth: str = "advanced",
    ) -> dict[str, Any]:
        """Execute web search."""
        if self.settings.provider == "tavily":
            return await self._search_tavily(query, max_results, search_depth)
        else:
            return await self._search_duckduckgo(query, max_results)

    async def _search_tavily(
        self,
        query: str,
        max_results: int,
        search_depth: str,
    ) -> dict[str, Any]:
        """Search using Tavily API (wrapped in thread for async compatibility)."""
        try:
            import asyncio
            client = self._get_tavily_client()
            response = await asyncio.to_thread(
                client.search,
                query=query,
                max_results=min(max_results, self.settings.max_results),
                search_depth=search_depth,
                include_answer=True,
            )

            results = []
            for result in response.get("results", []):
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "content": result.get("content", ""),
                    "score": result.get("score", 0),
                })

            logger.debug(f"[WebSearch] Tavily raw response: {json.dumps(response, ensure_ascii=False)}")
            return {
                "query": query,
                "provider": "tavily",
                "answer": response.get("answer", ""),
                "results": results,
                "total_results": len(results),
            }
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            # Fallback to DuckDuckGo
            return await self._search_duckduckgo(query, max_results)

    async def _search_duckduckgo(self, query: str, max_results: int) -> dict[str, Any]:
        """Search using DuckDuckGo."""
        try:
            import asyncio
            from duckduckgo_search import DDGS

            def _do_search():
                with DDGS() as ddgs:
                    results = []
                    for result in ddgs.text(query, max_results=min(max_results, 10)):
                        results.append({
                            "title": result.get("title", ""),
                            "url": result.get("href", ""),
                            "content": result.get("body", ""),
                        })
                    return results

            results = await asyncio.to_thread(_do_search)
            return {
                "query": query,
                "provider": "duckduckgo",
                "results": results,
                "total_results": len(results),
            }
        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")
            return {
                "query": query,
                "provider": "duckduckgo",
                "results": [],
                "total_results": 0,
                "error": str(e),
            }
