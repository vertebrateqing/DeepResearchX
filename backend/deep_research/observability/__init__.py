from __future__ import annotations
"""Langfuse v2 observability helpers.

v2 API (langfuse>=2.0.0,<3.0.0):
  - lf.trace(id=trace_id, name=..., input=..., session_id=...) → StatefulTraceClient
  - trace.span(name=..., input=...) → StatefulSpanClient  (call .end(output=...) to close)
  - trace.generation(name=..., model=..., input=...) → StatefulGenerationClient
  - lf.flush()
  - lf.create_dataset(name=...) / lf.create_dataset_item(...)

Usage:
    from deep_research.observability import get_langfuse

    lf = get_langfuse()
    if lf:
        trace = lf.trace(id=trace_id, name="deepresearch", input={"query": q})
        gen = trace.generation(name="llm_call", model="...", input=messages)
        gen.end(output=content, usage={"input": n, "output": m})
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from langfuse import Langfuse

_client: "Langfuse | None" = None


def get_langfuse() -> "Langfuse | None":
    """Return the shared Langfuse v2 client, or None if disabled/not installed."""
    global _client
    try:
        from deep_research.config.settings import get_settings
        cfg = get_settings().langfuse
    except (ImportError, ModuleNotFoundError):
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
        except (ImportError, ModuleNotFoundError, ValueError):
            return None

    return _client


def make_trace_context(trace_id: Optional[str]) -> Optional[str]:
    """Return trace_id as-is (used for v2 API compatibility shim)."""
    return trace_id
