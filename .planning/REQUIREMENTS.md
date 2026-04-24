# Requirements: A-Stock Analyzer

**Defined:** 2026-04-25
**Core Value:** Generate accurate, well-sourced, professional-grade A-share investment analysis reports from natural language queries

## v1 Requirements

### Critical Bug Fixes

- [ ] **BUG-01**: Fix RAG merge logic — `rag/pipeline.py:34` score comparison uses `<` instead of `>` for cosine distance, discarding better documents
- [ ] **BUG-02**: Fix base URL suffix — `config/default.yaml:31,56` has `/chat/completions` and `/embeddings` appended to base_url, causing 404s because SDK appends them again
- [ ] **BUG-03**: Fix `_merge_web_results` query capture — `agents/financial_rag_agent.py:39` uses loop variable `result` after loop ends, always returning the last query
- [ ] **BUG-04**: Fix ReAct loop empty return — `core/agent.py:230-305` returns empty string silently when all iterations exhaust without answer; should return an error AgentMessage

### Code Quality

- [ ] **QUAL-01**: Centralize hardcoded values — Move `MAX_CONTEXT_CHARS`, `max_tokens`, `MAX_ITERATIONS`, `DEFAULT_MAX_PARALLEL`, `MAX_REVISION_ROUNDS`, `MAX_EDIT_ROUNDS` into `config/default.yaml`
- [ ] **QUAL-02**: Extract JSON parsing utility — Create `core/utils.py` with `parse_json_from_llm()` to replace duplicate parsing in worker.py, planner.py, intent_clarifier.py, outline_planner.py, reviser.py, editor.py
- [ ] **QUAL-03**: Fix `_merge_web_results` query capture in FinancialRAGAgent

### Security & Robustness

- [ ] **SECU-01**: Add API key validation at startup — `config/settings.py` should raise clear error if `api_key` is missing or is an unexpanded placeholder like `${OPENAI_API_KEY}`
- [ ] **SECU-02**: Add URL validation to web scraper — `tools/web_scraper.py` should validate scheme (http/https only) and optionally allowlist/blocklist domains
- [ ] **SECU-03**: Fix ReAct loop to return error on exhaustion instead of empty string

### Performance

- [ ] **PERF-01**: Fix memory manager full sync — `memory/manager.py:88-112` should track already-synced findings and only sync new ones instead of re-embedding all accumulated findings on every save

### Testing

- [ ] **TEST-01**: Add RAG pipeline merge test — Cover `_merge_retrieval_results` score comparison and multi-variant retrieval merging
- [ ] **TEST-02**: Add ReAct loop exhaustion test — Verify agent returns error message when max iterations reached without answer
- [ ] **TEST-03**: Add config validation test — Verify startup fails gracefully with missing/placeholder API keys

## v2 Requirements

### Architecture Cleanup

- **ARCH-01**: Integrate `FinancialRAGAgent` into V4 orchestrator or remove standalone agent
- **ARCH-02**: Wire skills system into ChapterWorker or remove orphaned skills directory
- **ARCH-03**: Replace `weasyprint` with `playwright` for PDF generation to remove GTK+/Pango dependency

### Performance Scaling

- **PERF-02**: Batch BM25 document additions instead of full rebuild on every `add_documents()` call
- **PERF-03**: Share `httpx.AsyncClient` singleton across embedding stack instead of per-instance clients
- **PERF-04**: Add query rewriting skip logic for short queries and known commands

### Testing

- **TEST-04**: Add end-to-end V4 pipeline test (outline → chapters → revision → integration → edit → report)
- **TEST-05**: Add benchmark dataset for automated regression testing

## Out of Scope

| Feature | Reason |
|---------|--------|
| Replace ChromaDB with Qdrant/Milvus/pgvector | User explicitly deferred; ChromaDB sufficient for current single-user scale |
| Mobile app or web frontend | CLI-only scope for v1 |
| Real-time streaming market data | AKShare batch queries sufficient for report generation |
| Multi-user authentication | Single-user deployment model |
| OAuth/login system | Not needed for local CLI tool |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BUG-01 | Phase 1 | Pending |
| BUG-02 | Phase 1 | Pending |
| BUG-03 | Phase 1 | Pending |
| BUG-04 | Phase 1 | Pending |
| QUAL-01 | Phase 2 | Pending |
| QUAL-02 | Phase 2 | Pending |
| QUAL-03 | Phase 1 | Pending |
| SECU-01 | Phase 2 | Pending |
| SECU-02 | Phase 2 | Pending |
| SECU-03 | Phase 1 | Pending |
| PERF-01 | Phase 2 | Pending |
| TEST-01 | Phase 3 | Pending |
| TEST-02 | Phase 3 | Pending |
| TEST-03 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-25*
*Last updated: 2026-04-25 after initial definition*
