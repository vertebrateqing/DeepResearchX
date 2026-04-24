# Phase 1: Critical Bug Fixes - Context

**Gathered:** 2026-04-25 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix all confirmed bugs in the codebase that cause incorrect behavior or silent failures. Each bug has a specific file location and one-line fix identified in CONCERNS.md. No architectural changes — surgical fixes only.

</domain>

<decisions>
## Implementation Decisions

### RAG Pipeline Merge Logic (BUG-01)
- **D-01:** Change `rag/pipeline.py:34` from `if score < seen[doc_id]["score"]` to `if score > seen[doc_id]["score"]` — for cosine distance, lower is better, so keep the document with the better (lower) score
- **D-02:** Add unit test for `_merge_retrieval_results` covering multi-variant retrieval with duplicate docs

### Default Config Base URL (BUG-02)
- **D-03:** Remove `/chat/completions` suffix from `config/default.yaml:31` — the OpenAI-compatible SDK appends this itself
- **D-04:** Remove `/embeddings` suffix from `config/default.yaml:56` — same double-append issue

### FinancialRAGAgent Web Results (BUG-03)
- **D-05:** Fix `agents/financial_rag_agent.py:39` — capture the correct `query` before the loop instead of using the loop variable after loop exit

### ReAct Agent Loop (BUG-04 / SECU-03)
- **D-06:** After the `for iteration` loop in `core/agent.py:230-305`, check `if not final_answer` and return an `AgentMessage` with `role="error"` and clear error content instead of returning empty string
- **D-07:** Error message should be in Chinese (consistent with rest of codebase) — e.g., "分析完成但未获得有效结果，请重试或简化问题"

### Code Style
- **D-08:** All fixes must pass existing test suite (23 tests) and not introduce new ruff/mypy errors
- **D-09:** Maintain backward compatibility — no function signature changes unless absolutely necessary

### Claude's Discretion
- Exact error message wording for ReAct loop (as long as it's clear and Chinese)
- Whether to add `@pytest.mark.skip` for new tests if they need external API keys
- Refactoring approach for `_merge_web_results` (list comprehension vs explicit capture)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Bug documentation
- `.planning/codebase/CONCERNS.md` §Known Bugs — Full bug descriptions with file paths, line numbers, and trigger conditions

### Source files to modify
- `financial_agent/rag/pipeline.py` — `_merge_retrieval_results` method (line 32-36)
- `financial_agent/config/default.yaml` — `llm.base_url` (line 31) and `embedding.base_url` (line 56)
- `financial_agent/agents/financial_rag_agent.py` — `_merge_web_results` method (line 19-42)
- `financial_agent/core/agent.py` — `ReActAgent.run()` loop (line 228-318)

### Related context
- `financial_agent/TODO.md` — Recent refactor notes and bug fix history
- `financial_agent/design_v4_architecture.md` — V4 architecture design

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/finding.py` — `Finding` dataclass for structured outputs; `AgentMessage` in `core/message.py` for error responses
- `tests/unit/test_rag.py` — Existing RAG tests to extend
- `tests/unit/test_core.py` — Existing core tests to extend

### Established Patterns
- Error handling: Graceful degradation with fallback paths (see ARCHITECTURE.md Error Handling section)
- Config loading: `get_settings()` from `config/settings.py` loads YAML with env var expansion
- Testing: pytest with asyncio_mode=auto; tests in `tests/unit/`

### Integration Points
- `rag/pipeline.py` is used by `FinancialRAGAgent` and indirectly by RAG skills
- `config/default.yaml` is loaded at startup by `settings.py`; changes affect all LLM/embedding calls
- `core/agent.py` is the base for `GenericWorker`, `ChapterWorker`, and all ReAct-based agents
</code_context>

<specifics>
## Specific Ideas

- Fixes should be minimal and surgical — one-line changes where possible
- Chinese error messages preferred for user-facing output (consistent with rest of system)
- No breaking changes to public APIs or CLI interface
</specifics>

<deferred>
## Deferred Ideas

- Integrating `FinancialRAGAgent` into V4 orchestrator (Phase 2/v2 architecture)
- Centralizing hardcoded values to config YAML (Phase 2)
- Extracting shared JSON parsing utility (Phase 2)
- Adding comprehensive RAG pipeline tests beyond merge logic (Phase 3)

</deferred>

---

*Phase: 01-critical-bug-fixes*
*Context gathered: 2026-04-25*
