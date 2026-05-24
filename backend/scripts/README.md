# Scripts — 工具脚本使用指南

本目录包含开发、调试和评测用的独立脚本。所有脚本均为**零侵入设计**，不修改生产代码路径。

---

## 目录

| 脚本 | 用途 | 是否入库 Chroma |
|------|------|----------------|
| [`preview_chunks.py`](#preview_chunkspy) | 预览文档分块效果 | ❌ 不入库 |
| [`run_rag_eval.py`](#run_rag_evalpy) | 对已有 collection 运行 RAG 评测 | ✅ 只读 |
| [`run_rag_eval_local.py`](#run_rag_eval_localpy) | 本地 embedding 全流程评测 | ✅ 临时目录 |
| [`run_rag_eval_local_v2.py`](#run_rag_eval_local_v2py) | 本地 embedding + 自动发现相关 chunk | ✅ 临时目录 |
| [`run_rag_eval_local_hybrid.py`](#run_rag_eval_local_hybridpy) | 向量检索 vs 混合检索对比评测 | ✅ 临时目录 |
| [`build_alibaba_benchmark.py`](#build_alibaba_benchmarkpy) | 自动构建评测数据集草稿 | ✅ 临时目录 |
| [`build_alibaba_benchmark_final.py`](#build_alibaba_benchmark_finalpy) | 构建人工校验后的最终数据集 | ❌ 纯文本 |

---

## `preview_chunks.py`

**用途**：本地调试时预览 PDF/Word/文本的分块效果，不入库、不编码、零副作用。

```bash
uv run python scripts/preview_chunks.py -f ~/report.pdf --strategy recursive
```

**常用参数**：

| 参数 | 说明 | 示例 |
|------|------|------|
| `-f, --file` | 文件路径（必填） | `-f ~/report.pdf` |
| `--strategy` | 切分策略：`recursive` / `fixed` / `semantic` | `--strategy semantic` |
| `--chunk-size` | 目标 chunk 大小（字符数） | `--chunk-size 800` |
| `--chunk-overlap` | chunk 间重叠（字符数） | `--chunk-overlap 100` |
| `--compare` | 同时输出三种策略对比 | `--compare` |
| `--max-chunks` | 限制输出前 N 个 chunk | `--max-chunks 20` |
| `-o, --output` | 输出到 Markdown 文件（默认 stdout） | `-o report.md` |

**输出示例**：
```markdown
# Document Chunking Preview
**File:** `report.pdf`  
**Size:** 401,234 chars  
**Strategies tested:** recursive

======================================================================  STRATEGY: RECURSIVE  ======================================================================...

## Summary
| Metric | Value |
|--------|-------|
| Chunk count | 247 |
| Avg chunk size | 1,624 |
...

### Chunk 0
- **Chars**: 1,542
- **Lines**: 12

**Preview:**
```
阿里巴巴集團控股有限公司...
```
```

**注意**：此脚本不依赖 ChromaDB、不调用 Embedding 模型，仅使用 `document_loader` + `chunking` 两个模块。

---

## `run_rag_eval.py`

**用途**：对**已有**的 Chroma collection 运行 RAG 评测，输出 JSON + Markdown 报告。

```bash
uv run python scripts/run_rag_eval.py \
    --collection session_uploads_xxx \
    --dataset deep_research/evaluation/datasets/rag_benchmark.jsonl \
    --output ./eval_results/
```

**参数**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--collection` | Chroma collection 名称（必填） | — |
| `--dataset` | 评测数据集 JSONL 路径（必填） | — |
| `--output` | 报告输出目录 | `./eval_results` |
| `--top-k` | 检索 top_k | `10` |
| `--ks` | 指标计算的 k 值列表 | `1,3,5,10` |

**输出**：
- `rag_eval_YYYYMMDD_HHMMSS.json` — 结构化数据
- `rag_eval_YYYYMMDD_HHMMSS.md` — 人类可读报告

---

## `run_rag_eval_local.py`

**用途**：使用**本地 embedding 模型**（`BAAI/bge-large-zh-v1.5`）的完整评测流水线：加载 PDF → 切分 → 嵌入 → 入库 → 运行评测。

```bash
EMBEDDING_PROVIDER=local uv run python scripts/run_rag_eval_local.py
```

**流程**：
1. 加载指定 PDF 文件
2. 使用本地 embedding 模型编码并写入临时 Chroma collection
3. 读取评测数据集运行 benchmark
4. 输出 top_k=5 和 top_k=10 的对比结果

**默认路径**（硬编码）：
- PDF：`/mnt/c/Users/liqing/Desktop/阿里巴巴集團控股有限公司2025財務年度報告.pdf`
- 数据集：`deep_research/evaluation/datasets/alibaba_fy2025_benchmark.jsonl`
- 临时数据：`/tmp/alibaba_benchmark_local/`

---

## `run_rag_eval_local_v2.py`

**用途**：解决 `run_rag_eval_local.py` 的 chunk ID 漂移问题。每次重新入库会生成新的 doc_id，导致 benchmark 中标注的 chunk ID 失效。此脚本在入库后**自动从实际 chunk 文本中搜索关键词**，动态发现 relevant chunk IDs。

```bash
EMBEDDING_PROVIDER=local uv run python scripts/run_rag_eval_local_v2.py
```

**核心改进**：
```python
QUERY_SEARCH_TERMS = {
    "alibaba_001": ["996,347", "941,168", "總收入"],
    "alibaba_002": ["322,346", "客戶管理"],
    # ... 通过关键词匹配自动发现 chunk
}
```

**适用场景**：频繁调整 chunk_size / chunk_overlap / 切分策略 时，不需要手动更新 benchmark 中的 chunk ID。

---

## `run_rag_eval_local_hybrid.py`

**用途**：对比**纯向量检索** vs **混合检索**（BM25 + 向量 + RRF）的评测效果。

```bash
EMBEDDING_PROVIDER=local uv run python scripts/run_rag_eval_local_hybrid.py
```

**输出**：
```
======================================================================
Evaluating with VECTOR-ONLY retrieval
======================================================================
Avg MRR: 0.2345
  Precision@1: 0.2000
  Recall@1: 0.1500
...

======================================================================
Evaluating with HYBRID retrieval
======================================================================
Avg MRR: 0.4567
  Precision@1: 0.4000
  Recall@1: 0.3000
...
```

**评测报告保存位置**：
- `/tmp/alibaba_benchmark_local_v2/reports_vector-only/`
- `/tmp/alibaba_benchmark_local_v2/reports_hybrid/`

---

## `build_alibaba_benchmark.py`

**用途**：**自动构建评测数据集草稿**。使用 FakeEmbedding（哈希-based 确定性向量）快速入库，对候选 query 运行检索，自动填充 `relevant_chunk_ids`（作为人工审核的起点）。

```bash
uv run python scripts/build_alibaba_benchmark.py
```

**输出**：
- `deep_research/evaluation/datasets/alibaba_fy2025_benchmark_draft.jsonl`
- `/tmp/alibaba_benchmark/chunks_inspection.json` — chunk 文本检查文件

⚠️ **重要**：此脚本生成的 `relevance_scores` 和 `relevant_chunk_ids` 来自自动检索结果，**必须经过人工审核和调整**才能成为可靠的 benchmark。

**FakeEmbedding 原理**：
```python
# 基于文本 MD5 哈希生成确定性 one-hot 向量（512 维）
# 同一文本始终得到相同向量，不同文本大概率正交
# 仅用于快速构建 benchmark，不具备真实语义能力
```

---

## `build_alibaba_benchmark_final.py`

**用途**：构建**人工校验后的最终评测数据集**。所有 `relevant_chunk_ids` 和 `relevance_scores` 均为手动验证，不依赖自动检索。

```bash
uv run python scripts/build_alibaba_benchmark_final.py
```

**输出**：
- `deep_research/evaluation/datasets/alibaba_fy2025_benchmark.jsonl`

**数据集覆盖**：

| query_id | 类型 | 说明 |
|----------|------|------|
| alibaba_001-002, 004, 007 | exact_fact | 精确事实查询（收入、利润等） |
| alibaba_003, 008 | multi_condition | 多条件查询（业务+市场） |
| alibaba_005 | semantic | 语义近义查询（用词不同） |
| alibaba_006, 009 | comprehensive | 长文档综合查询（跨 chunk） |
| alibaba_010 | negative | 负例/无关查询 |

**relevance_scores**：
- `2` = 直接回答查询
- `1` = 部分相关
- `0` = 不相关

---

## 快速参考

```bash
# 1. 调试分块效果
uv run python scripts/preview_chunks.py -f doc.pdf --compare

# 2. 构建评测数据集（自动草稿 → 人工审核 → 最终版）
uv run python scripts/build_alibaba_benchmark.py          # 生成草稿
# ... 人工审核 chunks_inspection.json ...
uv run python scripts/build_alibaba_benchmark_final.py    # 生成最终版

# 3. 运行评测（本地 embedding + hybrid 对比）
EMBEDDING_PROVIDER=local uv run python scripts/run_rag_eval_local_hybrid.py

# 4. 对已有 collection 评测
uv run python scripts/run_rag_eval.py \
    --collection session_uploads_xxx \
    --dataset deep_research/evaluation/datasets/alibaba_fy2025_benchmark.jsonl
```
