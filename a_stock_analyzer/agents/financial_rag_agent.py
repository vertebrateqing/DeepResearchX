"""Financial RAG sub-agent for deep report analysis."""

import asyncio
import logging
from typing import Any, Optional

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.agent import ReActAgent
from a_stock_analyzer.core.base import AgentContext, BaseSkill
from a_stock_analyzer.core.message import AgentMessage
from a_stock_analyzer.rag.pipeline import RAGPipeline
from a_stock_analyzer.rag.query_rewriter import QueryRewriter
from a_stock_analyzer.tools.akshare_data import AKShareTool
from a_stock_analyzer.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)


def _merge_web_results(results_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge web search results from multiple query variants.

    Deduplicates by URL, keeps all unique results.
    """
    seen_urls: set[str] = set()
    merged_results: list[dict[str, Any]] = []

    for result in results_list:
        items = result.get("results", [])
        for item in items:
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged_results.append(item)
            elif not url:
                # Keep results without URL (e.g. DuckDuckGo snippets)
                merged_results.append(item)

    return {
        "query": result.get("query", ""),
        "results": merged_results,
        "total_results": len(merged_results),
    }


class FinancialRAGAgent(ReActAgent):
    """Sub-agent for financial report RAG analysis.

    Provides deep financial analysis using RAG on company reports.
    """

    def __init__(
        self,
        name: str = "financial_rag",
        tools: Optional[list] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
    ):
        cfg = get_settings().agents.financial_rag
        super().__init__(
            name=name,
            system_prompt=cfg.system_prompt,
            tools=tools or [AKShareTool(), WebSearchTool()],
            skills=skills,
            model=model or cfg.model,
        )
        self.rag_pipeline = RAGPipeline()
        self.query_rewriter = QueryRewriter()

    async def run(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run financial RAG analysis."""
        logger.info(f"FinancialRAGAgent analyzing: {user_input[:100]}...")

        # Try RAG first if reports are indexed
        rag_result = None
        try:
            doc_count = self.rag_pipeline.retriever.count().get("vector_store", 0)
            logger.info(f"[FinancialRAG] vector_store doc count={doc_count}")
            if doc_count > 0:
                rag_result = await self.rag_pipeline.query_and_answer(
                    query=user_input,
                    top_k=5,
                )
                logger.info(f"[FinancialRAG] RAG answer length={len(rag_result.get('answer', ''))}, sources={rag_result.get('sources', [])}")
        except Exception as e:
            logger.warning(f"[FinancialRAG] RAG query failed: {e}")

        # Combine RAG results with market data
        data_parts = []

        if rag_result and rag_result.get("answer"):
            data_parts.append(f"财报RAG分析结果:\n{rag_result['answer']}")

        # Get financial data from AKShare
        akshare = AKShareTool()
        try:
            # Try to extract stock symbol from input
            import re
            symbol_match = re.search(r'(\d{6})', user_input)
            if symbol_match:
                symbol = symbol_match.group(1)
                logger.info(f"[FinancialRAG] Fetching AKShare data for symbol={symbol}")
                financial_data = await akshare.execute(
                    data_type="stock_financial",
                    symbol=symbol,
                )
                data_len = len(str(financial_data))
                logger.info(f"[FinancialRAG] AKShare data fetched, length={data_len}")
                data_parts.append(f"财务数据:\n{str(financial_data)[:1500]}")
        except Exception as e:
            logger.warning(f"[FinancialRAG] Failed to get financial data: {e}")

        # Parallel web search with query rewriting
        web_results_merged = None
        try:
            search_variants = await self.query_rewriter.rewrite(user_input, n_variants=3)
            logger.info(f"[FinancialRAG] Web search variants: {len(search_variants)}")

            web_search_tool = WebSearchTool()
            search_tasks = [
                web_search_tool.execute(query=variant, max_results=5)
                for variant in search_variants
            ]
            search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
            # Filter out exceptions
            valid_results = [r for r in search_results if not isinstance(r, Exception)]
            if valid_results:
                web_results_merged = _merge_web_results(valid_results)
                logger.info(
                    f"[FinancialRAG] Web search merged: {web_results_merged['total_results']} unique results"
                )
                # Build summary text from merged results
                web_summary_parts = []
                for i, item in enumerate(web_results_merged["results"][:10], 1):
                    title = item.get("title", "")
                    snippet = item.get("content", item.get("snippet", ""))
                    web_summary_parts.append(f"{i}. {title}\n{snippet}")
                if web_summary_parts:
                    data_parts.append(
                        f"网络搜索结果:\n" + "\n\n".join(web_summary_parts)
                    )
        except Exception as e:
            logger.warning(f"[FinancialRAG] Web search failed: {e}")

        combined_input = f"""{user_input}

{"\n\n".join(data_parts)}

请基于以上信息，提供详细的财务分析。分析维度包括：
1. 盈利能力分析
2. 偿债能力分析
3. 运营效率分析
4. 成长性分析
5. 现金流质量
6. 综合评价与投资建议"""

        result = await super().run(combined_input, context)

        if isinstance(result.content, dict):
            result.content["summary"] = self._format_summary(
                result.content.get("answer", ""),
                rag_result,
            )

        return result

    def _format_summary(self, analysis: str, rag_result: Optional[dict] = None) -> str:
        """Format analysis into structured summary."""
        sources = ""
        if rag_result and rag_result.get("sources"):
            sources = f"\n\n**参考来源**: {', '.join(rag_result['sources'])}"

        return f"""## 财报深度分析摘要

{analysis[:3000]}

{sources}

---
*数据来源: 财报RAG + AKShare财务数据*
"""
