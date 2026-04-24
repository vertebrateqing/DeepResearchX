# Coding Conventions

**Analysis Date:** 2026-04-25

## Naming Patterns

**Files:**
- Snake case: `chapter_worker.py`, `intent_clarifier.py`, `akshare_data.py`
- Test files prefixed with `test_`: `test_core.py`, `test_rag.py`, `test_tools.py`
- Module-level `__init__.py` present in every package directory

**Classes:**
- PascalCase for all classes: `ReActAgent`, `BaseTool`, `AgentMessage`, `RAGPipeline`
- Abstract base classes prefixed with `Base`: `BaseAgent`, `BaseTool`, `BaseSkill`
- Data transfer objects use suffixes: `Config`, `Input`, `Output`, `Result`, `Context`
  - `MarketAnalysisInput`, `RAGQAOutput`, `SkillContext`, `AgentContext`
- Agent classes suffixed with `Agent`: `OrchestratorAgent`, `ReviserAgent`, `EditorAgent`

**Functions/Methods:**
- Snake case for all functions and methods: `execute()`, `get_schema()`, `run_simple()`
- Private methods prefixed with underscore: `_parse_plan()`, `_fallback_plan()`, `_build_messages()`
- Async methods use `async def` consistently: `async def run()`, `async def execute()`
- Factory/constructor helpers prefixed with underscore: `_default_tools()`, `_fallback_outline()`

**Variables:**
- Snake case: `chapter_files`, `research_contexts`, `tool_calls`
- Private module-level variables prefixed with underscore: `_settings`, `_registry`, `_local_model_singleton`
- Constants in UPPER_SNAKE_CASE at module level: `MAX_ITERATIONS`, `PASS_THRESHOLD_TOTAL`, `CHARS_PER_TOKEN`

**Types:**
- Type hints used throughout; `Optional[X]` for nullable, `list[X]` for collections (Python 3.10+ syntax)
- Union types use `|` syntax: `str | None`, `dict[str, Any] | None`
- Return type `dict[str, Any]` is the standard for tool/skill execution results

## Code Style

**Formatting:**
- Black with line-length 100 (`pyproject.toml`)
- Target Python 3.10+
- Ruff with same line-length 100
- mypy in strict mode

**Key settings from `pyproject.toml`:**
```toml
[tool.black]
line-length = 100
target-version = ['py310']

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.mypy]
python_version = "3.10"
strict = true
```

## Import Organization

**Order:**
1. `from __future__ import annotations` (when used)
2. Standard library imports
3. Third-party imports
4. Internal project imports (`financial_agent.*`)

**Example from `core/orchestrator.py`:**
```python
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import asyncio

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient, SimpleAgent
```

**Path Aliases:**
- No import aliases used; full module paths preferred: `from financial_agent.core.base import BaseTool`

## Type Hints

**Required everywhere:**
- Function parameters and return types
- Class attributes (via type annotations or Pydantic `BaseModel`)
- Module-level variables

**Patterns:**
- Use `Any` sparingly; preferred for `dict[str, Any]` result payloads
- `Optional[X]` for nullable parameters/returns
- Forward references in quotes for self-referential types: `"AgentMessage"`, `"AgentRunContext"`
- `from __future__ import annotations` enables PEP 563 postponed evaluation

## Error Handling

**Patterns:**
- Try/except with specific logging at each layer
- Graceful degradation: fallback to simpler behavior on failure
- `raise_for_status()` on HTTP responses
- `ValueError` for registry duplicate registrations

**Example from `core/agent.py`:**
```python
try:
    response = await self.llm.chat(...)
except Exception as e:
    logger.error(f"LLM call failed: {e}")
    error_msg = AgentMessage.create_error(...)
    return error_msg
```

**Retry pattern with tenacity:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def chat(self, ...):
    ...
```

**Tool execution error handling:**
- Catch exceptions, log with `logger.error()`, return `{"error": str(e)}` dict
- Never let tool failures crash the agent loop

## Logging

**Framework:** Standard library `logging`

**Patterns:**
- One logger per module: `logger = logging.getLogger(__name__)`
- Component prefix in log messages: `[Orchestrator]`, `[ChapterWorker]`, `[Reviser]`, `[WebSearch]`
- `logger.info()` for high-level flow events
- `logger.debug()` for detailed payloads (full JSON, prompts, responses)
- `logger.warning()` for recoverable issues
- `logger.error()` for failures

**Timing instrumentation:**
```python
t0 = time.perf_counter()
# ... work ...
t1 = time.perf_counter()
logger.info(f"[Component] Operation done in {t1-t0:.2f}s")
```

## Docstrings

**Style:** Google-style docstrings

**Required on:**
- All public classes
- All public methods (especially abstract ones in `BaseTool`, `BaseSkill`, `BaseAgent`)
- Module docstrings describing purpose

**Example:**
```python
async def execute(self, **kwargs: Any) -> dict[str, Any]:
    """Execute the tool with given arguments.

    Args:
        **kwargs: Tool-specific arguments.

    Returns:
        Dict containing the tool execution result.
    """
```

## Async Patterns

**Mandatory async/await:**
- All I/O-bound operations are async: LLM calls, HTTP requests, tool execution
- Use `asyncio.to_thread()` for blocking synchronous libraries (e.g., `akshare`, `sentence_transformers`)
- `asyncio.gather()` for parallel execution

**Example:**
```python
# Parallel chapter execution
execute_tasks = [
    worker.execute(research_context=research_contexts.get(ch.chapter_id, ""))
    for worker, ch in zip(workers, outline.chapters)
]
raw_findings = await asyncio.gather(*execute_tasks, return_exceptions=True)
```

## Data Models

**Two modeling approaches:**

1. **Pydantic `BaseModel`** for config, messages, API schemas:
   - `AgentMessage`, `SkillContext`, `AgentContext`
   - Skill input/output schemas: `RAGQAInput`, `MarketAnalysisOutput`

2. **`@dataclass`** for internal domain models:
   - `Finding`, `Source`, `TaskState`, `MemoryFinding`
   - `ChapterOutline`, `ReportOutline`, `ReviewResult`

**Serialization:**
- Pydantic: `.model_dump()` (v2)
- Dataclasses: custom `.to_dict()` / `.from_dict()` methods with ISO datetime handling

## Function Design

**Size:** Functions are moderate (20-60 lines typical). Large orchestration methods in `OrchestratorAgent` are split into private helper methods (`_execute_research`, `_execute_chapters`, `_pre_search_chapters`).

**Parameters:**
- Use `Optional[X] = None` for optional params
- Config objects loaded via `get_settings()` inside constructors, not passed as params
- Context objects passed explicitly: `context: Optional[AgentContext] = None`

**Return Values:**
- Tools return `dict[str, Any]`
- Skills return `dict[str, Any]`
- Agents return `AgentMessage`
- Internal methods return structured domain objects (`Finding`, `ReviewResult`)

## Module Design

**Exports:**
- No explicit `__all__` declarations found
- Public API surfaced through imports in `__init__.py` files

**Barrel Files:**
- `core/__init__.py` exports key classes
- No heavy re-export patterns; direct imports preferred

## Unicode / Text Handling

**Sanitization pattern:**
```python
def _sanitize(text: str) -> str:
    """Remove invalid Unicode surrogate characters without corrupting valid text."""
    return "".join(ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF))
```
- Applied to LLM outputs and user inputs before storage/transmission
- JSON serialization uses `ensure_ascii=False` for Chinese text

## Configuration Access

**Singleton pattern:**
```python
from financial_agent.config.settings import get_settings

settings = get_settings()
```
- Settings loaded from YAML (`config/default.yaml`) with env var overrides
- Pydantic-settings with `env_prefix` per config section
- Lazy initialization via module-level singleton

---

*Convention analysis: 2026-04-25*
