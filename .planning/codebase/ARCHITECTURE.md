# Architecture

**Analysis Date:** 2026-04-25

## Pattern Overview

**Overall:** Planner-Worker-Synthesizer (PWS) with V4 Layered Report Generation

**Key Characteristics:**
- Planner is the sole decision-maker; Workers are generic role-injected executors
- Research plans are structured DAGs (JSON), not hardcoded code paths
- Worker outputs are structured `Finding` objects with summary/details separation
- Context is layered: Planner sees summaries, Workers see task inputs, Synthesizer sees full details
- Report generation uses a 5-phase pipeline: Outline -> Parallel Chapters -> Review -> Integrate -> Edit
- Session-based memory with working, session, and long-term layers

## Layers

**CLI / Entry Layer:**
- Purpose: User interaction, argument parsing, session management
- Location: `financial_agent/cli.py`
- Contains: `run_interactive()`, `run_single()`, argparse setup
- Depends on: `OrchestratorAgent`, `MemoryManager`
- Used by: End user via command line

**Orchestration Layer:**
- Purpose: Main pipeline controller implementing V4 5-phase report generation
- Location: `financial_agent/core/orchestrator.py`
- Contains: `OrchestratorAgent` class, `_execute_research()`, `_execute_chapters()`, `_pre_search_chapters()`
- Depends on: `OutlinePlanner`, `ChapterWorker`, `ReviserAgent`, `IntegrationAgent`, `EditorAgent`, `ReportGenerator`, `IntentClarifier`, `MemoryManager`
- Used by: `cli.py`

**Planning Layer:**
- Purpose: Generate research plans as DAGs and evaluate sufficiency of findings
- Location: `financial_agent/core/planner.py`
- Contains: `ResearchPlanner` class, `PlanUpdate` class, DAG validation (`_is_valid_dag`)
- Depends on: `LLMClient`, `ResearchPlan`, `TaskNode`, `Finding`
- Used by: `OrchestratorAgent` (PWS mode), standalone deepresearch flows

**Worker Layer:**
- Purpose: Execute individual research tasks with role-based dynamic prompts
- Location: `financial_agent/core/worker.py`
- Contains: `GenericWorker` (extends `ReActAgent`), `ROLE_PROMPTS` mapping
- Depends on: `ReActAgent`, `TaskNode`, `Finding`, `AKShareTool`, `WebSearchTool`, `WebScraperTool`
- Used by: `DAGScheduler` (PWS mode), can be used directly by orchestrator

**Chapter Worker Layer (V4):**
- Purpose: Write individual report chapters with pre-search context
- Location: `financial_agent/core/chapter_worker.py`
- Contains: `ChapterWorker` class, single-shot writing + ReAct-based revision
- Depends on: `LLMClient`, `ChapterOutline`, `Finding`, `AKShareTool`, `WebSearchTool`, `WebScraperTool`
- Used by: `OrchestratorAgent._execute_chapters()`

**Quality Control Layer (V4):**
- Purpose: Review chapters and drafts against structured scoring criteria
- Location: `financial_agent/core/reviser.py`, `financial_agent/core/editor.py`
- Contains: `ReviserAgent` (5-dimension chapter review), `EditorAgent` (4-dimension draft review)
- Depends on: `LLMClient`, `ChapterOutline`
- Used by: `OrchestratorAgent` during Phase 3 (revision) and Phase 4 (editing)

**Integration Layer (V4):**
- Purpose: Merge chapters into coherent draft with transitions and deduplication
- Location: `financial_agent/core/integration.py`
- Contains: `IntegrationAgent` class
- Depends on: `LLMClient`
- Used by: `OrchestratorAgent` during Phase 3

**Report Generation Layer:**
- Purpose: Export final reports to Markdown and PDF
- Location: `financial_agent/core/report_generator.py`
- Contains: `ReportGenerator` class, V4 and legacy markdown generators, PDF conversion
- Depends on: `markdown` library (optional), `weasyprint` (optional)
- Used by: `OrchestratorAgent` during Phase 5

**RAG Pipeline Layer:**
- Purpose: Document ingestion, hybrid retrieval, and question answering over financial reports
- Location: `financial_agent/rag/pipeline.py`, `financial_agent/rag/hybrid_retriever.py`
- Contains: `RAGPipeline`, `HybridRetriever` (vector + BM25 with RRF fusion)
- Depends on: `ChromaVectorStore`, `BM25Store`, `EmbeddingService`, `CrossEncoderReranker`, `QueryRewriter`
- Used by: `FinancialRAGAgent` (`financial_agent/agents/financial_rag_agent.py`)

**Memory Layer:**
- Purpose: Session persistence, conversation history, task tracking, findings accumulation
- Location: `financial_agent/memory/manager.py`, `financial_agent/memory/models.py`
- Contains: `MemoryManager`, `SessionMemory`, `TaskState`, `MemoryFinding`, `UserPreferences`
- Depends on: `SessionStore`, `LongTermStore`
- Used by: `OrchestratorAgent`, `cli.py`

**Context Management Layer:**
- Purpose: Token budgeting and automatic compression across Planner/Worker/Synthesizer contexts
- Location: `financial_agent/core/context_manager.py`, `financial_agent/core/context_compactor.py`
- Contains: `ContextManager`, `TokenBudget`, `ContextCompactor`
- Depends on: `LLMClient`
- Used by: `GenericWorker` (via `build_worker_context`), available to Planner and Synthesizer

**Base Framework Layer:**
- Purpose: Abstract base classes for Agent, Tool, Skill, and Message protocol
- Location: `financial_agent/core/base.py`, `financial_agent/core/message.py`, `financial_agent/core/agent.py`
- Contains: `BaseAgent`, `BaseTool`, `BaseSkill`, `AgentMessage`, `LLMClient`, `ReActAgent`, `SimpleAgent`
- Depends on: `httpx`, `tenacity`, `pydantic`
- Used by: All agent and tool implementations

**Tool Layer:**
- Purpose: External data access and web interactions
- Location: `financial_agent/tools/`
- Contains: `AKShareTool` (A-share financial data), `WebSearchTool` (Tavily/DuckDuckGo), `WebScraperTool` (HTTP scraping)
- Depends on: `akshare`, `tavily-python`, `aiohttp`
- Used by: `GenericWorker`, `ChapterWorker`, `FinancialRAGAgent`

**Skill Layer:**
- Purpose: Higher-level reusable analytical capabilities (legacy, not currently used by PWS)
- Location: `financial_agent/skills/`
- Contains: `MarketAnalysisSkill`, `IndustryScreeningSkill`, `CompanySelectionSkill`, `RAGQASkill`
- Depends on: `BaseSkill`, `SimpleAgent`
- Used by: Currently unused by PWS pipeline; designed for optional Worker skill injection

## Data Flow

**V4 Report Generation Flow:**

1. User query enters via `cli.py` -> `OrchestratorAgent.run()`
2. `IntentClarifier` detects missing slots; up to 3 rounds of HITL clarification
3. `OutlinePlanner.generate_outline()` produces `ReportOutline` with `ChapterOutline` list
4. `_pre_search_chapters()` runs multi-query web search per chapter in parallel
5. `ChapterWorker.execute()` writes each chapter in parallel (single-shot LLM with pre-search context)
6. `ReviserAgent.revision_loop()` reviews each chapter in parallel; up to 2 revision rounds via `ChapterWorker.revise()` (ReAct)
7. `IntegrationAgent.integrate()` merges all chapter files into `draft.md` with transitions
8. `EditorAgent.edit_loop()` reviews draft; up to 2 edit rounds with revision application
9. `ReportGenerator.save()` exports final report to Markdown and PDF
10. `MemoryManager` persists session, findings, and conversation history

**PWS DeepResearch Flow (legacy/alternative):**

1. `ResearchPlanner.generate_plan()` creates `ResearchPlan` (DAG of `TaskNode`s)
2. `DAGScheduler.execute()` topologically sorts and runs ready tasks in parallel batches (max 3 concurrent)
3. `GenericWorker.execute()` runs ReAct loop per task, outputs `Finding`
4. `ResearchPlanner.evaluate()` checks if findings are sufficient; appends new tasks if needed
5. Synthesizer (orchestrator-level) consumes all `Finding.details` to generate report

**RAG Pipeline Flow:**

1. `RAGPipeline.ingest_documents()` splits documents, generates embeddings, indexes to vector + BM25 stores
2. `RAGPipeline.query()` rewrites query into variants, retrieves via `HybridRetriever` (RRF fusion)
3. Optional `CrossEncoderReranker` reranks results
4. `RAGPipeline.generate_answer()` builds context from retrieved docs and calls LLM

**State Management:**
- Session state: `SessionMemory` in `MemoryManager` tracks conversation, tasks, findings
- Plan state: `ResearchPlan` tracks `TaskNode` statuses (pending/running/completed/failed)
- Context budgets: `TokenBudget` instances in `ContextManager` enforce per-layer limits
- File-based artifacts: `outline.json`, `chapter_{id}.md`, `reviews.json`, `draft.md`, `edits.json` in session dir

## Key Abstractions

**Finding:**
- Purpose: Standardized worker output separating Planner-facing summary from Synthesizer-facing details
- Examples: `financial_agent/core/finding.py`
- Pattern: Dataclass with `to_planner_context()` for token-efficient consumption

**TaskNode / ResearchPlan:**
- Purpose: Executable DAG representing a research plan
- Examples: `financial_agent/core/research_plan.py`
- Pattern: Dataclass with dependency tracking; `DAGScheduler` performs topological batch execution

**ReActAgent:**
- Purpose: LLM-driven tool-use loop with reasoning and acting
- Examples: `financial_agent/core/agent.py`
- Pattern: Iterates up to `max_iterations`, calls tools via OpenAI function-calling format, accumulates messages

**ChapterOutline / ReportOutline:**
- Purpose: Structured report specification for V4 generation
- Examples: `financial_agent/core/outline_planner.py`
- Pattern: Dataclasses with `to_dict()` / `from_dict()` / `save()` / `load()` for JSON persistence

## Entry Points

**CLI Entry Point:**
- Location: `financial_agent/cli.py`
- Triggers: Command line (`python -m financial_agent.cli`) or installed script `a-stock-analyzer`
- Responsibilities: Parse args, setup logging, create `OrchestratorAgent`, run interactive or single-query mode

**OrchestratorAgent.run():**
- Location: `financial_agent/core/orchestrator.py`
- Triggers: Called by CLI or programmatically
- Responsibilities: Full V4 pipeline execution, clarification handling, session management

**Ingest Reports Script:**
- Location: `financial_agent/scripts/ingest_reports.py` (referenced in `pyproject.toml`)
- Triggers: `ingest-reports` CLI command
- Responsibilities: Load PDFs into RAG vector/BM25 stores

## Error Handling

**Strategy:** Graceful degradation with fallback paths at every LLM-dependent step

**Patterns:**
- LLM JSON parsing failures: Extract from markdown code blocks, then raw bracket matching, then wrap as summary (`worker.py:_extract_json_from_text`)
- Plan generation failure: Fallback to minimal 3-task plan (`planner.py:_fallback_plan`)
- Outline generation failure: Fallback to generic 3-chapter outline (`outline_planner.py:_fallback_outline`)
- Chapter write failure: Create fallback `Finding` with error details, continue pipeline (`orchestrator.py:_execute_chapters`)
- Review failure: Auto-pass with default scores to avoid blocking (`reviser.py:review_chapter`, `editor.py:review_draft`)
- Task failure in DAG: Retry up to 2 times, then mark failed; failed tasks satisfy downstream dependencies (`research_plan.py:get_ready_tasks`)
- Integration failure: Simple concatenation fallback (`integration.py:integrate`)

## Cross-Cutting Concerns

**Logging:** Python `logging` module with structured format; configured in `cli.py` via `get_settings().logging`; extensive timing instrumentation throughout core modules

**Validation:** Pydantic models for config (`Settings` in `config/settings.py`); JSON schema validation via manual parsing with fallback; DAG cycle detection via Kahn's algorithm

**Authentication:** API keys via environment variables (`OPENAI_API_KEY`, `TAVILY_API_KEY`); injected through `${VAR}` expansion in YAML config

**Context Isolation:** `AgentRunContext` (`core/context.py`) provides per-execution message/tool/skill tracking; child contexts are isolated from parents

**Registry:** Global singleton `Registry` (`core/registry.py`) for tool/skill/agent discovery; `ToolManager` and `SkillManager` provide typed access

---

*Architecture analysis: 2026-04-25*
