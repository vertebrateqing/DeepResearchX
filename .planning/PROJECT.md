# A-Stock Analyzer

## What This Is

A production-grade multi-agent system for A-share (A股) investment analysis. Users input a research question (e.g., "Analyze BYD's investment potential"), and the system generates a professional deep-research report via a Planner-Worker-Synthesizer (PWS) pipeline with a V4 layered report generation architecture.

The system features: intent clarification, dynamic outline planning, parallel chapter research with pre-search, multi-dimension review loops, integration/editing, and final Markdown/PDF output. It also includes a RAG pipeline for financial report ingestion and question answering.

## Core Value

Generate accurate, well-sourced, professional-grade A-share investment analysis reports from natural language queries with minimal user intervention.

## Requirements

### Validated

- ✓ V4 layered report generation (Outline → Chapters → Review → Integrate → Edit → Report) — existing
- ✓ PWS (Planner-Worker-Synthesizer) architecture with DAG-based parallel execution — existing
- ✓ Multi-tool ReAct agents (Web search, AKShare data, web scraping) — existing
- ✓ Hybrid RAG retrieval (ChromaDB vector + BM25 keyword + RRF fusion) — existing
- ✓ Session-based memory with short-term and long-term storage — existing
- ✓ Context management with token budgeting and compression — existing
- ✓ Report export to Markdown and PDF — existing
- ✓ Evaluation framework with LLM-as-Judge — existing

### Active

- [ ] Fix known bugs in RAG pipeline, config, web search, and ReAct loop
- [ ] Centralize scattered hardcoded values into config YAML
- [ ] Extract duplicate JSON parsing logic into a shared utility
- [ ] Add API key validation at startup to prevent opaque runtime failures
- [ ] Add URL validation to web scraper for security
- [ ] Fix memory manager syncing all findings on every save
- [ ] Add test coverage for RAG merge logic and V4 pipeline components

### Out of Scope

- Replace ChromaDB with another vector database — ChromaDB is sufficient for current scale; user explicitly deferred this decision
- Mobile app or web UI — CLI-only for v1
- Real-time market data streaming — AKShare batch queries are sufficient
- Multi-user concurrency with shared collections — single-user deployment model
- Video/image generation in reports — text and tables only

## Context

- **Brownfield project:** Significant existing codebase with a recently completed PWS refactor. Old skill-based agents were removed; V4 orchestrator is the primary flow.
- **Domain:** Chinese A-share market analysis. All reports are in Chinese. Data sources are AKShare (domestic) and web search (Tavily/DuckDuckGo).
- **Tech environment:** Python 3.10+, async throughout, Pydantic v2, ChromaDB local vector store.
- **Known issues:** See `.planning/codebase/CONCERNS.md` for full audit. Critical bugs include inverted RAG merge logic, incorrect base URL in default config, and orphaned skills system.
- **Architecture:** See `.planning/codebase/ARCHITECTURE.md` and `financial_agent/design_v4_architecture.md`.

## Constraints

- **Tech stack:** Python 3.10+, keep ChromaDB (no vector DB migration)
- **Timeline:** Bug fixes and tech debt are highest priority; new features deferred
- **Compatibility:** Must maintain existing CLI interface and session format
- **Performance:** Target <5 min per report on standard queries; current bottleneck is LLM API latency
- **Security:** No secrets in code; API keys via env vars only

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Keep ChromaDB | User explicitly deferred vector DB migration; sufficient for current single-user scale | — Pending |
| PWS over hardcoded pipeline | Eliminates rigid sub-agent wiring; enables dynamic research plans | ✓ Good |
| V4 layered report generation | Separates outline, writing, review, integration, editing into distinct phases | ✓ Good |
| Skills system unused | V4 orchestrator does not call skills; they remain as optional utilities | ⚠️ Revisit |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-25 after initialization*
