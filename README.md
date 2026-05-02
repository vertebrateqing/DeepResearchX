# DeepResearchX

**English** | [中文](#中文)

A production-grade multi-agent deep research system that generates comprehensive, structured reports on any topic. Built on a Planner-Worker-Synthesizer (PWS) architecture with real-time streaming, human-in-the-loop clarification, and automated quality review.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          DeepResearchX                                  │
│                                                                         │
│  User Query                                                             │
│      │                                                                  │
│      ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    OrchestratorAgent                            │    │
│  │                                                                 │    │
│  │  Phase 0: Intent Clarification (LLM-driven, ≤2 rounds)         │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  IntentClarifier  →  Enrich Query / Ask 1 Question       │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  Phase 1: Outline Planning                                      │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  OutlinePlanner  →  ReportOutline (chapters + deps DAG)  │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  Phase 2: Parallel Chapter Research (topological order)         │    │
│  │  ┌─────────────────────────────────────────────────────────┐   │    │
│  │  │  ChapterWorker C1 ──┐                                   │   │    │
│  │  │  ChapterWorker C2 ──┤── asyncio.gather (parallel)       │   │    │
│  │  │  ChapterWorker C3 ──┘                                   │   │    │
│  │  │       │                                                  │   │    │
│  │  │  Each worker: WebSearch + WebScraper → LLM draft        │   │    │
│  │  └─────────────────────────────────────────────────────────┘   │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  Phase 3: Quality Review & Revision Loop (≤2 rounds/chapter)   │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  ReviserAgent  →  Score (5 dims)  →  Feedback → Revise  │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  Phase 4a: Integration                                          │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  IntegrationAgent  →  Merge + Transitions + Summary      │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  Phase 4b: Editing                                              │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  EditorAgent  →  Polish + Fact-check + Completeness      │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  └──────────────────────────┼──────────────────────────────────────┘    │
│                             ▼                                           │
│                    Final Report (Markdown / PDF)                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────┐
                    │         Tool Layer           │
                    │  ┌──────────┐ ┌───────────┐ │
                    │  │  Tavily  │ │  Web      │ │
                    │  │  Search  │ │  Scraper  │ │
                    │  └──────────┘ └───────────┘ │
                    │  BM25 + Vector Hybrid Rank   │
                    └─────────────────────────────┘

                    ┌─────────────────────────────┐
                    │        Delivery Layer        │
                    │  FastAPI + SSE Streaming     │
                    │  React Frontend              │
                    └─────────────────────────────┘
```

---

## Features

- **Multi-Agent Pipeline**: Structured 5-phase pipeline — clarification → outline → parallel research → review → integration → editing
- **Parallel Chapter Execution**: Chapters with no dependencies run concurrently; dependent chapters execute in topological order
- **Quality Review Loop**: Per-chapter automated scoring across 5 dimensions with feedback-driven revision (≤2 rounds)
- **Real-Time Streaming**: SSE-based progress streaming — every phase update, tool call, and partial content delivered to the frontend
- **LLM-Driven Query Enrichment**: Intent clarification uses a single LLM call to produce an enriched research prompt (filling in time range, scope, dimensions). The enriched prompt is shown to the user as an editable card — confirm as-is or refine before research begins
- **Hybrid Retrieval**: BM25 + vector cosine similarity with RRF fusion for web-scraped content ranking
- **Any-Domain Research**: General-purpose prompts; not limited to any specific domain
- **Benchmark Evaluation**: Built-in RACE metric evaluation via `deep_research_bench` submodule

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend Framework | FastAPI + uvicorn (async) |
| LLM | OpenAI-compatible API (Qwen, DeepSeek, GPT-4o, GLM, Kimi…) |
| Embedding | BAAI/bge-large-zh-v1.5 (local) |
| Vector Store | ChromaDB |
| Web Search | Tavily / DuckDuckGo |
| Hybrid Retrieval | BM25 (rank-bm25) + cosine similarity + RRF |
| Streaming | SSE (sse-starlette) |
| Frontend | React 19 + TypeScript + Vite + Tailwind CSS |
| Containerization | Docker + Docker Compose |

---

## Project Structure

```
DeepResearchX/
├── backend/
│   ├── main.py                          # FastAPI entry point
│   ├── api/
│   │   ├── router.py                    # REST endpoints
│   │   ├── models.py                    # Pydantic request/response models
│   │   └── streaming.py                 # SSE streaming service
│   └── deep_research/
│       ├── config/
│       │   ├── default.yaml             # LLM, RAG, tools configuration
│       │   └── settings.py              # Pydantic-Settings loader
│       ├── core/
│       │   ├── orchestrator.py          # Main pipeline orchestrator
│       │   ├── outline_planner.py       # Phase 1: report structure
│       │   ├── chapter_worker.py        # Phase 2: per-chapter research
│       │   ├── reviser.py               # Phase 3: quality review
│       │   ├── integration.py           # Phase 4a: chapter merging
│       │   ├── editor.py                # Phase 4b: final polish
│       │   ├── intent_clarifier.py      # Pre-phase: HITL clarification
│       │   └── agent.py                 # LLMClient + ReActAgent base
│       ├── tools/
│       │   ├── web_search.py            # Tavily / DuckDuckGo
│       │   ├── web_scraper.py           # Scrape + hybrid chunk ranking
│       │   └── llm_call.py              # Direct LLM tool
│       └── rag/                         # ChromaDB vector retrieval
├── frontend/
│   └── src/
│       ├── App.tsx                      # Multi-turn chat UI
│       ├── components/
│       │   ├── AnalysisProgress.tsx     # Real-time phase progress
│       │   └── SourceCards.tsx          # Reference source display
│       └── services/api.ts              # SSE client
├── deep_research_bench/                 # Evaluation submodule (RACE metrics)
├── run_drx_bench.py                     # Benchmark generation runner
├── eval.sh                              # End-to-end evaluation script
├── dev-start.sh                         # One-command dev startup
└── docker-compose.yml
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- An OpenAI-compatible LLM API key
- (Optional) Tavily API key for web search

### One-Command Setup

```bash
git clone --recurse-submodules https://github.com/your-org/DeepResearchX.git
cd DeepResearchX
./dev-start.sh
```

The script checks dependencies, installs packages, and starts both backend (`:8000`) and frontend (`:5173`).

```bash
./dev-stop.sh   # stop all services
```

### Manual Setup

**Backend:**

```bash
cd backend
python3.10 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# Create .env
cat > .env << EOF
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
LLM_MODEL=qwen-plus
TAVILY_API_KEY=tvly-your-key   # optional
EOF

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

### Docker Compose

```bash
docker-compose up --build
```

---

## Configuration

Edit `backend/deep_research/config/default.yaml` or override via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_API_KEY` | LLM provider API key | (required) |
| `LLM_BASE_URL` | Full chat completions endpoint | Qwen DashScope |
| `LLM_MODEL` | Model name | `qwen-plus` |
| `TAVILY_API_KEY` | Tavily web search key | (optional) |

**Supported LLM providers** (any OpenAI-compatible endpoint):

| Provider | Example models |
|----------|---------------|
| Alibaba Qwen | `qwen-plus`, `qwen-max`, `qwen-turbo` |
| DeepSeek | `deepseek-chat`, `deepseek-reasoner` |
| OpenAI | `gpt-4o`, `gpt-4o-mini` |
| Moonshot (Kimi) | `moonshot-v1-128k` |
| Zhipu GLM | `glm-4`, `glm-4-plus` |
| Local (vLLM/Ollama) | any compatible model |

---

## API

### `GET /api/analyze/stream`

Main SSE streaming endpoint.

```
Query parameters:
  query                string   (required) Research question
  model                string   (optional) Override default model
  session_id           string   (optional) Resume existing session
  skip_clarification   bool     (default: false) Skip HITL for batch/eval mode
```

**SSE event types:**

| Event | Payload |
|-------|---------|
| `connected` | `{task_id}` |
| `status` | `{message, phase}` |
| `progress` | `{percent}` |
| `thinking` | LLM reasoning step |
| `tool_call` | Tool name + arguments |
| `tool_result` | Tool output |
| `chapter` | Per-chapter update |
| `content` | Accumulated Markdown report |
| `sources` | Extracted references |
| `complete` | Final report |
| `error` | Error message |

### `POST /api/analyze`

Create analysis task (polling mode).

### `GET /api/analyze/{task_id}`

Poll task status.

Swagger UI available at `http://localhost:8000/docs`.

---

## Observability (Langfuse)

DeepResearchX integrates [Langfuse](https://langfuse.com) for full observability: every LLM call, web search, pipeline phase, and tool invocation is traced.

### What is tracked

| Span type | Name | Content |
|-----------|------|---------|
| `agent` | `deepresearch` | Root trace — full request input/output |
| `generation` | `llm_call` | Full prompt messages, response text, token counts, latency |
| `span` | `outline_planning` | Enriched query in, chapter list out, latency |
| `span` | `chapter_execution` | Chapter count, pass rate, latency |
| `span` | `web_search` | Query, provider, retrieved URLs, top-k chunks with text |
| `span` | `integration` | Latency |
| `span` | `editorial_review` | Latency |

### Self-hosted Langfuse server

Start a local Langfuse v2 server (PostgreSQL required):

```bash
# Start PostgreSQL (one-time)
/opt/homebrew/opt/postgresql@15/bin/pg_ctl -D ~/.langfuse-postgres start

# Run DB migrations (one-time)
cd ~/.langfuse-server/web
DATABASE_URL="postgresql://$(whoami)@localhost:5433/langfuse" \
  node node_modules/.bin/prisma migrate deploy

# Start Langfuse server
DATABASE_URL="postgresql://$(whoami)@localhost:5433/langfuse" \
NEXTAUTH_SECRET="your-secret" SALT="your-salt" \
NEXTAUTH_URL="http://localhost:3000" \
  node node_modules/.bin/next dev -p 3000
```

Then register at `http://localhost:3000` and create a project to obtain `public_key` / `secret_key`.

Add to `backend/.env`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
```

### Startup modes

```bash
# Normal mode — no tracing (default)
./dev-start.sh

# Production tracing — all LLM calls and spans recorded, no dataset
./dev-start.sh --trace

# Dataset recording — tracing + write to Langfuse Dataset (default 10 items max)
./dev-start.sh --record
./dev-start.sh --record 50   # custom cap
```

All tracing config is deployment-level, controlled via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `LANGFUSE_ENABLED` | Enable tracing | `false` |
| `LANGFUSE_PUBLIC_KEY` | Project public key | — |
| `LANGFUSE_SECRET_KEY` | Project secret key | — |
| `LANGFUSE_HOST` | Langfuse server URL | `http://localhost:3000` |
| `LANGFUSE_RECORD_DATASET` | Write completed runs to Dataset | `false` |
| `LANGFUSE_DATASET_MAX_ITEMS` | Max dataset items per run | `1` |

---

## Evaluation

DeepResearchX includes a benchmark evaluation pipeline using RACE metrics.

```bash
# Generate reports for all benchmark queries (runs backend)
python run_drx_bench.py

# Run specific query IDs
python run_drx_bench.py --ids 1,5,10

# Full pipeline: generate → validate → evaluate
./eval.sh

# Single query end-to-end
./eval.sh 8
```

Results are written to `deep_research_bench/results/race/DeepResearchX/race_result.txt`.

---

## License

MIT

---

---

# 中文

**[English](#deepresearchx)** | 中文

DeepResearchX 是一个生产级多智能体深度研究系统，能够针对任意主题自动生成结构化、有深度的分析报告。基于规划-工作-综合（PWS）架构，支持实时流式输出、人机协作澄清和自动质量审查。

---

## 架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          DeepResearchX                                  │
│                                                                         │
│  用户输入查询                                                            │
│      │                                                                  │
│      ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    OrchestratorAgent（主编排器）                  │    │
│  │                                                                 │    │
│  │  阶段 0：意图澄清（LLM 驱动，最多 2 轮）                          │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  IntentClarifier → 直接增强查询 / 提一个关键问题          │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  阶段 1：大纲规划                                               │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  OutlinePlanner → ReportOutline（章节 + 依赖 DAG）        │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  阶段 2：并行章节研究（拓扑排序执行）                            │    │
│  │  ┌─────────────────────────────────────────────────────────┐   │    │
│  │  │  ChapterWorker C1 ──┐                                   │   │    │
│  │  │  ChapterWorker C2 ──┤── asyncio.gather（并行）          │   │    │
│  │  │  ChapterWorker C3 ──┘                                   │   │    │
│  │  │       │                                                  │   │    │
│  │  │  每个 Worker：网络搜索 + 网页抓取 → LLM 生成章节草稿      │   │    │
│  │  └─────────────────────────────────────────────────────────┘   │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  阶段 3：质量审查与修订循环（每章最多 2 轮）                     │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  ReviserAgent → 五维评分 → 反馈 → 修订                   │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  阶段 4a：整合                                                  │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  IntegrationAgent → 合并章节 + 过渡段落 + 执行摘要        │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  │                          ▼                                      │    │
│  │  阶段 4b：编辑润色                                              │    │
│  │  ┌──────────────────────────────────────────────────────────┐  │    │
│  │  │  EditorAgent → 语言润色 + 事实核查 + 完整性检查           │  │    │
│  │  └──────────────────────────────────────────────────────────┘  │    │
│  │                          │                                      │    │
│  └──────────────────────────┼──────────────────────────────────────┘    │
│                             ▼                                           │
│                    最终报告（Markdown / PDF）                            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────┐
                    │          工具层              │
                    │  ┌──────────┐ ┌───────────┐ │
                    │  │  Tavily  │ │  网页     │ │
                    │  │  搜索    │ │  抓取器   │ │
                    │  └──────────┘ └───────────┘ │
                    │  BM25 + 向量混合排序（RRF）   │
                    └─────────────────────────────┘

                    ┌─────────────────────────────┐
                    │          交付层              │
                    │  FastAPI + SSE 流式传输       │
                    │  React 前端界面              │
                    └─────────────────────────────┘
```

---

## 功能特性

- **多智能体流水线**：五阶段结构化流水线——意图澄清 → 大纲规划 → 并行研究 → 质量审查 → 整合编辑
- **并行章节执行**：无依赖的章节并发执行，有依赖的章节按拓扑顺序执行
- **质量审查循环**：每章自动评分（5个维度），基于反馈驱动修订（最多2轮）
- **实时流式输出**：基于 SSE 的进度流——每个阶段更新、工具调用和部分内容实时推送到前端
- **LLM 驱动的查询增强**：意图澄清模块通过单次 LLM 调用生成增强版研究提示词（自动补全时间范围、研究深度、分析维度），以可编辑卡片形式展示给用户，用户确认或修改后直接开始研究
- **混合检索**：BM25 + 向量余弦相似度 + RRF 融合排序，用于网页抓取内容排名
- **通用领域研究**：通用提示词设计，不限于特定领域
- **基准评测**：内置 RACE 指标评测，通过 `deep_research_bench` 子模块实现

---

## 技术栈

| 层次 | 技术选型 |
|------|---------|
| 后端框架 | FastAPI + uvicorn（异步） |
| 大语言模型 | OpenAI 兼容 API（通义千问、DeepSeek、GPT-4o、GLM、Kimi…） |
| 向量嵌入 | BAAI/bge-large-zh-v1.5（本地） |
| 向量数据库 | ChromaDB |
| 网络搜索 | Tavily / DuckDuckGo |
| 混合检索 | BM25 (rank-bm25) + 余弦相似度 + RRF |
| 流式传输 | SSE (sse-starlette) |
| 前端 | React 19 + TypeScript + Vite + Tailwind CSS |
| 容器化 | Docker + Docker Compose |

---

## 项目结构

```
DeepResearchX/
├── backend/
│   ├── main.py                          # FastAPI 入口
│   ├── api/
│   │   ├── router.py                    # REST 接口定义
│   │   ├── models.py                    # Pydantic 数据模型
│   │   └── streaming.py                 # SSE 流式服务
│   └── deep_research/
│       ├── config/
│       │   ├── default.yaml             # LLM、RAG、工具配置
│       │   └── settings.py              # Pydantic-Settings 加载器
│       ├── core/
│       │   ├── orchestrator.py          # 主流水线编排器
│       │   ├── outline_planner.py       # 阶段1：报告结构规划
│       │   ├── chapter_worker.py        # 阶段2：章节研究与撰写
│       │   ├── reviser.py               # 阶段3：质量审查
│       │   ├── integration.py           # 阶段4a：章节整合
│       │   ├── editor.py                # 阶段4b：最终润色
│       │   ├── intent_clarifier.py      # 前置阶段：HITL 澄清
│       │   └── agent.py                 # LLMClient + ReActAgent 基类
│       ├── tools/
│       │   ├── web_search.py            # Tavily / DuckDuckGo
│       │   ├── web_scraper.py           # 网页抓取 + 混合排序
│       │   └── llm_call.py              # 直接 LLM 调用工具
│       └── rag/                         # ChromaDB 向量检索
├── frontend/
│   └── src/
│       ├── App.tsx                      # 多轮对话 UI
│       ├── components/
│       │   ├── AnalysisProgress.tsx     # 实时阶段进度
│       │   └── SourceCards.tsx          # 参考来源展示
│       └── services/api.ts              # SSE 客户端
├── deep_research_bench/                 # 评测子模块（RACE 指标）
├── run_drx_bench.py                     # 基准测试生成脚本
├── eval.sh                              # 端到端评测脚本
├── dev-start.sh                         # 一键开发环境启动
└── docker-compose.yml
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- OpenAI 兼容 LLM API Key
- （可选）Tavily API Key（用于网络搜索）

### 一键启动

```bash
git clone --recurse-submodules https://github.com/your-org/DeepResearchX.git
cd DeepResearchX
./dev-start.sh
```

脚本会自动检查依赖、安装包，并启动后端（`:8000`）和前端（`:5173`）。

```bash
./dev-stop.sh   # 停止所有服务
```

### 手动启动

**后端：**

```bash
cd backend
python3.10 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# 创建 .env 文件
cat > .env << EOF
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
LLM_MODEL=qwen-plus
TAVILY_API_KEY=tvly-your-key   # 可选
EOF

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**前端：**

```bash
cd frontend
npm install
npm run dev
```

打开浏览器访问 `http://localhost:5173`。

### Docker Compose

```bash
docker-compose up --build
```

---

## 配置说明

编辑 `backend/deep_research/config/default.yaml` 或通过环境变量覆盖：

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LLM_API_KEY` | LLM 提供商 API Key | （必填） |
| `LLM_BASE_URL` | 完整的 chat completions 接口地址 | 通义千问 DashScope |
| `LLM_MODEL` | 模型名称 | `qwen-plus` |
| `TAVILY_API_KEY` | Tavily 搜索 API Key | （可选） |

**支持的 LLM 提供商**（任何 OpenAI 兼容接口）：

| 提供商 | 示例模型 |
|--------|---------|
| 阿里通义千问 | `qwen-plus`、`qwen-max`、`qwen-turbo` |
| DeepSeek | `deepseek-chat`、`deepseek-reasoner` |
| OpenAI | `gpt-4o`、`gpt-4o-mini` |
| 月之暗面 Kimi | `moonshot-v1-128k` |
| 智谱 GLM | `glm-4`、`glm-4-plus` |
| 本地模型 (vLLM/Ollama) | 任意兼容模型 |

---

## API 接口

### `GET /api/analyze/stream`

主要的 SSE 流式分析接口。

```
查询参数：
  query                string   （必填）研究问题
  model                string   （可选）覆盖默认模型
  session_id           string   （可选）恢复已有会话
  skip_clarification   bool     （默认 false）批量/评测模式跳过 HITL
```

**SSE 事件类型：**

| 事件 | 说明 |
|------|------|
| `connected` | 连接建立，返回 `task_id` |
| `status` | 阶段状态更新 |
| `progress` | 进度百分比 |
| `thinking` | LLM 推理步骤 |
| `tool_call` | 工具调用详情 |
| `tool_result` | 工具返回结果 |
| `chapter` | 章节更新 |
| `content` | 累积的 Markdown 报告内容 |
| `sources` | 提取的参考来源 |
| `complete` | 最终报告完成 |
| `error` | 错误信息 |

Swagger UI：`http://localhost:8000/docs`

---

## 可观测性（Langfuse）

DeepResearchX 集成了 [Langfuse](https://langfuse.com) 完整可观测性：每次 LLM 调用、网络搜索、流水线阶段和工具调用都会被追踪。

### 追踪内容

| Span 类型 | 名称 | 内容 |
|-----------|------|------|
| `agent` | `deepresearch` | 根 trace — 完整请求输入/输出 |
| `generation` | `llm_call` | 完整 prompt 消息、回答文本、token 数、耗时 |
| `span` | `outline_planning` | 增强查询输入、章节列表输出、耗时 |
| `span` | `chapter_execution` | 章节数、通过率、耗时 |
| `span` | `web_search` | 查询词、提供商、检索 URL 列表、top-k chunk 文本 |
| `span` | `integration` | 耗时 |
| `span` | `editorial_review` | 耗时 |

### 本地部署 Langfuse 服务

启动本地 Langfuse v2 服务（需要 PostgreSQL）：

```bash
# 启动 PostgreSQL（首次）
/opt/homebrew/opt/postgresql@15/bin/pg_ctl -D ~/.langfuse-postgres start

# 执行数据库迁移（首次）
cd ~/.langfuse-server/web
DATABASE_URL="postgresql://$(whoami)@localhost:5433/langfuse" \
  node node_modules/.bin/prisma migrate deploy

# 启动 Langfuse 服务
DATABASE_URL="postgresql://$(whoami)@localhost:5433/langfuse" \
NEXTAUTH_SECRET="your-secret" SALT="your-salt" \
NEXTAUTH_URL="http://localhost:3000" \
  node node_modules/.bin/next dev -p 3000
```

访问 `http://localhost:3000` 注册账号并创建项目，获取 `public_key` / `secret_key`。

在 `backend/.env` 中添加：

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
```

### 启动模式

```bash
# 普通模式 — 不启用追踪（默认）
./dev-start.sh

# 生产追踪模式 — 追踪所有 LLM 调用和阶段，不录制 dataset
./dev-start.sh --trace

# 录制测试集模式 — 追踪 + 写入 Langfuse Dataset（默认最多 10 条）
./dev-start.sh --record
./dev-start.sh --record 50   # 自定义上限
```

所有追踪配置均为部署层面配置，通过环境变量控制：

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LANGFUSE_ENABLED` | 是否启用追踪 | `false` |
| `LANGFUSE_PUBLIC_KEY` | 项目公钥 | — |
| `LANGFUSE_SECRET_KEY` | 项目私钥 | — |
| `LANGFUSE_HOST` | Langfuse 服务地址 | `http://localhost:3000` |
| `LANGFUSE_RECORD_DATASET` | 是否将研究结果录入 Dataset | `false` |
| `LANGFUSE_DATASET_MAX_ITEMS` | 每次运行最多录入条目数 | `1` |

---

## 基准评测

DeepResearchX 内置基准评测流水线，使用 RACE 指标。

```bash
# 对所有基准查询生成报告（需要后端运行中）
python run_drx_bench.py

# 指定查询 ID
python run_drx_bench.py --ids 1,5,10

# 完整流水线：生成 → 验证 → 评测
./eval.sh

# 单条查询端到端测试
./eval.sh 8
```

评测结果保存至 `deep_research_bench/results/race/DeepResearchX/race_result.txt`。

---

## License

MIT
