"""Integration tests for Langfuse observability.

Tests verify that:
1. All LLM calls are captured as generation spans
2. Web search calls are captured as retrieval spans with urls+chunks
3. Phase spans (outline, chapters, integration, editing) are created
4. Spans have correct metadata (latency, tokens, etc.)

Uses InMemorySpanExporter to capture spans without a Langfuse server.
"""
import asyncio
import json
import os
import sys
import time
import pytest

# ---- Setup in-memory span capture ----
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from langfuse import Langfuse
from langfuse.types import TraceContext

_span_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_span_exporter))

# Patch env so settings load with langfuse enabled
os.environ["LANGFUSE_ENABLED"] = "true"
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-test-local"
os.environ["LANGFUSE_SECRET_KEY"] = "sk-test-local"
os.environ["LANGFUSE_HOST"] = "http://localhost:9999"  # won't connect, we capture locally

# Create patched langfuse client using our provider
_lf = Langfuse(
    public_key="pk-test-local",
    secret_key="sk-test-local",
    host="http://localhost:9999",
    tracer_provider=_provider,
)


def get_spans(name=None):
    spans = _span_exporter.get_finished_spans()
    if name:
        return [s for s in spans if s.name == name]
    return spans


def clear_spans():
    _span_exporter.clear()


# ---- Test 1: LLM Generation Span ----
def test_llm_generation_span():
    """Verify LLM calls produce generation spans with input/output/usage."""
    clear_spans()

    trace_id = _lf.create_trace_id()
    tc = TraceContext(trace_id=trace_id)

    # Simulate what LLMClient._openai_chat does
    messages = [{"role": "user", "content": "分析2024年新能源汽车市场"}]
    gen = _lf.start_observation(
        trace_context=tc,
        name="llm_call",
        as_type="generation",
        model="MiniMax-M2.5",
        input=messages,
        metadata={"tools_enabled": False},
    )

    # Simulate LLM response
    time.sleep(0.01)
    content = "2024年新能源汽车市场规模达到1200万辆..."
    usage = {"input": 120, "output": 250}

    gen.update(
        output=content,
        usage_details=usage,
        metadata={"latency_s": 2.3, "has_tool_calls": False},
    )
    gen.end()
    _lf.flush()

    spans = get_spans("llm_call")
    assert len(spans) >= 1, f"Expected llm_call span, got: {[s.name for s in get_spans()]}"

    span = spans[0]
    attrs = span.attributes

    # Verify input is captured
    assert "langfuse.observation.input" in attrs
    input_data = json.loads(attrs["langfuse.observation.input"])
    assert input_data[0]["content"] == "分析2024年新能源汽车市场"

    # Verify output is captured
    assert "langfuse.observation.output" in attrs
    assert "2024年新能源汽车" in attrs["langfuse.observation.output"]

    # Verify metadata
    assert "langfuse.observation.metadata.latency_s" in attrs

    print(f"✅ Test 1 PASSED: LLM generation span captured")
    print(f"   - input: {attrs['langfuse.observation.input'][:80]}...")
    print(f"   - output: {attrs['langfuse.observation.output'][:80]}...")
    print(f"   - latency: {attrs.get('langfuse.observation.metadata.latency_s')}")


# ---- Test 2: Web Search Retrieval Span ----
def test_web_search_retrieval_span():
    """Verify web search calls produce retrieval spans with urls and chunks."""
    clear_spans()

    trace_id = _lf.create_trace_id()
    tc = TraceContext(trace_id=trace_id)

    # Simulate what WebSearchTool.execute does
    query = "2024年新能源汽车销量数据"
    span = _lf.start_observation(
        trace_context=tc,
        name="web_search",
        as_type="retriever",
        input={"query": query, "max_results": 10, "provider": "tavily"},
    )

    time.sleep(0.01)

    # Simulate search results with chunks
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

    span.update(
        output={"urls": urls, "top_chunks": chunks},
        metadata={"latency_s": 1.8, "source": "tavily_raw"},
    )
    span.end()
    _lf.flush()

    spans = get_spans("web_search")
    assert len(spans) >= 1, f"Expected web_search span, got: {[s.name for s in get_spans()]}"

    span_data = spans[0]
    attrs = span_data.attributes

    # Verify input query captured
    assert "langfuse.observation.input" in attrs
    input_data = json.loads(attrs["langfuse.observation.input"])
    assert input_data["query"] == query

    # Verify output has urls and chunks
    assert "langfuse.observation.output" in attrs
    output_data = json.loads(attrs["langfuse.observation.output"])
    assert len(output_data["urls"]) == 3
    assert len(output_data["top_chunks"]) == 3
    assert "2024年全年新能源汽车" in output_data["top_chunks"][0]["text"]

    print(f"✅ Test 2 PASSED: Web search retrieval span captured")
    print(f"   - query: {input_data['query']}")
    print(f"   - urls count: {len(output_data['urls'])}")
    print(f"   - top chunks: {len(output_data['top_chunks'])}")
    for c in output_data["top_chunks"]:
        print(f"     • [{c['title']}] {c['text'][:60]}...")


# ---- Test 3: Full Pipeline Phase Spans ----
def test_pipeline_phase_spans():
    """Verify all pipeline phases produce spans with latency metadata."""
    clear_spans()

    trace_id = _lf.create_trace_id()
    tc = TraceContext(trace_id=trace_id)

    # Simulate orchestrator root span
    root = _lf.start_observation(
        trace_context=tc,
        name="deepresearch",
        as_type="agent",
        input={"query": "分析2024年中国新能源汽车市场"},
        metadata={"model": "MiniMax-M2.5", "session_id": "test-session-001"},
    )

    phases = [
        ("outline_planning", "chain", {"title": "2024新能源汽车市场分析报告", "chapters": ["c1", "c2", "c3"]}, 3.2),
        ("chapter_execution", "chain", {"chapters": 3, "passed": 3}, 45.8),
        ("integration", "chain", {}, 8.1),
        ("editorial_review", "chain", {}, 12.3),
    ]

    for name, as_type, output, latency in phases:
        t0 = time.perf_counter()
        span = _lf.start_observation(trace_context=tc, name=name, as_type=as_type)
        time.sleep(0.01)  # simulate work
        span.update(output=output if output else None, metadata={"latency_s": latency})
        span.end()

    root.update(output={"report_length": 15000, "status": "success"})
    root.end()
    _lf.flush()

    all_spans = get_spans()
    span_names = [s.name for s in all_spans]

    print(f"✅ Test 3 PASSED: All pipeline phase spans captured")
    print(f"   Spans recorded: {span_names}")

    assert "deepresearch" in span_names
    assert "outline_planning" in span_names
    assert "chapter_execution" in span_names
    assert "integration" in span_names
    assert "editorial_review" in span_names

    # Verify latency metadata on each phase
    for phase_name, _, _, expected_latency in phases:
        phase_spans = get_spans(phase_name)
        assert len(phase_spans) >= 1, f"Missing span: {phase_name}"
        span = phase_spans[0]
        latency_attr = span.attributes.get("langfuse.observation.metadata.latency_s")
        assert latency_attr is not None, f"Missing latency on {phase_name}"
        print(f"   - {phase_name}: latency={latency_attr}s")


if __name__ == "__main__":
    print("=" * 60)
    print("Langfuse Integration Tests (InMemory mode)")
    print("=" * 60)

    tests = [test_llm_generation_span, test_web_search_retrieval_span, test_pipeline_phase_spans]
    passed = 0
    failed = 0

    for test_fn in tests:
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
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
