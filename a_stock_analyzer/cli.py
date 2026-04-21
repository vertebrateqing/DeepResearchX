"""CLI entry point for A-Stock Analyzer."""

import argparse
import asyncio
import logging
import sys

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.message import AgentMessage
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


async def run_interactive(session_id: str | None = None) -> None:
    """Run interactive mode with session persistence and clarification support."""
    setup_logging()

    orchestrator = OrchestratorAgent(session_id=session_id)

    print("\n" + "=" * 60)
    print("🤖 A-Stock Analyzer - 交互模式")
    print("   输入 'exit' 或 'quit' 退出")
    print("   输入 'status' 查看会话状态")
    print("   输入 'prefs' 查看/修改用户偏好")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("👤 您: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break

        # Sanitize input to remove invalid Unicode surrogates
        user_input = "".join(ch for ch in user_input if not (0xD800 <= ord(ch) <= 0xDFFF))

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "退出"):
            print("👋 保存会话并退出...")
            await orchestrator.memory.save()
            break

        if user_input.lower() == "status":
            _print_session_status(orchestrator)
            continue

        if user_input.lower() == "prefs":
            _print_preferences(orchestrator)
            continue

        print()
        result = await orchestrator.run(user_input)
        _print_result(result)


async def run_single(query: str, session_id: str | None = None) -> None:
    """Run a single analysis query."""
    setup_logging()

    orchestrator = OrchestratorAgent(session_id=session_id)

    print(f"\n🔍 分析请求: {query}\n")
    print("=" * 60)

    result = await orchestrator.run(query)
    _print_result(result)

    print("\n" + "=" * 60)


def _print_result(result: AgentMessage) -> None:
    """Print agent result, handling clarification prompts."""
    content = result.content

    if isinstance(content, dict):
        # Check if clarification is needed
        if content.get("requires_clarification"):
            print("🤖 需要更多信息:")
            print(content.get("prompt", ""))
            return

        report = content.get("report", "")
        sections = content.get("sections", {})

        if report:
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


def _print_session_status(orchestrator: OrchestratorAgent) -> None:
    """Print current session status."""
    memory = orchestrator.memory
    print(f"\n📊 会话状态 (ID: {memory.session_id})")
    print(f"   用户: {memory.user_id}")
    print(f"   对话轮数: {len(memory.session.conversation_history)}")
    print(f"   待办任务: {len(memory.get_pending_tasks())}")
    print(f"   已完成任务: {len(memory.session.completed_tasks)}")
    print(f"   累积发现: {len(memory.session.accumulated_findings)}")
    print()


def _print_preferences(orchestrator: OrchestratorAgent) -> None:
    """Print current user preferences."""
    prefs = orchestrator.memory.get_preferences()
    print(f"\n👤 用户偏好:")
    print(f"   投资风格: {prefs.investment_style or '未设置'}")
    print(f"   风险偏好: {prefs.risk_tolerance or '未设置'}")
    print(f"   时间维度: {prefs.time_horizon or '未设置'}")
    print(f"   默认推荐数: {prefs.top_n_default}")
    print(f"   偏好行业: {', '.join(prefs.preferred_industries) or '无'}")
    print(f"   排除行业: {', '.join(prefs.excluded_industries) or '无'}")
    print()


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
        "--interactive",
        "-i",
        action="store_true",
        help="交互模式（支持多轮对话和意图澄清）",
    )
    parser.add_argument(
        "--session",
        "-s",
        type=str,
        help="指定会话ID（用于恢复历史会话）",
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

    if args.interactive:
        asyncio.run(run_interactive(session_id=args.session))
        return

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

    asyncio.run(run_single(query, session_id=args.session))


if __name__ == "__main__":
    main()
