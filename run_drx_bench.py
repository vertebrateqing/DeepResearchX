"""
Runner script: call DeepResearchX backend for each benchmark query and
produce a JSONL file compatible with deep_research_bench evaluation.

Usage:
    # Ensure backend is running on localhost:8000
    python run_drx_bench.py [--limit N] [--concurrency N] [--output path]

Output format (one JSON per line):
    {"id": 1, "prompt": "query text", "article": "full report markdown"}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.parse
from pathlib import Path

import httpx

BACKEND_URL = os.getenv("DRX_BACKEND_URL", "http://localhost:8000")
DEFAULT_OUTPUT = Path(__file__).parent / "deep_research_bench/data/test_data/raw_data/DeepResearchX.jsonl"
DEFAULT_QUERY = Path(__file__).parent / "deep_research_bench/data/prompt_data/query.jsonl"
TIMEOUT_PER_QUERY = 600  # seconds


async def run_single(client: httpx.AsyncClient, item: dict) -> dict:
    """Call the SSE stream endpoint for one query and collect the full article."""
    query = item["prompt"]
    url = f"{BACKEND_URL}/api/analyze/stream?query={urllib.parse.quote(query)}&skip_clarification=true"

    article_parts: list[str] = []
    error_msg = ""

    try:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            current_event = ""
            async for raw_line in resp.aiter_lines():
                raw_line = raw_line.strip()
                if not raw_line:
                    current_event = ""
                    continue

                # Standard SSE: "event: <type>" line followed by "data: <json>" line
                if raw_line.startswith("event:"):
                    current_event = raw_line[6:].strip()
                elif raw_line.startswith("data:"):
                    json_str = raw_line[5:].strip()
                    try:
                        data = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue

                    if current_event == "content":
                        article_parts.append(data.get("text", "") or data.get("content", ""))
                    elif current_event == "complete":
                        break
                    elif current_event == "error":
                        error_msg = data.get("message", "unknown error")
                        break

    except Exception as e:
        error_msg = str(e)

    article = "".join(article_parts).strip()

    if error_msg and not article:
        print(f"  [ERROR] id={item['id']}: {error_msg}", flush=True)
        article = f"[ERROR: {error_msg}]"
    elif not article:
        print(f"  [WARN] id={item['id']}: empty article", flush=True)
        article = "[ERROR: empty response]"
    else:
        print(f"  [OK] id={item['id']} ({len(article)} chars)", flush=True)

    return {"id": item["id"], "prompt": query, "article": article}


async def run_batch(
    queries: list[dict],
    output_path: Path,
    concurrency: int,
) -> None:
    """Run all queries with bounded concurrency, writing results incrementally."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load already-completed ids to support resuming
    done_ids: set = set()
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    done_ids.add(json.loads(line)["id"])
                except Exception:
                    pass
        print(f"Resuming: {len(done_ids)} already done, skipping.", flush=True)

    pending = [q for q in queries if q["id"] not in done_ids]
    print(f"Running {len(pending)} queries (concurrency={concurrency})...", flush=True)

    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(item: dict) -> dict:
        async with semaphore:
            return await run_single(client, item)

    # Use long read timeout: SSE events can be minutes apart during chapter generation
    timeout = httpx.Timeout(connect=30, read=TIMEOUT_PER_QUERY, write=30, pool=30)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        tasks = [bounded(item) for item in pending]
        with open(output_path, "a", encoding="utf-8") as out_f:
            for coro in asyncio.as_completed(tasks):
                result = await coro
                out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                out_f.flush()

    print(f"\nDone. Output: {output_path}", flush=True)


def main() -> None:
    global BACKEND_URL
    parser = argparse.ArgumentParser(description="Run DeepResearchX on benchmark queries")
    parser.add_argument("--query", default=str(DEFAULT_QUERY), help="Path to query.jsonl")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSONL path")
    parser.add_argument("--limit", type=int, default=None, help="Only run first N queries (for testing)")
    parser.add_argument("--concurrency", type=int, default=2, help="Max parallel queries")
    parser.add_argument("--backend", default=BACKEND_URL, help="Backend base URL")
    args = parser.parse_args()

    BACKEND_URL = args.backend

    query_path = Path(args.query)
    if not query_path.exists():
        print(f"ERROR: query file not found: {query_path}")
        print("Make sure deep_research_bench is cloned and query.jsonl exists.")
        sys.exit(1)

    queries: list[dict] = []
    with open(query_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))

    if args.limit:
        queries = queries[: args.limit]

    print(f"Loaded {len(queries)} queries from {query_path}")
    asyncio.run(run_batch(queries, Path(args.output), args.concurrency))


if __name__ == "__main__":
    main()
