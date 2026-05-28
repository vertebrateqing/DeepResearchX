from __future__ import annotations
"""Web search tools for gathering market information."""

import json
import logging
import time
from typing import Any, Optional

from deep_research.config.settings import get_settings
from deep_research.core.base import BaseTool
from deep_research.observability import get_langfuse

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Tool for web search using Tavily or DuckDuckGo.

    When scraping is enabled, also fetches full page content from
    result URLs and returns the most relevant text chunks.
    """

    name = "tavily_search"
    description = "搜索互联网获取最新的市场信息、行业动态、公司新闻等。适用于获取实时数据和最新资讯。支持抓取搜索结果网页全文并按相关性过滤。"
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
        "scrape": {
            "type": "boolean",
            "description": "是否抓取搜索结果网页全文",
            "default": True,
        },
    }

    def __init__(self) -> None:
        self.settings = get_settings().data_sources.web_search
        self.scraper_settings = get_settings().data_sources.web_scraper
        self._tavily_client: Optional[Any] = None
        self._scraper: Optional[Any] = None
        self._trace_id: Optional[str] = None

    def _get_tavily_client(self) -> Any:
        if self._tavily_client is None:
            try:
                from tavily import TavilyClient

                self._tavily_client = TavilyClient(api_key=self.settings.api_key)
            except ImportError:
                raise ImportError("tavily-python is required for Tavily search")
        return self._tavily_client

    def _get_scraper(self) -> Any:
        if self._scraper is None:
            from deep_research.tools.web_scraper import WebScraperTool

            self._scraper = WebScraperTool()
        return self._scraper

    async def execute(
        self,
        query: str,
        max_results: int = 10,
        search_depth: str = "advanced",
        scrape: bool = True,
    ) -> dict[str, Any]:
        """Execute web search, optionally scraping result URLs."""
        lf = get_langfuse()
        span = lf.span(
            trace_id=self._trace_id,
            name="web_search",
            input={"query": query, "max_results": max_results, "provider": self.settings.provider},
        ) if lf and self._trace_id else None

        t0 = time.perf_counter()

        if self.settings.provider == "tavily":
            result = await self._search_tavily(query, max_results, search_depth)
        else:
            result = await self._search_duckduckgo(query, max_results)

        # Build chunks from search results
        should_scrape = scrape and self.scraper_settings.enabled
        if should_scrape and result.get("results"):
            # For Tavily, try to use raw_content directly to avoid extra HTTP requests
            if self.settings.provider == "tavily":
                chunks = self._extract_chunks_from_tavily(result["results"], query)
                if chunks:
                    result["scraped_chunks"] = chunks
                    result["scraped_total_chunks"] = len(chunks)
                    logger.info(
                        f"[WebSearch] Extracted {len(chunks)} chunks from Tavily raw_content"
                    )
                    if span:
                        span.end(output={
                            "urls": [r["url"] for r in result.get("results", [])],
                            "top_chunks": [{"url": c["url"], "title": c.get("title", ""), "text": c["text"][:500]} for c in chunks],
                        }, metadata={"latency_s": round(time.perf_counter() - t0, 3), "source": "tavily_raw"})
                    return result

            # Fall back to manual scraping for DuckDuckGo or when Tavily raw_content is empty
            urls = [r["url"] for r in result["results"] if r.get("url")]
            if urls:
                try:
                    scraper = self._get_scraper()
                    scraped = await scraper.execute(
                        urls=urls[: self.scraper_settings.max_pages],
                        query=query,
                        top_k=self.scraper_settings.max_pages,
                        chunk_size=self.scraper_settings.chunk_size,
                        chunk_overlap=self.scraper_settings.chunk_overlap,
                    )
                    result["scraped_chunks"] = scraped.get("chunks", [])
                    result["scraped_total_chunks"] = scraped.get("total_chunks", 0)
                    logger.info(
                        f"[WebSearch] Scraped {scraped.get('total_chunks', 0)} chunks "
                        f"from {len(scraped.get('pages', []))} pages, "
                        f"returned {len(scraped.get('chunks', []))} top-k"
                    )
                except Exception as e:  # noqa: BLE001
                    # Web scraper may raise various exceptions (httpx errors,
                    # parsing errors, timeout); catch broadly to prevent one
                    # failing URL from aborting the entire search.
                    logger.warning(f"[WebSearch] URL scraping failed: {e}")
                    result["scraped_chunks"] = []
                    result["scraped_total_chunks"] = 0

        if span:
            chunks = result.get("scraped_chunks", [])
            span.end(output={
                "urls": [r["url"] for r in result.get("results", [])],
                "top_chunks": [{"url": c["url"], "title": c.get("title", ""), "text": c["text"][:500]} for c in chunks],
            }, metadata={"latency_s": round(time.perf_counter() - t0, 3), "source": "scraped"})

        return result

    def _extract_chunks_from_tavily(
        self, results: list[dict[str, Any]], query: str
    ) -> list[dict[str, Any]]:
        """Extract text chunks from Tavily's raw_content to avoid extra HTTP fetches."""
        from deep_research.tools.web_scraper import split_text

        chunks: list[dict[str, Any]] = []
        chunk_size = getattr(self.scraper_settings, "chunk_size", 2048)
        chunk_overlap = getattr(self.scraper_settings, "chunk_overlap", 128)
        max_text_length = getattr(self.scraper_settings, "max_text_length", 30000)
        top_k = getattr(self.scraper_settings, "max_pages", 5)

        for result in results:
            raw = result.get("raw_content", "")
            if not raw:
                continue

            # Truncate if too long
            if len(raw) > max_text_length:
                raw = raw[:max_text_length]

            text_chunks = split_text(
                raw,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            for i, text in enumerate(text_chunks):
                chunks.append({
                    "text": text,
                    "url": result.get("url", ""),
                    "title": result.get("title", ""),
                    "chunk_index": i,
                })

        # Limit to top_k chunks per result
        if len(chunks) > top_k:
            chunks = chunks[:top_k]

        return chunks

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
            t0 = time.perf_counter()
            response = await asyncio.to_thread(
                client.search,
                query=query,
                max_results=min(max_results, self.settings.max_results),
                search_depth=search_depth,
                include_answer=True,
                include_raw_content=True,
            )
            latency = time.perf_counter() - t0

            results = []
            for result in response.get("results", []):
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "content": result.get("content", ""),
                    "score": result.get("score", 0),
                })

            logger.info(f"[WebSearch] Tavily search latency={latency:.2f}s, results={len(results)}, query={query[:50]}...")
            logger.debug(f"[WebSearch] Tavily raw response: {json.dumps(response, ensure_ascii=False)}")
            return {
                "query": query,
                "provider": "tavily",
                "answer": response.get("answer", ""),
                "results": results,
                "total_results": len(results),
            }
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
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

            t0 = time.perf_counter()
            results = await asyncio.to_thread(_do_search)
            latency = time.perf_counter() - t0
            logger.info(f"[WebSearch] DuckDuckGo search latency={latency:.2f}s, results={len(results)}, query={query[:50]}...")
            return {
                "query": query,
                "provider": "duckduckgo",
                "results": results,
                "total_results": len(results),
            }
        except (ImportError, Exception) as e:  # noqa: BLE001
            # DDGS may raise various exceptions (network, rate limit, etc.)
            logger.error(f"DuckDuckGo search failed: {e}")
            return {
                "query": query,
                "provider": "duckduckgo",
                "results": [],
                "total_results": 0,
                "error": str(e),
            }
