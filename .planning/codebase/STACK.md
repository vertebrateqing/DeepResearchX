# Technology Stack

**Analysis Date:** 2026-04-25

## Languages

**Primary:**
- Python 3.10+ — entire codebase (minimum 3.10, supports 3.11, 3.12)

**Secondary:**
- YAML — configuration files (`config/default.yaml`, `config/qwen.yaml`)
- Markdown — report generation and session human-readable output
- HTML/CSS — PDF report styling (`core/report_generator.py`)

## Runtime

**Environment:**
- CPython 3.10+
- Asyncio-based async runtime throughout (`async def` agents, tools, RAG pipeline)

**Package Manager:**
- pip (via `pyproject.toml`)
- Build backend: `hatchling`
- Lockfile: not present (no `uv.lock`, `poetry.lock`, or `requirements.txt`)

## Frameworks

**Core:**
- Pydantic v2 (`pydantic>=2.0`) — settings validation, skill input/output schemas
- Pydantic-Settings (`pydantic-settings>=2.0`) — environment-based config loading with `.env` support
- PyYAML (`pyyaml>=6.0`) — YAML configuration parsing

**Testing:**
- pytest (`pytest>=8.0`) — test runner
- pytest-asyncio (`pytest-asyncio>=0.23`) — async test support (`asyncio_mode = auto`)
- pytest-cov (`pytest-cov>=5.0`) — coverage

**Build/Dev:**
- Hatchling — PEP 517 build backend
- Ruff (`ruff>=0.4`) — linting (dev)
- mypy (`mypy>=1.9`) — type checking with `strict = true` (dev)
- Black (`black>=24.0`) — formatting, `line-length = 100`, `target-version = py310` (dev)

## Key Dependencies

**Critical:**
- `httpx>=0.27` — async HTTP client for all LLM API calls (`core/agent.py`)
- `tenacity>=8.2` — retry logic on LLM and embedding API calls (`@retry` decorators)
- `structlog>=24.1` — structured logging (configured in `config/settings.py`)
- `aiohttp>=3.9` — async HTTP (secondary to httpx)

**RAG / Vector:**
- `chromadb>=0.5` — local vector database (`rag/vector_store.py`)
- `rank-bm25>=0.2` — BM25 keyword retrieval (`rag/bm25_store.py`)
- `sentence-transformers>=3.0` — local embedding model loading (`tools/embedding_call.py`)
- `jieba` — Chinese text tokenization for BM25 (`rag/bm25_store.py`)
- `numpy>=1.24` — numerical operations (reranker cosine similarity)

**Document Processing:**
- `PyPDF2>=3.0` — PDF text extraction fallback (`rag/document_loader.py`, `tools/web_scraper.py`)
- `pdfplumber>=0.10` — PDF text/tables extraction primary (`rag/document_loader.py`)
- `beautifulsoup4` (implied by `bs4` import in `tools/web_scraper.py`) — HTML parsing

**Data:**
- `akshare>=1.14` — A-share market data API (`tools/akshare_data.py`)
- `pandas>=2.0` — data frame manipulation in AKShareTool

**Web Search:**
- `tavily-python>=0.3` — Tavily search API (`tools/web_search.py`)
- `duckduckgo-search>=6.0` — DuckDuckGo search fallback (`tools/web_search.py`)

**Report Generation:**
- `markdown>=3.5` — Markdown to HTML conversion for PDF
- `weasyprint>=60.0` — HTML to PDF conversion (`core/report_generator.py`)

**Language Detection:**
- `langdetect>=1.0` — language detection (RAG pipeline)

## Configuration

**Environment:**
- `.env` file loaded by Pydantic-Settings (`env_file=".env"` in `config/settings.py`)
- Environment variable expansion in YAML: `${VAR}` and `${VAR:-default}` patterns (`config/settings.py:_expand_env_vars`)
- Key env vars: `OPENAI_API_KEY`, `DASHSCOPE_API_KEY`, `TAVILY_API_KEY`

**Build:**
- `pyproject.toml` — single source of truth for dependencies, tool configs, and entry points
- `tool.pytest.ini_options` — testpaths: `financial_agent/tests`, asyncio_mode: `auto`
- `tool.black` / `tool.ruff` / `tool.mypy` — formatting, linting, type-checking configs

**Application Config:**
- `config/default.yaml` — default runtime configuration (LLM, embedding, RAG, agents)
- `config/qwen.yaml` — Qwen-specific template (copy to `custom.yaml` to use)
- `config/settings.py` — Pydantic-based settings classes with env var overrides

## Platform Requirements

**Development:**
- Python 3.10+
- Optional: CUDA for local embedding models (`device: auto` detects GPU)
- Optional: `HF_ENDPOINT` defaults to `https://hf-mirror.com` for China users (`tools/embedding_call.py`)

**Production:**
- Local deployment (no containerization config detected)
- ChromaDB persists to `./financial_agent/data/vector_db`
- BM25 index persists to `./financial_agent/data/bm25_index`
- Session data persists to `./financial_agent/data/sessions`
- Reports output to `./financial_agent/data/output`

## CLI Entry Points

**Registered scripts (from `pyproject.toml`):**
- `a-stock-analyzer` — `financial_agent.cli:main` (interactive or single-query mode)
- `ingest-reports` — `financial_agent.scripts.ingest_reports:main` (PDF ingestion)
- `run-evaluation` — `financial_agent.scripts.run_evaluation:main` (benchmark evaluation)

---

*Stack analysis: 2026-04-25*
