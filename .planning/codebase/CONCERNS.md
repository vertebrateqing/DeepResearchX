# Codebase Concerns

**Analysis Date:** 2026-04-25

## Tech Debt

### PWS Refactor Left Old Code Paths Inconsistent
- **Issue:** The PWS (Planner-Worker-Synthesizer) refactor replaced hard-coded sub-agents with `GenericWorker`, but `FinancialRAGAgent` (`agents/financial_rag_agent.py`) remains as a standalone class and is **not invoked by the new V4 orchestrator**. The TODO.md explicitly states it is "独立能力，当前未被 orchestrator 调用".
- **Files:** `agents/financial_rag_agent.py`, `core/orchestrator.py`
- **Impact:** RAG pipeline code (query rewriting, retrieval, answer generation) exists but is unreachable in the main V4 flow. Maintenance burden without production value.
- **Fix approach:** Integrate `RAGPipeline` as a tool available to `ChapterWorker` during revision, or remove the standalone agent and expose RAG via `GenericWorker` tools.

### Skills System Is Orphaned
- **Issue:** The skills framework (`skills/market_analysis.py`, `skills/industry_screening.py`, `skills/company_selection.py`, `skills/rag_qa.py`) defines typed Pydantic input/output schemas and `SimpleAgent`-based execution, but the V4 orchestrator never calls them. `core/skill_manager.py` exists but is unused by `OrchestratorAgent`.
- **Files:** `skills/*.py`, `core/skill_manager.py`
- **Impact:** Dead code; any bug fixes to skills are irrelevant to the running system.
- **Fix approach:** Wire skills into `ChapterWorker.revise()` as optional capabilities, or delete the skills directory to reduce confusion.

### Hardcoded Values Scattered Across Core
- **Issue:** Multiple magic numbers and hardcoded thresholds without central configuration:
  - `MAX_CONTEXT_CHARS = 6000` in `rag/pipeline.py:318`
  - `max_tokens=4096` in `core/chapter_worker.py:151`
  - `max_tokens=8192` in `core/integration.py:116` and `core/editor.py:202`
  - `max_chars = 15000` / `12000` in `core/editor.py:101,170`
  - `MAX_ITERATIONS = 10` in `core/agent.py:197`
  - `DEFAULT_MAX_PARALLEL = 3` in `core/research_plan.py:21`
  - `MAX_REVISION_ROUNDS = 2` in `core/reviser.py:71`
  - `MAX_EDIT_ROUNDS = 2` in `core/editor.py:66`
- **Files:** `rag/pipeline.py`, `core/chapter_worker.py`, `core/integration.py`, `core/editor.py`, `core/agent.py`, `core/research_plan.py`, `core/reviser.py`
- **Impact:** Tuning requires editing source code across many files; inconsistent limits cause context overflow or truncated reports.
- **Fix approach:** Centralize in `config/default.yaml` under a `budgets` or `limits` section and load via `get_settings()`.

### Duplicate JSON Extraction Logic
- **Issue:** Every LLM-response parser re-implements the same markdown-code-block stripping and BOM handling:
  - `core/worker.py:235-283` (stack-based bracket matching)
  - `core/planner.py:119-127`, `270-277`
  - `core/intent_clarifier.py:273-278`, `426-430`
  - `core/outline_planner.py:202-210`
  - `core/reviser.py:202-209`
  - `core/editor.py:266-273`
- **Files:** Multiple files across `core/`
- **Impact:** Bug fixes (e.g., the BOM fix in TODO.md) had to be applied in 6+ places. Future parsing edge cases will require the same scatter-shot fixes.
- **Fix approach:** Extract a single `parse_json_from_llm(text: str) -> dict` utility in `core/utils.py` or similar.

## Known Bugs

### RAG Merge Logic Inverted (Confirmed Unfixed in Source)
- **Issue:** `rag/pipeline.py:34` uses `if score < seen[doc_id]["score"]` when merging retrieval results. For cosine/l2 distance, lower is better, so the condition should be `>` (keep the better score). This discards high-quality documents and retains low-quality ones.
- **Files:** `rag/pipeline.py:32-36`
- **Trigger:** Any RAG query with query rewriting (`rewrite=True`, the default) that retrieves the same doc via multiple variants.
- **Workaround:** Set `rewrite=False` in `RAGPipeline.query()`, but this hurts recall.
- **Fix approach:** Change `<` to `>` on line 34.

### Base URL Has Incorrect Path Suffix
- **Issue:** `config/default.yaml:31` sets `base_url: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`. OpenAI-compatible SDKs append `/chat/completions` themselves, so the effective URL becomes `.../chat/completions/chat/completions`, causing 404.
- **Files:** `config/default.yaml:31`, `config/default.yaml:56`
- **Trigger:** Any LLM call when using the default config without overriding `base_url` via environment.
- **Workaround:** Override `base_url` via `OPENAI_API_BASE` or edit the YAML.
- **Fix approach:** Remove `/chat/completions` and `/embeddings` suffixes from `default.yaml`.

### `_merge_web_results` Captures Wrong Query
- **Issue:** `agents/financial_rag_agent.py:39` uses `result.get("query", "")` where `result` is the loop variable. After the loop ends, `result` holds the last iteration's value, so the returned merged result always has the wrong query string.
- **Files:** `agents/financial_rag_agent.py:19-42`
- **Trigger:** Any call to `FinancialRAGAgent.run()` that performs web search with multiple variants.
- **Fix approach:** Capture the correct query before the loop or use a list comprehension.

### ReAct Loop Returns Empty String on Exhaustion
- **Issue:** `core/agent.py:230-305` runs `for iteration in range(self.max_iterations)`. If all 10 iterations complete without a final answer (no tool calls and no content), `final_answer` remains `""` and is returned silently. Callers cannot distinguish "thinking" from "failure".
- **Files:** `core/agent.py:228-318`
- **Trigger:** Edge case where LLM returns tool calls on every iteration or empty content.
- **Fix approach:** After the loop, check `if not final_answer` and return an error `AgentMessage`.

## Security Considerations

### API Keys in Config YAML with Environment Variable Fallback
- **Risk:** `config/default.yaml` contains `${OPENAI_API_KEY}`, `${TAVILY_API_KEY}`, etc. If the environment variable is unset, the literal string `"${OPENAI_API_KEY}"` is passed to the SDK, which may leak the placeholder in error logs or HTTP requests.
- **Files:** `config/default.yaml:21,49,56,97`, `config/settings.py`
- **Current mitigation:** Pydantic settings load from `.env` file; `SettingsConfigDict` has `extra="ignore"`.
- **Recommendations:** Add validation in `settings.py` to raise if `api_key` is missing or looks like an unexpanded placeholder. Do not proceed with LLM calls when keys are missing.

### Session Store Writes User Content to Disk Unencrypted
- **Risk:** `memory/session_store.py` persists full conversation history (including potentially sensitive user queries about personal finances) to JSON and Markdown files on the local filesystem without encryption.
- **Files:** `memory/session_store.py:29-46`
- **Current mitigation:** Files are in `./financial_agent/data/sessions/` which is `.gitignore`d.
- **Recommendations:** Document that session data is stored locally; consider adding a retention policy and cleanup job.

### Web Scraper Fetches Arbitrary URLs
- **Risk:** `tools/web_scraper.py` fetches URLs returned by search engines without URL validation or domain allowlisting. Malicious search results could lead to SSRF or fetching harmful content.
- **Files:** `tools/web_scraper.py`
- **Current mitigation:** `max_text_length=30000` limits response size; timeouts are set.
- **Recommendations:** Add a domain allowlist/blocklist and validate URL schemes (only `http`/`https`).

## Performance Bottlenecks

### Memory Save Syncs All Historical Findings Every Time
- **Problem:** `memory/manager.py:88-112` calls `save(sync_long_term=True)` which iterates over **all** `accumulated_findings` and embeds each one via `LongTermStore.add_finding()`. In a long session this is O(N) and blocks on embedding API calls.
- **Files:** `memory/manager.py:88-112`
- **Cause:** No tracking of which findings have already been synced.
- **Improvement path:** Add a `last_synced_index` or `synced` flag to `MemoryFinding` and only sync new findings.

### BM25 Full Rebuild on Every Document Addition
- **Problem:** `rag/bm25_store.py:64-66` rebuilds the entire BM25 index (`O(N^2)`) every time `add_documents()` is called. With many documents this becomes prohibitively slow.
- **Files:** `rag/bm25_store.py:46-68`
- **Cause:** `rank_bm25.BM25Okapi` does not support incremental updates; the code rebuilds from `self._documents` each time.
- **Improvement path:** Batch document additions and rebuild once per batch, or switch to an incremental BM25 implementation.

### Embedding Tool Creates New HTTP Client per Call
- **Problem:** `tools/embedding_call.py:44-53` lazily creates an `httpx.AsyncClient` but `EmbeddingTool` is instantiated fresh in many places (`EmbeddingService.tool` property, `LongTermStore`, `RAGPipeline`). Each instance gets its own client, losing HTTP connection reuse.
- **Files:** `tools/embedding_call.py:44-53`, `rag/embedding.py`, `memory/long_term_store.py`
- **Cause:** No shared client singleton across the embedding stack.
- **Improvement path:** Use a module-level or dependency-injected shared `AsyncClient` for all embedding calls.

### Query Rewriting Lacks Skip Logic
- **Problem:** `rag/query_rewriter.py:38-89` always calls the LLM to rewrite queries, even for simple commands like "exit", "status", or very short queries (< 10 chars).
- **Files:** `rag/query_rewriter.py`, `core/orchestrator.py` (pre-search in `_pre_search_chapters`)
- **Cause:** No early-exit heuristic before the LLM call.
- **Improvement path:** Add a guard: if query is a known command or very short, skip rewriting and return `[query]`.

### Pre-Search Does Not Respect Chapter Dependencies
- **Problem:** `core/orchestrator.py:307-406` pre-searches all chapters in parallel without considering that some chapters may depend on others. Research contexts for downstream chapters may be stale or irrelevant because upstream chapters have not been written yet.
- **Files:** `core/orchestrator.py:307-406`
- **Impact:** Wasted API calls and potentially misleading pre-search context for dependent chapters.
- **Improvement path:** Only pre-search chapters with `depends_on=[]` or whose dependencies have completed.

## Fragile Areas

### JSON Parsing from LLM Outputs
- **Files:** `core/worker.py`, `core/planner.py`, `core/intent_clarifier.py`, `core/outline_planner.py`, `core/reviser.py`, `core/editor.py`
- **Why fragile:** Every component that talks to an LLM parses JSON from free-text responses. Despite stack-based bracket matching and BOM stripping, malformed JSON (e.g., unescaped quotes inside strings, truncated responses) can still crash the parser. Fallbacks exist but often auto-pass or return empty data, masking failures.
- **Safe modification:** Always test JSON parsing with adversarial inputs (nested braces, unicode, truncated output). Use a centralized parser utility.
- **Test coverage:** Unit tests cover `worker.py` JSON extraction but do not test all parser edge cases across all components.

### Chapter Worker Single-Shot Writing
- **Files:** `core/chapter_worker.py:111-194`
- **Why fragile:** `ChapterWorker.execute()` makes a single LLM call with a large prompt (system prompt + research context + objective). If the LLM truncates output due to `max_tokens=4096`, the chapter is cut off mid-sentence. The word count is measured as `len(chapter_text)` (character count, not actual Chinese word count), so it does not accurately reflect content length.
- **Safe modification:** Add a continuation loop if the response ends abruptly. Use actual word segmentation (e.g., `jieba`) for accurate word counts.
- **Test coverage:** No tests for chapter generation or truncation handling.

### Revision Loop May Infinite-Loop on Persistent Failure
- **Files:** `core/reviser.py:233-275`
- **Why fragile:** `revision_loop` runs `MAX_REVISION_ROUNDS + 1` times. If `worker.revise()` fails silently (catches exception and logs), the loop continues but the chapter file may be unchanged. The reviewer then re-reviews the same text and may produce identical feedback, wasting API calls.
- **Safe modification:** Detect no-op revisions (file unchanged) and break early. Add a hash/checksum comparison before and after revision.

### Report Generator PDF Dependency
- **Files:** `core/report_generator.py:11-26`, `298-340`
- **Why fragile:** PDF generation depends on `weasyprint` which requires GTK+/Pango/Cairo. On minimal Linux containers (Alpine) or macOS without Homebrew, this fails silently and falls back to HTML. Chinese characters render as boxes if system fonts are missing.
- **Safe modification:** Add a `playwright` fallback for PDF generation, or pre-install Noto Sans CJK fonts in deployment environments.

## Scaling Limits

### LLM API Rate Limiting
- **Current capacity:** `DAGScheduler` limits to `DEFAULT_MAX_PARALLEL = 3` workers.
- **Limit:** With 6-10 chapters in V4, plus pre-search (up to 3 queries per chapter), plus revision loops (up to 2 rounds), a single user request can generate 30-60+ LLM calls. At 3 concurrent, this is serially throttled.
- **Scaling path:** Make `max_parallel` configurable per provider. Add request queuing with exponential backoff and jitter.

### Context Window Exhaustion in Integration/Editor
- **Current capacity:** `IntegrationAgent.integrate()` concatenates all chapter files into a single prompt. With 8 chapters at ~1000 chars each, the prompt exceeds 8000 chars. `EditorAgent` truncates at 15000 chars.
- **Limit:** For deep research with 10+ chapters, the integration prompt will exceed typical 8K-16K context windows, causing truncation or API errors.
- **Scaling path:** Chunk-based integration (integrate 2-3 chapters at a time, then merge), or use a model with larger context (32K+).

### ChromaDB Single-Collection per User
- **Current capacity:** `LongTermStore` creates one ChromaDB collection per `user_id`.
- **Limit:** ChromaDB `PersistentClient` is file-based and not designed for high-concurrency writes. Multiple simultaneous sessions for the same user will contend on the same SQLite-backed collection.
- **Scaling path:** Use a server-based vector DB (e.g., Qdrant, Milvus, pgvector) for production deployments.

## Dependencies at Risk

### `akshare` Data Source Reliability
- **Risk:** `akshare` is a community-maintained scraping library for Chinese financial data. Its APIs change frequently without semantic versioning. `AKShareTool` hard-codes function names like `stock_zh_a_spot_em`, `stock_financial_report_sina`.
- **Impact:** If `akshare` renames or removes these functions, the tool crashes and returns `{"error": ...}`.
- **Migration plan:** Add API versioning/shimming layer. Cache successful schema mappings. Provide graceful degradation to web search when AKShare fails.

### `weasyprint` Heavy System Dependencies
- **Risk:** `weasyprint` depends on system libraries (Pango, Cairo, GDK). These are often missing in Docker Alpine images and CI environments.
- **Impact:** PDF generation silently fails; users only get Markdown.
- **Migration plan:** Replace with `playwright` + headless Chromium for PDF generation, or use a cloud PDF API.

### `jieba` for Chinese Tokenization
- **Risk:** `jieba` is used in `BM25Store` for search tokenization. It loads a dictionary on first use, which is slow and memory-intensive.
- **Impact:** First BM25 search after process startup has high latency.
- **Migration plan:** Pre-load `jieba` at application startup. Consider `pkuseg` or `hanlp` for better accuracy if needed.

## Missing Critical Features

### No End-to-End Integration Tests
- **Problem gap:** The test suite (`tests/unit/`) has 23 unit tests covering `BaseAgent`, `Registry`, `Message`, and basic tool mocks. There are no tests for:
  - `OrchestratorAgent.run()` full pipeline
  - `ChapterWorker.execute()` + `revise()`
  - `ReviserAgent.revision_loop()`
  - `IntegrationAgent.integrate()`
  - `EditorAgent.edit_loop()`
  - RAG pipeline end-to-end
- **Blocks:** Safe refactoring of V4 architecture. Any change to orchestrator flow risks breaking the entire pipeline undetected.
- **Files:** `tests/unit/test_core.py`, `tests/unit/test_rag.py`, `tests/unit/test_skills.py`, `tests/unit/test_tools.py`

### No Benchmark Dataset for V4
- **Problem gap:** `evaluation/evaluator.py` expects a benchmark JSON file, but no benchmark dataset is present in the repo. `AgentEvaluator.run_benchmark()` cannot be run without external data.
- **Blocks:** Automated regression testing and quality measurement.
- **Files:** `evaluation/evaluator.py`, `evaluation/`

### No graceful handling for missing API keys at runtime
- **Problem gap:** If `OPENAI_API_KEY` or `TAVILY_API_KEY` is missing, the system will proceed until the first API call and then fail with an opaque HTTP 401 error. There is no startup health check.
- **Blocks:** First-time user experience and deployment validation.
- **Files:** `core/agent.py`, `tools/web_search.py`

## Test Coverage Gaps

### V4 Orchestrator Pipeline Untested
- **What's not tested:** The entire 5-phase V4 flow (outline -> chapters -> revision -> integration -> editor -> report).
- **Files:** `core/orchestrator.py`, `core/chapter_worker.py`, `core/reviser.py`, `core/integration.py`, `core/editor.py`, `core/outline_planner.py`
- **Risk:** A refactor of any V4 component could break the entire report generation flow with no test failure.
- **Priority:** High

### RAG Pipeline Merge Logic Untested
- **What's not tested:** `_merge_retrieval_results` score comparison logic, multimodal PDF ingestion, query rewriting.
- **Files:** `rag/pipeline.py`, `rag/query_rewriter.py`
- **Risk:** The inverted score bug has persisted because no test covers multi-variant retrieval merging.
- **Priority:** High

### Memory Manager Long-Term Sync Untested
- **What's not tested:** `MemoryManager.save()` with `sync_long_term=True`, `LongTermStore.add_finding()`, `search_findings()` with entity filtering.
- **Files:** `memory/manager.py`, `memory/long_term_store.py`
- **Risk:** Memory leaks, duplicate embeddings, or silent failures in long-term storage.
- **Priority:** Medium

### Context Manager Compression Untested
- **What's not tested:** `ContextManager.compress_text()`, `ContextCompactor.compact()`, token budget enforcement.
- **Files:** `core/context_manager.py`, `core/context_compactor.py`
- **Risk:** Context overflow causing LLM API errors or degraded output quality.
- **Priority:** Medium

---

*Concerns audit: 2026-04-25*
