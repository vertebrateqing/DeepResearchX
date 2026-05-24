#!/usr/bin/env python3
"""Preview document chunking results — standalone diagnostic tool.

Zero coupling to production upload flow. Runs locally, outputs Markdown.

Usage:
    uv run python scripts/preview_chunks.py -f ~/report.pdf --strategy recursive
    uv run python scripts/preview_chunks.py -f ~/report.pdf --strategy semantic --chunk-size 800
    uv run python scripts/preview_chunks.py -f ~/report.pdf --compare  # compare all strategies
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from deep_research.rag.chunking import get_splitter
from deep_research.rag.document_loader import load_document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_num(n: int) -> str:
    return f"{n:,}"


def _preview(text: str, length: int = 300) -> str:
    """Return a safe preview string for terminal display."""
    if len(text) <= length:
        return text
    return text[:length] + "..."


def _border(text: str, width: int = 70, char: str = "-") -> str:
    return char * width + f"  {text}  " + char * width


def _build_stats(chunks: list[str]) -> dict[str, Any]:
    sizes = [len(c) for c in chunks]
    return {
        "count": len(chunks),
        "total_chars": sum(sizes),
        "avg_size": round(sum(sizes) / len(sizes), 1) if sizes else 0,
        "min_size": min(sizes) if sizes else 0,
        "max_size": max(sizes) if sizes else 0,
        "median_size": sorted(sizes)[len(sizes) // 2] if sizes else 0,
    }


def _render_chunk(i: int, chunk: str, preview_len: int) -> str:
    """Render a single chunk as Markdown."""
    lines: list[str] = [
        f"### Chunk {i}",
        "",
        f"- **Chars**: {_fmt_num(len(chunk))}",
        f"- **Lines**: {_fmt_num(chunk.count(chr(10)) + 1)}",
        "",
        "**Preview:**",
        "",
        "```",
        _preview(chunk, preview_len),
        "```",
        "",
        f"**Tail (last 100 chars):**",
        "",
        "```",
        _preview(chunk[-100:], 100) if len(chunk) > 100 else chunk,
        "```",
        "",
    ]
    return "\n".join(lines)


def _render_strategy(
    strategy: str,
    chunks: list[str],
    preview_len: int,
    elapsed_ms: float,
) -> str:
    """Render full report for one strategy."""
    stats = _build_stats(chunks)
    lines: list[str] = [
        _border(f" STRATEGY: {strategy.upper()} ", char="="),
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Chunk count | {_fmt_num(stats['count'])} |",
        f"| Total chars | {_fmt_num(stats['total_chars'])} |",
        f"| Avg chunk size | {_fmt_num(int(stats['avg_size']))} |",
        f"| Median size | {_fmt_num(stats['median_size'])} |",
        f"| Min size | {_fmt_num(stats['min_size'])} |",
        f"| Max size | {_fmt_num(stats['max_size'])} |",
        f"| Split time | {elapsed_ms:.1f} ms |",
        "",
        "## Chunks",
        "",
    ]

    for i, chunk in enumerate(chunks):
        lines.append(_render_chunk(i, chunk, preview_len))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview how a document is split into chunks. Standalone tool — does not touch ChromaDB."
    )
    parser.add_argument("-f", "--file", required=True, type=Path, help="Path to PDF / Word / text file")
    parser.add_argument(
        "--strategy",
        default="recursive",
        choices=["recursive", "fixed", "semantic"],
        help="Chunking strategy (default: recursive)",
    )
    parser.add_argument("--chunk-size", type=int, default=None, help="Target chunk size (chars)")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="Overlap between chunks (chars)")
    parser.add_argument("--preview-length", type=int, default=300, help="Max chars to show per chunk preview")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write Markdown to file instead of stdout")
    parser.add_argument("--compare", action="store_true", help="Run all 3 strategies and output comparison")
    parser.add_argument("--max-chunks", type=int, default=None, help="Limit output to first N chunks")
    args = parser.parse_args()

    file_path: Path = args.file
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}", file=sys.stderr)
        return 1

    # 1. Load document
    print(f"Loading: {file_path.name} ...", file=sys.stderr)
    doc = load_document(file_path)
    print(f"Loaded: {_fmt_num(len(doc.content))} chars", file=sys.stderr)
    print(f"Source: {doc.source}", file=sys.stderr)
    print("", file=sys.stderr)

    strategies = ["recursive", "fixed", "semantic"] if args.compare else [args.strategy]
    reports: list[str] = []

    for strategy in strategies:
        import time

        t0 = time.perf_counter()
        splitter = get_splitter(
            strategy=strategy,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
        chunks = splitter.split_text(doc.content)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if args.max_chunks:
            chunks = chunks[: args.max_chunks]

        reports.append(_render_strategy(strategy, chunks, args.preview_length, elapsed_ms))

    # 2. Assemble final output
    lines: list[str] = [
        "# Document Chunking Preview",
        "",
        f"**File:** `{file_path.name}`  ",
        f"**Size:** {_fmt_num(len(doc.content))} chars  ",
        f"**Strategies tested:** {', '.join(strategies)}",
        "",
        "---",
        "",
    ]
    lines.extend(reports)

    output = "\n".join(lines)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Report written to: {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
