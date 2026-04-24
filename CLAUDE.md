# A-Stock Analyzer

This is a brownfield Python project — a multi-agent A-share (A股) investment analysis system.

## Project Context

- **Entry point:** `financial_agent/cli.py`
- **Architecture:** Planner-Worker-Synthesizer (PWS) with V4 layered report generation
- **Tech stack:** Python 3.10+, Pydantic v2, ChromaDB, AKShare, Tavily/DuckDuckGo search
- **Report flow:** Intent Clarification → Outline → Parallel Chapters → Review → Integrate → Edit → Markdown/PDF

## Current Work

Bug fixes and tech debt remediation. See `.planning/codebase/CONCERNS.md` for full audit.

**Key constraints:** Keep ChromaDB (no vector DB migration). Maintain existing CLI and session formats.

## Working With This Codebase

- All agents are async. Tools use `asyncio.to_thread()` for blocking calls (pandas, DuckDuckGo).
- Configuration lives in `config/default.yaml` and `config/settings.py` (Pydantic-Settings with .env).
- LLM outputs are parsed from markdown code blocks with fallbacks. JSON parsing is duplicated across many files — candidate for centralization.
- Session artifacts (outline.json, chapter_*.md, draft.md) are written to `./financial_agent/data/sessions/{session_id}/`.
- The skills directory (`financial_agent/skills/`) is currently orphaned — not called by the V4 orchestrator.

## Before Changing Code

1. Read `.planning/codebase/CONCERNS.md` for known issues
2. Read `.planning/codebase/ARCHITECTURE.md` for data flow
3. Check `financial_agent/TODO.md` for recent refactor notes
4. Run existing tests: `pytest financial_agent/tests/`

## GSD Workflow

This project uses GSD for planning and execution.

- **Roadmap:** `.planning/ROADMAP.md`
- **Requirements:** `.planning/REQUIREMENTS.md`
- **State:** `.planning/STATE.md`
- **Next step:** `/gsd-plan-phase 1` then `/gsd-execute-phase 1`
