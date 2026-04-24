# External Integrations

**Analysis Date:** 2026-04-25

## APIs & External Services

**LLM Providers (OpenAI-compatible API):**
- Primary: Alibaba DashScope (通义千问 / Qwen)
  - Config: `llm.base_url = https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
  - Model: `qwen-plus` (default), options: `qwen-turbo`, `qwen-max`
  - Auth: `OPENAI_API_KEY` or `DASHSCOPE_API_KEY` env var
  - File: `config/default.yaml`, `config/qwen.yaml`
- Supported alternatives (same OpenAI-compatible format):
  - DeepSeek (`https://api.deepseek.com/v1`) — models: `deepseek-chat`, `deepseek-reasoner`
  - Moonshot / Kimi (`https://api.moonshot.cn/v1`) — models: `moonshot-v1-8k`, etc.
  - Zhipu AI (`https://open.bigmodel.cn/api/paas/v4`) — models: `glm-4`, `glm-4-plus`
  - Baidu Qianfan (`https://qianfan.baidubce.com/v2`) — models: `ernie-4.0`, `ernie-3.5`
  - OpenAI (`https://api.openai.com/v1`) — models: `gpt-4o`, `gpt-4o-mini`
  - Local via vLLM / Ollama (`http://localhost:8000/v1`)
- Client implementation: `core/agent.py:LLMClient` — unified async HTTP client with provider-specific response normalization

**Embedding Providers:**
- Local (default): `sentence-transformers` with `BAAI/bge-large-zh-v1.5` on CPU/CUDA
- OpenAI-compatible APIs: DashScope (`text-embedding-v1`), Zhipu (`embedding-3`), Baidu (`embedding-v1`)
- Config: `embedding.provider` = `local` or `openai`
- File: `tools/embedding_call.py`

**Web Search:**
- Tavily (primary)
  - SDK: `tavily-python>=0.3`
  - Auth: `TAVILY_API_KEY` env var
  - Features: `search_depth=advanced`, `include_answer=True`, `include_raw_content=True`
  - File: `tools/web_search.py`
- DuckDuckGo (fallback)
  - SDK: `duckduckgo-search>=6.0`
  - No API key required
  - Used when Tavily fails or provider is explicitly set to `duckduckgo`
  - File: `tools/web_search.py`

**A-Share Market Data:**
- AKShare (`akshare>=1.14`)
  - No API key required
  - Data types: `stock_spot`, `industry_board`, `stock_financial`, `stock_news`, `market_sentiment`, `stock_list`, `industry_stocks`
  - Sync pandas calls wrapped in `asyncio.to_thread()` for async compatibility
  - File: `tools/akshare_data.py`

## Data Storage

**Databases:**
- ChromaDB — local persistent vector database
  - Path: `./financial_agent/data/vector_db`
  - Collection: `financial_reports`
  - Distance function: cosine (configurable: `cosine`, `l2`, `ip`)
  - Client: `chromadb.PersistentClient`
  - File: `rag/vector_store.py`

**File Storage:**
- Local filesystem only
- Session storage: `./financial_agent/data/sessions/{session_id}.json` + `.md`
- BM25 index: `./financial_agent/data/bm25_index` (pickle file)
- User preferences: `./financial_agent/data/user_preferences.json`
- Report output: `./financial_agent/data/output/report_{session_id}_{timestamp}.md` + `.pdf`
- PDF ingestion source: user-provided paths

**Caching:**
- None detected (no Redis, Memcached, or disk cache layer)
- Embedding model singleton cached in module-level variable (`tools/embedding_call.py:_local_model_singleton`)

## Authentication & Identity

**Auth Provider:**
- None — no user authentication system
- Sessions identified by `session_id` (auto-generated: `sess_YYYYMMDD_HHMMSS_{hex}`)
- User ID defaults to `"anonymous"`
- File: `memory/session_store.py`, `memory/manager.py`

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry, Rollbar, or similar service

**Logs:**
- Python standard `logging` module
- Configurable format: `json` or `console` (`config/settings.py:LoggingConfig`)
- Log level: `INFO` by default (performance observation phase)
- Structured log fields include latency, token counts, tool call counts (`core/agent.py`)

## CI/CD & Deployment

**Hosting:**
- Not detected — no Dockerfile, docker-compose, or cloud deployment configs

**CI Pipeline:**
- Not detected — no GitHub Actions, GitLab CI, or similar configs

## Environment Configuration

**Required env vars:**
- `OPENAI_API_KEY` or `DASHSCOPE_API_KEY` — LLM API access
- `TAVILY_API_KEY` — Tavily web search (optional if using DuckDuckGo)
- `HF_ENDPOINT` — optional, defaults to `https://hf-mirror.com` for HuggingFace model downloads

**Secrets location:**
- `.env` file (loaded by Pydantic-Settings, noted in `.gitignore` but not read here)
- Environment variables referenced in YAML via `${VAR}` syntax

## Webhooks & Callbacks

**Incoming:**
- None — no webhook endpoints or HTTP server

**Outgoing:**
- None — no outgoing webhooks
- All external communication is via client-initiated HTTP requests

## VLM (Vision Language Model)

**Provider:**
- Configurable via `vlm.enabled` (default: `false`)
- Supports Qwen-VL (`qwen-vl-max`) for chart understanding in PDFs
- File: `rag/multimodal/pdf_extractor.py` (multimodal PDF ingestion)

---

*Integration audit: 2026-04-25*
