# Codebase Structure

**Analysis Date:** 2026-04-25

## Directory Layout

```
financial_agent/
├── cli.py                      # CLI entry point (interactive + single-query modes)
├── pyproject.toml              # Project metadata, dependencies, tool configs
├── TODO.md                     # PWS refactoring progress tracker
├── __init__.py                 # Package init
│
├── agents/                     # Legacy agent implementations
│   └── financial_rag_agent.py  # Financial RAG sub-agent (standalone capability)
│
├── config/
│   ├── settings.py             # Pydantic-based configuration with env expansion
│   └── default.yaml            # Default YAML configuration (LLM, RAG, data sources)
│
├── core/                       # Core framework and V4 pipeline components
│   ├── __init__.py
│   ├── agent.py                # LLMClient, ReActAgent, SimpleAgent
│   ├── base.py                 # BaseAgent, BaseTool, BaseSkill, AgentContext
│   ├── chapter_worker.py       # ChapterWorker (V4 Phase 2: per-chapter writing)
│   ├── context.py              # AgentRunContext (execution isolation)
│   ├── context_compactor.py    # ContextCompactor (LLM-based context compression)
│   ├── context_manager.py      # ContextManager + TokenBudget (layered budgets)
│   ├── editor.py               # EditorAgent (V4 Phase 4b: final polish loop)
│   ├── finding.py              # Finding + Source dataclasses (structured output)
│   ├── integration.py          # IntegrationAgent (V4 Phase 4a: merge chapters)
│   ├── intent_clarifier.py     # IntentClarifier (HITL slot-filling clarification)
│   ├── message.py              # AgentMessage protocol (TASK/RESULT/ERROR/SUMMARY)
│   ├── orchestrator.py         # OrchestratorAgent (V4 5-phase pipeline controller)
│   ├── outline_planner.py      # OutlinePlanner (V4 Phase 1: report outline generation)
│   ├── planner.py              # ResearchPlanner (PWS plan generation + evaluation)
│   ├── registry.py             # Global Registry singleton (agents/skills/tools)
│   ├── report_generator.py     # ReportGenerator (Markdown + PDF export)
│   ├── research_plan.py        # ResearchPlan + TaskNode + DAGScheduler
│   ├── reviser.py              # ReviserAgent (V4 Phase 3: chapter quality review)
│   ├── skill_manager.py        # SkillManager (registry wrapper for skills)
│   ├── tool_manager.py         # ToolManager (registry wrapper for tools)
│   └── worker.py               # GenericWorker (PWS role-based sub-agent)
│
├── data/                       # Runtime data storage
│   ├── output/                 # Generated reports (MD/PDF)
│   ├── processed/              # Processed intermediate data
│   ├── raw/                    # Raw downloaded data
│   ├── sessions/               # Session working directories (outline, chapters, drafts)
│   └── vector_db/              # Chroma vector database persistence
│
├── evaluation/                 # Evaluation and benchmarking
│   └── benchmarks/             # Benchmark datasets
│
├── memory/                     # Session and long-term memory
│   ├── __init__.py
│   ├── long_term_store.py      # Persistent long-term memory store
│   ├── manager.py              # MemoryManager (coordinates all memory layers)
│   ├── models.py               # SessionMemory, TaskState, MemoryFinding, UserPreferences
│   └── session_store.py        # Session-level memory persistence
│
├── rag/                        # RAG pipeline components
│   ├── __init__.py
│   ├── bm25_store.py           # BM25 sparse retrieval index
│   ├── document_loader.py      # Document and PDF loaders
│   ├── embedding.py            # EmbeddingService (local + API)
│   ├── hybrid_retriever.py     # HybridRetriever (vector + BM25 with RRF)
│   ├── pipeline.py             # RAGPipeline (end-to-end ingest/query/answer)
│   ├── query_rewriter.py       # QueryRewriter (multi-variant expansion)
│   ├── reranker.py             # CrossEncoderReranker
│   ├── text_splitter.py        # RecursiveTextSplitter
│   ├── vector_store.py         # ChromaVectorStore
│   └── multimodal/             # Multimodal PDF processing
│       ├── __init__.py
│       ├── pdf_extractor.py    # MultimodalPDFExtractor (text/tables/images)
│       ├── unified_document.py # Unified document chunk model
│       └── vlm_processor.py    # VLM-based chart understanding
│
├── scripts/                    # Utility scripts
│   ├── ingest_reports.py       # PDF ingestion into RAG stores
│   └── run_evaluation.py       # Benchmark evaluation runner
│
├── skills/                     # Reusable analytical skills (legacy, unused by PWS)
│   ├── __init__.py
│   ├── company_selection.py    # Company selection skill
│   ├── industry_screening.py   # Industry screening skill
│   ├── market_analysis.py      # Market analysis skill
│   └── rag_qa.py               # RAG QA skill
│
├── tests/                      # Test suite
│   ├── __init__.py
│   ├── conftest.py             # Pytest configuration
│   └── unit/
│       ├── test_core.py        # Tests for base classes, messages, registry
│       ├── test_rag.py         # Tests for RAG components
│       ├── test_skills.py      # Tests for skills
│       └── test_tools.py       # Tests for tools
│
└── tools/                      # External tool implementations
    ├── __init__.py
    ├── akshare_data.py         # AKShare A-share financial data tool
    ├── embedding_call.py       # Embedding API wrapper
    ├── llm_call.py             # LLM API wrapper (legacy)
    ├── web_scraper.py          # Web scraping tool
    └── web_search.py           # Web search tool (Tavily/DuckDuckGo)
```

## Directory Purposes

**`core/`:**
- Purpose: Framework foundation and all V4/PWS pipeline components
- Contains: Base classes, agents, planners, workers, quality control, context management, messaging
- Key files: `orchestrator.py`, `planner.py`, `worker.py`, `chapter_worker.py`, `finding.py`, `research_plan.py`

**`rag/`:**
- Purpose: Document retrieval and question-answering pipeline
- Contains: Vector store, BM25, hybrid retriever, reranker, query rewriter, document loaders, multimodal processing
- Key files: `pipeline.py`, `hybrid_retriever.py`, `vector_store.py`, `bm25_store.py`

**`memory/`:**
- Purpose: Session persistence and user preference storage
- Contains: Session store, long-term store, memory models, manager
- Key files: `manager.py`, `models.py`, `session_store.py`

**`tools/`:**
- Purpose: External data and web interaction capabilities
- Contains: AKShare data fetcher, web search, web scraper
- Key files: `akshare_data.py`, `web_search.py`, `web_scraper.py`

**`skills/`:**
- Purpose: Higher-level analytical capabilities (legacy from pre-PWS architecture)
- Contains: Market analysis, industry screening, company selection, RAG QA skills
- Status: Not currently used by V4/PWS pipeline; available for future Worker skill injection

**`agents/`:**
- Purpose: Legacy specialized sub-agents
- Contains: `FinancialRAGAgent` (standalone RAG analysis agent)
- Status: `FinancialRAGAgent` preserved as independent capability; not called by orchestrator

**`data/`:**
- Purpose: Runtime data persistence (not committed to git)
- Contains: Output reports, session working files, vector DB, raw/processed data
- Key subdirs: `sessions/{session_id}/`, `output/`, `vector_db/`

**`config/`:**
- Purpose: Configuration loading and defaults
- Contains: Pydantic settings with env var expansion, default YAML
- Key files: `settings.py`, `default.yaml`

**`tests/`:**
- Purpose: Unit test suite
- Contains: Tests for core, RAG, skills, tools
- Key files: `unit/test_core.py`, `unit/test_rag.py`

## Key File Locations

**Entry Points:**
- `financial_agent/cli.py`: Main CLI entry point

**Configuration:**
- `financial_agent/config/settings.py`: Settings singleton with env expansion
- `financial_agent/config/default.yaml`: Default configuration values

**Core Logic:**
- `financial_agent/core/orchestrator.py`: V4 5-phase pipeline orchestration
- `financial_agent/core/planner.py`: PWS research plan generation and evaluation
- `financial_agent/core/worker.py`: PWS generic role-based worker
- `financial_agent/core/chapter_worker.py`: V4 per-chapter writer with revision
- `financial_agent/core/research_plan.py`: DAG scheduler and task execution

**Testing:**
- `financial_agent/tests/unit/test_core.py`: Core framework tests
- `financial_agent/tests/unit/test_rag.py`: RAG pipeline tests

## Naming Conventions

**Files:**
- Modules: `snake_case.py` (e.g., `chapter_worker.py`, `intent_clarifier.py`)
- Test files: `test_{module}.py` (e.g., `test_core.py`)

**Directories:**
- All lowercase, underscore-separated (e.g., `hybrid_retriever.py` lives in `rag/`)

**Classes:**
- PascalCase with descriptive suffixes: `*Agent`, `*Worker`, `*Manager`, `*Planner`, `*Skill`, `*Tool`
- Examples: `OrchestratorAgent`, `GenericWorker`, `MemoryManager`, `ResearchPlanner`, `RAGPipeline`

**Functions/Methods:**
- snake_case, async by default for I/O operations
- Examples: `generate_outline()`, `execute_chapters()`, `run_react_loop()`

## Where to Add New Code

**New V4 Pipeline Phase/Agent:**
- Implementation: `financial_agent/core/{new_phase}.py`
- Integration: Import and wire into `OrchestratorAgent._execute_research()` in `financial_agent/core/orchestrator.py`
- Tests: `financial_agent/tests/unit/test_core.py`

**New Tool (external data source):**
- Implementation: `financial_agent/tools/{tool_name}.py` (extend `BaseTool`)
- Registration: Tools are instantiated directly in Workers; no global registration required for V4
- Tests: `financial_agent/tests/unit/test_tools.py`

**New Worker Role (PWS):**
- Implementation: Add role prompt to `ROLE_PROMPTS` dict in `financial_agent/core/worker.py`
- Validation: Add role to `VALID_ROLES` in `financial_agent/core/planner.py`

**New RAG Component:**
- Implementation: `financial_agent/rag/{component}.py`
- Integration: Wire into `RAGPipeline` in `financial_agent/rag/pipeline.py`
- Tests: `financial_agent/tests/unit/test_rag.py`

**New Skill (legacy pattern):**
- Implementation: `financial_agent/skills/{skill_name}.py` (extend `BaseSkill`)
- Registration: Via `SkillManager` or direct instantiation
- Tests: `financial_agent/tests/unit/test_skills.py`

**Utilities/Helpers:**
- Shared helpers: Add to appropriate existing module in `core/` or create `financial_agent/core/utils.py`

## Special Directories

**`data/sessions/`:**
- Purpose: Per-session working files (outline, chapters, reviews, drafts, edits)
- Generated: Yes, at runtime by `OrchestratorAgent`
- Committed: No (add to `.gitignore`)
- File pattern: `data/sessions/{session_id}/outline.json`, `chapter_{id}.md`, `draft.md`, etc.

**`data/vector_db/`:**
- Purpose: Chroma vector database persistence
- Generated: Yes, by `RAGPipeline.ingest_documents()`
- Committed: No

**`data/output/`:**
- Purpose: Final generated reports (`.md`, `.pdf`, `.html`)
- Generated: Yes, by `ReportGenerator.save()`
- Committed: No

**`__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-04-25*
