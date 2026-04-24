# Roadmap: A-Stock Analyzer

**Created:** 2026-04-25
**Granularity:** Standard
**Mode:** YOLO

---

## Overview

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Critical Bug Fixes | Fix all confirmed bugs causing incorrect behavior or silent failures | BUG-01, BUG-02, BUG-03, BUG-04, QUAL-03, SECU-03 | 6 |
| 2 | Code Quality & Security | Centralize config, extract utilities, harden security | QUAL-01, QUAL-02, SECU-01, SECU-02, PERF-01 | 5 |
| 3 | Test Coverage | Add tests for fixed bugs and critical untested paths | TEST-01, TEST-02, TEST-03 | 3 |

**Coverage:** 13 v1 requirements mapped to 3 phases. All requirements covered ✓

---

## Phase 1: Critical Bug Fixes

**Goal:** Fix all confirmed bugs causing incorrect behavior or silent failures.

**Requirements:** BUG-01, BUG-02, BUG-03, BUG-04, QUAL-03, SECU-03

**Success Criteria:**
1. RAG pipeline `_merge_retrieval_results` correctly keeps highest-quality documents (not lowest)
2. Default config `base_url` works without manual override when using DashScope
3. `FinancialRAGAgent._merge_web_results` returns the original query, not the last loop variable
4. `ReActAgent` returns a clear error message when max iterations exhausted, not empty string
5. All existing 23 unit tests still pass after fixes
6. No new mypy or ruff errors introduced

**UI hint:** no

**AI integration hint:** no

**Depends on:** None

**Estimated complexity:** Medium — 6 files, well-defined changes

---

## Phase 2: Code Quality & Security

**Goal:** Centralize configuration, eliminate duplicate code, and harden security boundaries.

**Requirements:** QUAL-01, QUAL-02, SECU-01, SECU-02, PERF-01

**Success Criteria:**
1. All previously hardcoded thresholds/limits are loaded from `config/default.yaml` via `get_settings()`
2. A single `parse_json_from_llm()` utility exists in `core/utils.py` and is used by all JSON-parsing components
3. Startup raises clear `ValueError` if any required API key is missing or is an unexpanded placeholder
4. Web scraper rejects non-http/https URLs and logs skipped domains
5. Memory manager only syncs new findings since last sync, not all accumulated findings
6. All existing tests pass; new tests added for config loading and JSON utility

**UI hint:** no

**AI integration hint:** no

**Depends on:** Phase 1

**Estimated complexity:** Medium-High — refactoring across 10+ files, requires careful coordination

---

## Phase 3: Test Coverage

**Goal:** Add tests for the bugs fixed in Phase 1 and critical untested code paths.

**Requirements:** TEST-01, TEST-02, TEST-03

**Success Criteria:**
1. RAG pipeline merge test verifies correct score comparison with multi-variant retrieval
2. ReAct loop test verifies error message returned on max iteration exhaustion
3. Config validation test verifies startup failure with missing/placeholder API keys
4. Overall test count increases from 23 to 26+
5. All tests pass in CI/local

**UI hint:** no

**AI integration hint:** no

**Depends on:** Phase 2

**Estimated complexity:** Low — focused test additions

---

## Milestones

### Milestone 1: Stable Foundation
- **Includes:** Phases 1, 2, 3
- **Definition of done:** All confirmed bugs fixed, code quality improved, security hardened, critical paths tested
- **Target:** After Phase 3 completion

---

*Roadmap created: 2026-04-25*
*Last updated: 2026-04-25*
