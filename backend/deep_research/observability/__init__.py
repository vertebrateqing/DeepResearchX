from __future__ import annotations
"""Langfuse v4 observability helpers.

v4 API:
  - lf.start_observation(trace_context=TraceContext(trace_id=...), name=..., as_type=..., input=...)
    → returns LangfuseSpan / LangfuseGeneration (call .update(...) then .end())
  - lf.create_dataset_item(dataset_name=..., input=..., expected_output=..., source_trace_id=...)
  - lf.flush()
  - lf.create_trace_id() → str  (pre-allocate a trace id)

Usage:
    from deep_research.observability import get_langfuse, make_trace_context

    lf = get_langfuse()
    if lf:
        tc = make_trace_context(trace_id)
        span = lf.start_observation(trace_context=tc, name="web_search",
                                    as_type="retriever", input={...})
        # ... do work ...
        span.update(output={...}, metadata={...})
        span.end()
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from langfuse import Langfuse
    from langfuse.types import TraceContext

_client: "Langfuse | None" = None


def get_langfuse() -> "Langfuse | None":
    """Return the shared Langfuse client, or None if disabled/not installed."""
    global _client
    try:
        from deep_research.config.settings import get_settings
        cfg = get_settings().langfuse
    except Exception:
        return None

    if not cfg.enabled:
        return None

    if _client is None:
        try:
            from langfuse import Langfuse
            _client = Langfuse(
                public_key=cfg.public_key,
                secret_key=cfg.secret_key,
                host=cfg.host,
                flush_at=cfg.flush_at,
                flush_interval=cfg.flush_interval,
            )
        except Exception:
            return None

    return _client


def make_trace_context(trace_id: Optional[str]) -> "TraceContext | None":
    """Build a TraceContext dict for start_observation(..., trace_context=...)."""
    if not trace_id:
        return None
    try:
        from langfuse.types import TraceContext
        return TraceContext(trace_id=trace_id)
    except Exception:
        return None
