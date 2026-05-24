# Evaluation — RAG 评测框架

本模块提供完整的 RAG（Retrieval-Augmented Generation）检索质量评测能力，与生产代码零耦合，可独立使用。

---

## 架构概览

```
evaluation/
├── models.py          # Pydantic 数据模型
├── metrics.py         # 指标计算（Precision@k, Recall@k, MRR, NDCG）
├── rag_evaluator.py   # 评测执行器
├── reporter.py        # 报告生成器（JSON + Markdown）
├── chunking_metrics.py    # 切分质量指标
├── index_health.py        # 索引健康检查
└── datasets/
    ├── alibaba_fy2025_benchmark.jsonl       # 最终版评测数据集
    └── alibaba_fy2025_benchmark_draft.jsonl # 草稿数据集（需人工审核）
```

---

## 数据模型

### `RAGTestCase` — 单条评测用例

```python
class RAGTestCase(BaseModel):
    query_id: str              # 唯一标识
    query: str                 # 查询文本
    collection_name: str       # 所属 collection
    relevant_doc_ids: list[str]        # 相关文档 ID
    relevant_chunk_ids: list[str]      # 相关 chunk ID
    relevance_scores: dict[str, int]   # chunk 级别相关度 {chunk_id: score}
    category: str              # 查询类别
    expected_answer: str       # 期望答案（参考）
```

### `RAGBenchmarkReport` — 评测报告

```python
class RAGBenchmarkReport(BaseModel):
    total_queries: int
    avg_precision_at_k: dict[int, float]
    avg_recall_at_k: dict[int, float]
    avg_mrr: float
    avg_ndcg_at_k: dict[int, float]
    avg_latency_ms: float
    avg_source_diversity: float
    per_category: dict          # 按类别聚合统计
    failures: list[dict]        # zero_recall 的失败查询
    per_query_results: list[QueryDetail]   # 逐查询详情
```

---

## 评测指标

### Precision@k

前 k 个检索结果中相关结果的比例：

```
Precision@k = |{相关 chunk} ∩ {前 k 个检索结果}| / k
```

### Recall@k

前 k 个检索结果覆盖了多少相关 chunk：

```
Recall@k = |{相关 chunk} ∩ {前 k 个检索结果}| / |{相关 chunk}|
```

### MRR (Mean Reciprocal Rank)

第一个相关结果的倒数排名：

```
MRR = 1/rank_of_first_relevant
```

如果前 k 个中没有相关结果，MRR = 0。

### NDCG@k (Normalized Discounted Cumulative Gain)

考虑相关度等级的排序指标。相关度 score 越高、排名越靠前，NDCG 越高：

```
DCG@k = Σ relevance_score_i / log2(i + 1)
NDCG@k = DCG@k / IDCG@k
```

---

## 使用方式

### 方式一：通过脚本（推荐）

```bash
# 对已有 collection 评测
cd backend
uv run python scripts/run_rag_eval.py \
    --collection session_uploads_xxx \
    --dataset deep_research/evaluation/datasets/alibaba_fy2025_benchmark.jsonl \
    --output ./eval_results/
```

### 方式二：程序化调用

```python
from deep_research.evaluation.rag_evaluator import RAGEvaluator
from deep_research.evaluation.reporter import EvaluationReporter
from deep_research.rag.pipeline import RAGPipeline

pipeline = RAGPipeline(collection_name="my_collection")
evaluator = RAGEvaluator(
    pipeline=pipeline,
    benchmark_path="deep_research/evaluation/datasets/alibaba_fy2025_benchmark.jsonl"
)

# hybrid=True: BM25 + 向量 + RRF
# hybrid=False: 纯向量检索
report = await evaluator.run(top_k=10, ks=[1, 3, 5, 10], hybrid=True)

# 保存报告
reporter = EvaluationReporter(report)
json_path, md_path = reporter.save("./eval_results")
```

### 方式三：对比 vector-only vs hybrid

```bash
EMBEDDING_PROVIDER=local uv run python scripts/run_rag_eval_local_hybrid.py
```

---

## 评测数据集格式

JSONL 格式，每行一个 `RAGTestCase`：

```json
{
  "query_id": "alibaba_001",
  "query": "阿里巴巴2025財年的總收入是多少",
  "collection_name": "alibaba_fy2025_benchmark",
  "relevant_doc_ids": ["f3ab57593d974f06933030f3ef62aae3"],
  "relevant_chunk_ids": [
    "f3ab57593d974f06933030f3ef62aae3__chunk__225",
    "f3ab57593d974f06933030f3ef62aae3__chunk__171"
  ],
  "relevance_scores": {
    "f3ab57593d974f06933030f3ef62aae3__chunk__225": 2,
    "f3ab57593d974f06933030f3ef62aae3__chunk__171": 2
  },
  "category": "exact_fact",
  "expected_answer": "人民幣996,347百萬元"
}
```

**relevance_scores**：
- `2` = 直接回答
- `1` = 部分相关
- `0` = 不相关

---

## 报告输出示例

### Markdown 报告结构

```markdown
# RAG Evaluation Report

## Overall Metrics
### Precision@k
- P@1: 0.4000
- P@3: 0.2667
...

### Recall@k
- R@1: 0.1500
...

### Other Metrics
- MRR: 0.4567
- Avg Latency: 245.67 ms

## Per-Category Breakdown
### exact_fact
- count: 4, avg_mrr: 0.5234, recall@1: 0.2500

## Per-Query Details
### alibaba_001 [OK]
**Expected Answer:** 人民幣996,347百萬元
**Metrics:** MRR: 0.5000 | Latency: 123.45ms | Retrieved: 10

**Relevant Chunks (3):**
- `...__chunk__225` (score=2, index=225, size=1542)
  > 预览文本...

**Retrieved Chunks (top 5):**
1. `...__chunk__225` [RELEVANT]
   > 预览文本...
2. `...__chunk__999`
   > 预览文本...
```

---

## 扩展：添加新的评测数据集

1. **准备文档**：将 PDF/Word/文本导入 Chroma collection
2. **构建 query**：基于文档内容设计查询，覆盖不同场景
3. **标注 relevant chunks**：人工判定哪些 chunk 能回答查询
4. **写入 JSONL**：每行一个 `RAGTestCase`

或使用脚本自动生成草稿：

```bash
uv run python scripts/build_alibaba_benchmark.py
# 人工审核生成的草稿...
uv run python scripts/build_alibaba_benchmark_final.py
```

---

## 模块独立性

本模块仅依赖：
- `rag.pipeline` — 用于检索
- `rag.vector_store` — 用于读取 chunk 文本（report 生成时）
- 标准库 + Pydantic

不依赖：
- API 层（FastAPI 路由）
- 前端
- LLM 调用
- 网络搜索
