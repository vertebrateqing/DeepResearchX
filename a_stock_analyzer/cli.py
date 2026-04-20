"""CLI entry point for A-Stock Analyzer."""

import argparse
import asyncio
import logging
import sys

from a_stock_analyzer.agents.company_agent import CompanySelectionAgent
from a_stock_analyzer.agents.financial_rag_agent import FinancialRAGAgent
from a_stock_analyzer.agents.industry_agent import IndustryScreeningAgent
from a_stock_analyzer.agents.market_agent import MarketAnalysisAgent
from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.orchestrator import OrchestratorAgent


def setup_logging() -> None:
    """Setup logging configuration."""
    cfg = get_settings().logging
    level = getattr(logging, cfg.level.upper(), logging.INFO)

    handlers = [logging.StreamHandler(sys.stdout)]
    if cfg.file:
        handlers.append(logging.FileHandler(cfg.file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


async def run_analysis(query: str) -> None:
    """Run full investment analysis."""
    setup_logging()

    # Create orchestrator
    orchestrator = OrchestratorAgent()

    # Register sub-agents
    orchestrator.register_sub_agent(MarketAnalysisAgent())
    orchestrator.register_sub_agent(IndustryScreeningAgent())
    orchestrator.register_sub_agent(CompanySelectionAgent())
    orchestrator.register_sub_agent(FinancialRAGAgent())

    print(f"\n🔍 分析请求: {query}\n")
    print("=" * 60)

    result = await orchestrator.run(query)

    print("\n" + "=" * 60)
    print("📊 分析报告\n")

    content = result.content
    if isinstance(content, dict):
        report = content.get("report", "")
        sections = content.get("sections", {})

        print(report)

        if sections:
            print("\n" + "-" * 60)
            print("📋 各模块摘要:\n")
            for name, summary in sections.items():
                if summary:
                    print(f"\n【{name}】")
                    print(summary[:500] + "..." if len(str(summary)) > 500 else summary)
    else:
        print(content)

    print("\n" + "=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A-Stock Analyzer - A股投资分析Agent系统",
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="分析请求，如：推荐值得投资的A股行业和公司",
    )
    parser.add_argument(
        "--market",
        action="store_true",
        help="仅进行市场分析",
    )
    parser.add_argument(
        "--industry",
        action="store_true",
        help="仅进行行业推荐",
    )
    parser.add_argument(
        "--company",
        type=str,
        help="分析指定公司，如：600519",
    )

    args = parser.parse_args()

    if args.market:
        query = "请分析当前A股市场情况"
    elif args.industry:
        query = "请推荐当前最具投资价值的A股行业"
    elif args.company:
        query = f"请分析公司 {args.company} 的投资价值"
    elif args.query:
        query = args.query
    else:
        parser.print_help()
        return

    asyncio.run(run_analysis(query))


if __name__ == "__main__":
    main()
