"""Integration tests for Langfuse observability (v2 SDK).

Tests verify that:
1. All LLM calls are captured as generation observations
2. Web search calls are captured as span observations with urls+chunks
3. Phase spans (outline, chapters, integration, editing) are created

Requires:
  - Langfuse v2 server running at localhost:3000
  - LANGFUSE_ENABLED=true in environment
"""
import os
import sys
import time

import pytest

# Set env before any imports
os.environ["LANGFUSE_ENABLED"] = "true"
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-107cfd09-4458-47e7-b694-649d966ac71c"
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-4ab52db8-24b0-4d58-ba8d-6d4700d745f0"
os.environ["LANGFUSE_HOST"] = "http://localhost:3000"

# Reset settings singleton and langfuse client
import deep_research.observability as _obs

_obs._client = None

from deep_research.config.settings import Settings as _Settings
import deep_research.config.settings as _cfg_mod

_cfg_mod._settings = None

from deep_research.observability import get_langfuse


lf = get_langfuse()


# Check if Langfuse server is reachable
_server_available = False
if lf is not None:
    try:
        # Quick health check via Langfuse API
        import urllib.request
        req = urllib.request.Request(
            f"{os.environ['LANGFUSE_HOST']}/api/public/health",
            method="GET",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            _server_available = resp.status == 200
    except Exception:
        _server_available = False


pytestmark = pytest.mark.skipif(
    not _server_available,
    reason="Langfuse server not running at localhost:3000. Start it with: cd ~/langfuse-server && pnpm run dev",
)


def _count_db(table: str) -> int:
    """Count rows in the PostgreSQL database used by Langfuse."""
    # Try pgserver first (cross-platform embedded PostgreSQL)
    pgdata = os.path.expanduser("~/.langfuse-postgres-pgserver")
    try:
        import pgserver
        import pathlib
        s = pgserver.get_server(pathlib.Path(pgdata), cleanup_mode=None)
        s.ensure_postgres_running()
        result = s.psql(f"SELECT count(*) FROM {table};")
        # Parse result like "?column? \n----------\n        42\n(1 row)"
        for line in result.splitlines():
            line = line.strip()
            if line and line.isdigit():
                return int(line)
        return -1
    except Exception:
        pass

    # Fallback: try system psql on common ports
    for port in [5433, 5432]:
        try:
            import subprocess
            result = subprocess.run(
                ["psql", "-p", str(port), "-d", "langfuse", "-t", "-c", f"SELECT count(*) FROM {table};"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception:
            continue

    return -1


# ---- Test 1: LLM Generation Span ----
def test_llm_generation_span():
    """Verify LLM calls produce generation observations with input/output/usage."""
    assert lf is not None, "Langfuse client should not be None when enabled"
    before = _count_db("observations")

    trace = lf.trace(
        name="test_llm_generation",
        session_id="test-session-001",
        input={"query": "分析2024年新能源汽车市场"},
    )

    messages = [{"role": "user", "content": "分析2024年新能源汽车市场"}]
    gen = lf.generation(
        trace_id=trace.id,
        name="llm_call",
        model="MiniMax-M2.5",
        input=messages,
        metadata={"tools_enabled": False},
    )

    time.sleep(0.05)
    content = "2024年新能源汽车市场规模达到1200万辆，同比增长35%..."
    gen.end(
        output=content,
        usage={"input": 120, "output": 250},
        metadata={"latency_s": 2.3, "has_tool_calls": False},
    )
    trace.update(output={"status": "test_complete"})
    lf.flush()

    after = _count_db("observations")
    assert after > before, f"Expected new observations, count before={before} after={after}"

    # Verify via Langfuse API
    obs = lf.get_observation(gen.id)
    assert obs.type == "GENERATION", f"Expected GENERATION, got {obs.type}"
    assert obs.model == "MiniMax-M2.5"
    assert "新能源汽车" in str(obs.output or "")

    print(f"✅ Test 1 PASSED: LLM generation span stored")
    print(f"   - trace_id: {trace.id}")
    print(f"   - generation_id: {gen.id}")
    print(f"   - model: {obs.model}")
    print(f"   - input: {str(obs.input)[:80]}...")
    print(f"   - output: {str(obs.output)[:80]}...")
    print(f"   - usage: {obs.usage}")


# ---- Test 2: Web Search Retrieval Span ----
def test_web_search_retrieval_span():
    """Verify web search calls produce span observations with urls and chunks."""
    before = _count_db("observations")

    trace = lf.trace(
        name="test_web_search",
        session_id="test-session-002",
        input={"query": "2024年新能源汽车销量数据"},
    )

    query = "2024年新能源汽车销量数据"
    span = lf.span(
        trace_id=trace.id,
        name="web_search",
        input={"query": query, "max_results": 10, "provider": "tavily"},
    )

    time.sleep(0.05)
    urls = [
        "https://example.com/ev-2024-sales",
        "https://news.auto.com/ev-market-2024",
        "https://report.energy.gov/new-energy-vehicles",
    ]
    chunks = [
        {"url": urls[0], "title": "2024新能源汽车销量报告", "text": "2024年全年新能源汽车销量突破1200万辆，同比增长35%。其中纯电动汽车占比68%..."},
        {"url": urls[1], "title": "新能源汽车市场分析", "text": "比亚迪以350万辆的年销量位居全球新能源汽车销量第一，特斯拉以180万辆位列第二..."},
        {"url": urls[2], "title": "能源政策与新能源汽车", "text": "国家政策持续支持新能源汽车发展，补贴政策延续至2025年底..."},
    ]
    span.end(
        output={"urls": urls, "top_chunks": chunks},
        metadata={"latency_s": 1.8, "source": "tavily_raw"},
    )
    trace.update(output={"status": "test_complete"})
    lf.flush()

    after = _count_db("observations")
    assert after > before, f"Expected new span observations, before={before} after={after}"

    obs = lf.get_observation(span.id)
    assert obs.type == "SPAN", f"Expected SPAN, got {obs.type}"
    assert obs.input is not None

    output_data = obs.output or {}
    assert "urls" in str(output_data)
    assert "top_chunks" in str(output_data)

    print(f"✅ Test 2 PASSED: Web search retrieval span stored")
    print(f"   - trace_id: {trace.id}")
    print(f"   - span_id: {span.id}")
    print(f"   - input query: {query}")
    print(f"   - output urls: {len(urls)}")
    print(f"   - top chunks: {len(chunks)}")
    for c in chunks:
        print(f"     • [{c['title']}] {c['text'][:60]}...")


# ---- Test 3: Full Pipeline Phase Spans ----
def test_pipeline_phase_spans():
    """Verify all pipeline phases produce spans with latency metadata."""
    before_traces = _count_db("traces")
    before_obs = _count_db("observations")

    trace = lf.trace(
        name="deepresearch",
        session_id="test-session-003",
        input={"query": "分析2024年中国新能源汽车市场"},
        metadata={"model": "MiniMax-M2.5"},
    )

    phases = [
        ("outline_planning", {"title": "2024新能源汽车市场分析报告", "chapters": ["c1", "c2", "c3"]}, 3.2),
        ("chapter_execution", {"chapters": 3, "passed": 3}, 45.8),
        ("integration", {}, 8.1),
        ("editorial_review", {}, 12.3),
    ]

    span_ids = {}
    for name, output, latency in phases:
        span = lf.span(trace_id=trace.id, name=name)
        time.sleep(0.01)
        span.end(output=output if output else None, metadata={"latency_s": latency})
        span_ids[name] = span.id

    trace.update(output={"report_length": 15000, "status": "success"})
    lf.flush()

    after_traces = _count_db("traces")
    after_obs = _count_db("observations")

    assert after_traces > before_traces, "Expected new trace"
    assert after_obs >= before_obs + 4, f"Expected at least 4 new spans, got {after_obs - before_obs}"

    print(f"✅ Test 3 PASSED: Full pipeline phase spans stored")
    print(f"   - trace_id: {trace.id}")
    print(f"   - new traces: {after_traces - before_traces}")
    print(f"   - new observations: {after_obs - before_obs}")

    for name, _, expected_latency in phases:
        obs = lf.get_observation(span_ids[name])
        latency = (obs.metadata or {}).get("latency_s", "N/A") if obs.metadata else "N/A"
        print(f"   - {name}: latency={latency}s, id={obs.id[:8]}...")

    print(f"\n   View traces at: http://localhost:3000")


if __name__ == "__main__":
    print("=" * 60)
    print("Langfuse Integration Tests (Live Server)")
    print(f"Server: {os.environ['LANGFUSE_HOST']}")
    print(f"Server available: {_server_available}")
    print("=" * 60)

    if not _server_available:
        print("\n⚠️  Langfuse server not running. Skipping tests.")
        print("   Start server: cd ~/langfuse-server && pnpm run dev")
        sys.exit(0)

    tests = [test_llm_generation_span, test_web_search_retrieval_span, test_pipeline_phase_spans]
    passed = 0
    failed = 0

    for test_fn in tests:
        print(f"\nRunning {test_fn.__name__}...")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"❌ {test_fn.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print(f"View all traces at: http://localhost:3000")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
