# DeepResearchX

Multi-agent deep research system that turns a single user query into a structured
report through a Planner → Worker → Synthesizer pipeline with streaming output.

## Project Context

- **Entry point:** `backend/main.py` (FastAPI app exported as `app`)
- **Package manager:** [uv](https://docs.astral.sh/uv/) — `uv sync` and `uv run` only;
  no `requirements.txt` or hand-managed venvs
- **Architecture:** Intent Clarifier → Outline Planner → Parallel Chapter Workers
  (DAG-aware) → Reviser → Integration → Editor
- **Tech stack:** Python 3.10+, FastAPI, Pydantic v2, ChromaDB, Tavily/DuckDuckGo,
  OpenAI-compatible LLM clients, optional Langfuse observability
- **Streaming:** SSE via `api/streaming.py`; every phase update flows through it

## Layout

```
backend/
├── main.py                       FastAPI entrypoint (uses lifespan handler)
├── pyproject.toml                Single source of truth for deps + tool config
├── api/                          Router, request/response models, SSE service
└── deep_research/
    ├── config/{default.yaml,settings.py}
    ├── core/                     orchestrator, outline_planner, chapter_worker,
    │                             reviser, integration, editor, intent_clarifier
    ├── tools/                    web_search, web_scraper, llm_call
    ├── rag/                      ChromaDB hybrid retrieval, document_loader
    └── utils/                    Shared JSON parsing + text utilities
```

Session artifacts (outline.json, chapter_*.md, draft.md) live under
`backend/deep_research/data/sessions/{session_id}/`.

## Working With This Codebase

- All agents are async. Blocking calls (DuckDuckGo, file I/O) go through
  `asyncio.to_thread()`.
- Configuration: `config/default.yaml` + Pydantic-Settings in `config/settings.py`.
  `.env` is auto-loaded from `backend/` then the repo root.
- LLM outputs are parsed from markdown code blocks; centralized helpers live in
  `deep_research/utils/`.
- The `langfuse` integration is feature-flagged behind `LANGFUSE_ENABLED=true`.

## Common Commands

```bash
# Install / sync deps
cd backend && uv sync

# Run the API server (auto-reload)
cd backend && uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run tests
cd backend && uv run pytest

# Lint / format
cd backend && uv run ruff check .
```

The repo-level `./dev-start.sh` and `./dev-stop.sh` wrap these for the
backend + frontend pair.
