"""AKShare data tools for A-share market data."""

import asyncio
import json
import logging
from typing import Any

from a_stock_analyzer.core.base import BaseTool

logger = logging.getLogger(__name__)


class AKShareTool(BaseTool):
    """Tool for fetching A-share data via AKShare."""

    name = "akshare_data"
    description = "获取A股市场数据，包括行情、行业、公司基本面、财务数据等。"
    parameters = {
        "data_type": {
            "type": "string",
            "description": "数据类型: stock_spot, industry_board, stock_financial, stock_news, market_sentiment",
        },
        "symbol": {
            "type": "string",
            "description": "股票代码（可选）",
            "default": "",
        },
        "industry": {
            "type": "string",
            "description": "行业名称（可选）",
            "default": "",
        },
        "limit": {
            "type": "integer",
            "description": "返回数据条数",
            "default": 20,
        },
    }

    def __init__(self) -> None:
        self._ak = None

    @property
    def ak(self) -> Any:
        if self._ak is None:
            try:
                import akshare as ak

                self._ak = ak
            except ImportError:
                raise ImportError("akshare is required for A-share data")
        return self._ak

    async def execute(
        self,
        data_type: str,
        symbol: str = "",
        industry: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Execute AKShare data fetch."""
        try:
            if data_type == "stock_spot":
                return await self._get_stock_spot(symbol, limit)
            elif data_type == "industry_board":
                return await self._get_industry_board(limit)
            elif data_type == "stock_financial":
                return await self._get_stock_financial(symbol)
            elif data_type == "stock_news":
                return await self._get_stock_news(symbol, limit)
            elif data_type == "market_sentiment":
                return await self._get_market_sentiment()
            elif data_type == "stock_list":
                return await self._get_stock_list()
            elif data_type == "industry_stocks":
                return await self._get_industry_stocks(industry, limit)
            else:
                return {"error": f"Unknown data_type: {data_type}"}
        except Exception as e:
            logger.error(f"AKShare fetch failed: {e}")
            return {"error": str(e), "data_type": data_type}

    async def _get_stock_spot(self, symbol: str, limit: int) -> dict[str, Any]:
        """Get real-time stock quotes."""
        df = await asyncio.to_thread(self.ak.stock_zh_a_spot_em)
        if symbol:
            df = df[df["代码"] == symbol]
        df = df.head(limit)
        return {
            "data_type": "stock_spot",
            "count": len(df),
            "data": json.loads(df.to_json(orient="records", force_ascii=False)),
        }

    async def _get_industry_board(self, limit: int) -> dict[str, Any]:
        """Get industry board data."""
        df = await asyncio.to_thread(self.ak.stock_board_industry_name_em)
        df = df.head(limit)
        return {
            "data_type": "industry_board",
            "count": len(df),
            "data": json.loads(df.to_json(orient="records", force_ascii=False)),
        }

    async def _get_stock_financial(self, symbol: str) -> dict[str, Any]:
        """Get stock financial indicators."""
        if not symbol:
            return {"error": "symbol is required for stock_financial"}

        # Try to get financial summary
        try:
            df = await asyncio.to_thread(self.ak.stock_financial_report_sina, stock=symbol)
            return {
                "data_type": "stock_financial",
                "symbol": symbol,
                "data": json.loads(df.to_json(orient="records", force_ascii=False)),
            }
        except Exception:
            # Fallback to basic financial data
            df = await asyncio.to_thread(self.ak.stock_financial_analysis_indicator, symbol=symbol)
            return {
                "data_type": "stock_financial",
                "symbol": symbol,
                "data": json.loads(df.to_json(orient="records", force_ascii=False)),
            }

    async def _get_stock_news(self, symbol: str, limit: int) -> dict[str, Any]:
        """Get stock news."""
        if not symbol:
            return {"error": "symbol is required for stock_news"}

        df = await asyncio.to_thread(self.ak.stock_news_em, symbol=symbol)
        df = df.head(limit)
        return {
            "data_type": "stock_news",
            "symbol": symbol,
            "count": len(df),
            "data": json.loads(df.to_json(orient="records", force_ascii=False)),
        }

    async def _get_market_sentiment(self) -> dict[str, Any]:
        """Get market sentiment indicators."""
        # Get market overview
        df = await asyncio.to_thread(self.ak.stock_zh_index_spot)
        return {
            "data_type": "market_sentiment",
            "indices": json.loads(df.to_json(orient="records", force_ascii=False)),
        }

    async def _get_stock_list(self) -> dict[str, Any]:
        """Get A-share stock list."""
        df = await asyncio.to_thread(self.ak.stock_zh_a_spot_em)
        return {
            "data_type": "stock_list",
            "count": len(df),
            "data": json.loads(df[["代码", "名称", "所属行业"]].to_json(orient="records", force_ascii=False)),
        }

    async def _get_industry_stocks(self, industry: str, limit: int) -> dict[str, Any]:
        """Get stocks in an industry."""
        if not industry:
            return {"error": "industry is required for industry_stocks"}

        try:
            df = await asyncio.to_thread(self.ak.stock_board_industry_cons_em, symbol=industry)
            df = df.head(limit)
            return {
                "data_type": "industry_stocks",
                "industry": industry,
                "count": len(df),
                "data": json.loads(df.to_json(orient="records", force_ascii=False)),
            }
        except Exception as e:
            return {"error": str(e), "industry": industry}
