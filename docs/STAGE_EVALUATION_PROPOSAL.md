# DeepResearchX 分阶段评测指标体系设计方案

> 目标：为 RAG 检索效果与 Outline/DAG 生成质量建立可量化、可自动化、可追踪的评测体系，提升系统迭代效率。

---

## 1. 项目 Pipeline 阶段梳理

| 阶段 | 核心组件 | 关键产出 | 当前评测状态 |
|------|---------|---------|------------|
| P0: 意图澄清 | `IntentClarifier` | `ClarificationResult` | 无评测 |
| P1: 大纲生成 | `OutlinePlanner` | `ReportOutline` (outline.json) | 无评测 |
| P1b: 研究计划 | `ResearchPlanner` | `ResearchPlan` (DAG of TaskNodes) | 无评测 |
| P2: RAG 检索 | `RAGPipeline` | 相关 chunks | 基础单元测试 |
| P2b: 章节执行 | `ChapterWorker` + `DAGScheduler` | `chapter_*.md` | 无评测 |
| P3: 章节评审 | `ReviserAgent` | `reviews.json` | 内置 5 维评分 |
| P4: 整合编辑 | `IntegrationAgent` + `EditorAgent` | `draft.md` | 无评测 |
| P5: 报告导出 | `ReportGenerator` | `.md` / `.pdf` | 无评测 |

**当前已有评测基础设施：**
- `backend/deep_research/evaluation/metrics.py` — Accuracy, F1, Relevance, NDCG
- `backend/deep_research/evaluation/llm_judge.py` — LLM-as-Judge (5 维 1-5 分)
- `deep_research_bench/` — 端到端 benchmark 框架（4 维动态加权）

---

## 2. 方案一：工程化自动指标方案（Auto-Metrics First）

**核心思想：** 每个阶段输出均可被规则化指标自动校验，无需调用 LLM，毫秒级计算，**适合作为 CI 门禁和回归测试**。

### 2.1 Stage P2 — RAG Pipeline 评测

#### 指标组 A：Chunking 质量（无 LLM）

| 指标 | 定义 | 计算方式 | 目标阈值 |
|------|------|---------|---------|
| `chunk_boundary_bleed` | 在句中/段中切断的比例 | 检测 chunk 首尾是否落在标点或换行处 | < 15% |
| `chunk_length_cv` | chunk 长度变异系数 | `std(chunk_chars) / mean(chunk_chars)` | < 0.5 |
| `empty_chunk_rate` | 空/纯空白 chunk 占比 | `empty_chunks / total_chunks` | = 0% |
| `chunk_overlap_ratio` | 实际 overlap / 设定 overlap | `mean(overlap_chars) / chunk_overlap` | 0.8~1.2 |

> 实现：在 `RecursiveTextSplitter` 输出后直接计算，可用 `backend/tests/unit/test_rag.py` 扩展。

#### 指标组 B：Embedding & 检索质量（需标注数据集）

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| `precision@k` | 前 k 个检索结果中相关的比例 | `|relevant ∩ retrieved_k| / k` |
| `recall@k` | 相关文档被检索到的比例 | `|relevant ∩ retrieved_k| / |relevant|` |
| `mrr` | 第一个相关结果的倒数排名 | `mean(1 / rank_first_relevant)` |
| `ndcg@k` | 考虑排序位置的累积增益 | 见 `metrics.py` 现有实现 |
| `distance_variance` | 检索结果距离分布方差 | 方差过大说明 embedding 区分度差 |

> **评测数据集构建：** 准备 50~100 条 `(query, 相关 doc_ids, 相关 chunk_ids)` 标注，覆盖中英文、短查询、长查询。文档使用项目真实测试文档（PDF/TXT/DOCX）。

#### 指标组 C：Index 健康度（运行时监控）

| 指标 | 定义 | 采集方式 |
|------|------|---------|
| `duplicate_chunk_rate` | 重复内容 chunk 占比 | Hash 去重后计算 |
| `metadata_completeness` | chunk metadata 必填字段完整率 | 检查 `doc_id`, `chunk_index`, `filename` 等 |
| `index_latency_p99` | 单次检索延迟 P99 | `time.perf_counter()` 打点 |

### 2.2 Stage P1/P1b — Outline & DAG 结构评测

#### 指标组 D：DAG 结构正确性（100% 可自动判定）

| 指标 | 定义 | 计算方式 | 目标 |
|------|------|---------|------|
| `dag_is_acyclic` | DAG 无环 | Kahn 拓扑排序（已有 `_is_valid_dag`） | 必为 true |
| `dag_all_deps_exist` | 所有依赖节点存在 | `∀c, ∀d ∈ c.depends_on, d ∈ chapter_ids` | 必为 true |
| `dag_no_orphan_nodes` | 无孤立节点（至少一个入边或出边） | 入度+出度 > 0 | 必为 true |
| `dag_topological_depth` | 拓扑排序深度（并行度指标） | 最长依赖链长度 | 建议 3~5 |
| `dag_parallelization_ratio` | 可并行章节比例 | `max_parallelizable / total_chapters` | > 0.4 |

> 实现：复用 `planner.py` 中 `_is_valid_dag` 的逻辑，扩展为返回完整指标 dict。

#### 指标组 E：Outline 内容合规性

| 指标 | 定义 | 计算方式 | 目标 |
|------|------|---------|------|
| `title_specificity_score` | 标题是否含"研究对象+维度" | 正则：禁止匹配 "市场分析\|行业概况\|竞争格局" 等宽泛词；必须含实体名词+限定词 | > 0.8 |
| `word_count_in_range` | 字数在合理范围 | `∀c, 200 ≤ word_count ≤ 2000` | 100% |
| `tool_validity` | 工具选择合法 | `suggested_tools ⊆ {tavily_search, web_scraper}` | 100% |
| `research_type_balance` | 三类章节比例合理 | data_collection ≥ 1, analysis ≥ 1, conclusion ≥ 1 | 满足 |
| `key_questions_per_chapter` | 每章至少有几个具体问题 | `mean(len(key_questions))` | ≥ 2 |
| `dependency_type_consistency` | 依赖关系与类型一致 | analysis 必须依赖 data_collection; conclusion 必须依赖 analysis | 100% |

> 实现：在 `OutlinePlanner._parse_outline()` 后增加 `validate_outline()` 方法，返回合规性报告。

#### 指标组 F：Outline 与用户 Query 的覆盖度

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| `keyword_coverage` | query 关键词在大纲中的出现率 | `|query_keywords ∩ outline_text| / |query_keywords|` |
| `entity_coverage` | query 中的实体名是否被章节覆盖 | NER 提取实体后匹配 |

---

## 3. 方案二：LLM-as-Judge 语义评测方案（Semantic Quality First）

**核心思想：** 用 LLM（或更便宜的轻量模型）判断语义层面的质量，**指标更贴近人类感知**，适合评估生成质量，适合作为周级/发布级评测。

### 3.1 Stage P2 — RAG 语义检索评测

| 指标 | 定义 | Prompt 核心逻辑 | 评分 |
|------|------|----------------|------|
| `rag_query_chunk_relevance` | 检索 chunk 与 query 的语义相关度 | "以下文档片段是否能直接回答用户问题？" | 1~5 |
| `rag_information_sufficiency` | 检索结果信息量是否足够写作 | "基于这些片段，能否写出 800 字的完整分析？" | 1~5 |
| `rag_faithfulness` | chunk 是否忠实于原文 | "片段中是否有原文未包含的推断？" | 1~5 (扣分制) |
| `rag_source_diversity` | 来源是否多样化 | 统计 `unique(doc_id)` / `total_chunks` | 0~1 |

> 实现：扩展 `LLMJudge`，新增 `evaluate_retrieval(query, chunks) -> dict` 方法。

### 3.2 Stage P1 — Outline 语义质量评测

| 指标 | 定义 | Prompt 核心逻辑 | 评分 |
|------|------|----------------|------|
| `outline_coherence` | 大纲整体逻辑连贯性 | "章节间是否有自然的递进关系？" | 1~5 |
| `outline_dependency_rationality` | 依赖关系是否合理 | "每章的 depends_on 是否必要且充分？" | 1~5 |
| `outline_research_depth` | 研究深度是否足够 | "大纲是否只停留在表面描述，还是有深度分析？" | 1~5 |
| `outline_title_quality` | 标题质量 | "标题是否具体、可执行、无歧义？" | 1~5 |
| `outline_coverage` | 用户 query 维度覆盖度 | "用户的每个关注点是否都有对应章节？" | 1~5 |
| `outline_actionability` | 大纲产出是否有决策价值 | "按此大纲生成的报告，能否支持实际决策？" | 1~5 |

> **评测接口设计：**
> ```python
> async def evaluate_outline(
>     user_query: str,
>     outline: ReportOutline,
> ) -> dict:
>     """Return 6-dim semantic scores + reasoning."""
> ```

### 3.3 Stage P2b/P3 — 章节执行与评审语义评测

| 指标 | 定义 | 评测方式 |
|------|------|---------|
| `objective_achievement` | 章节是否达成 objective | LLM 判断 "章节内容是否完成了 stated objective" |
| `key_question_coverage` | 是否回答了所有 key_questions | LLM 逐条匹配 |
| `cross_chapter_consistency` | 章节间是否有矛盾 | 提取两章的 factual claims，用 LLM 做交叉验证 |
| `source_authority` | 来源权威性 | LLM 判断 URL/domain 可信度 + 引用是否规范 |

### 3.4 Stage P4/P5 — 整合与导出语义评测

| 指标 | 定义 | 评测方式 |
|------|------|---------|
| `transition_quality` | 章节过渡自然度 | LLM 判断 "删除章节标题后，读者能否感知结构变化" |
| `redundancy_score` | 重复内容比例 | LLM 提取重复论点，计算重复字数占比 |
| `executive_summary_accuracy` | 摘要准确度 | LLM 判断 "摘要中的每个要点是否在正文中有支撑" |
| `overall_report_quality` | 报告整体质量 | 复用 `deep_research_bench` 的 4 维框架 |

---

## 4. 方案三：端到端 Benchmark 迭代评测方案（Benchmark-Driven First）

**核心思想：** 建立固定 benchmark 数据集，用标准化输入追踪每次迭代的输出质量变化，**适合检测 regression、对比 A/B 版本、建立质量基线**。

### 4.1 Benchmark 数据集设计

#### 数据集规模与分类

```yaml
benchmark:
  total_tasks: 30
  categories:
    industry_analysis: 8      # 行业深度分析（如"2024年新能源汽车行业分析"）
    company_research: 8       # 公司调研（如"比亚迪2024年财报分析"）
    trend_forecast: 6         # 趋势预测（如"AI Agent未来3年发展趋势"）
    comparative_study: 4      # 对比研究（如"特斯拉vs比亚迪技术路线对比"）
    policy_impact: 4          # 政策影响（如"双碳政策对钢铁行业的影响"）
  difficulty:
    easy: 10    # 3-5 章，单维度问题
    medium: 12  # 6-8 章，多维度关联
    hard: 8     # 9-12 章，跨领域综合分析
```

#### 标注内容（每条 task）

```json
{
  "task_id": "bench_001",
  "category": "industry_analysis",
  "difficulty": "medium",
  "user_query": "2024年中国新能源汽车市场规模与竞争格局分析",
  "golden_outline": {
    "title": "...",
    "chapters": [
      {
        "chapter_id": "c1",
        "title": "2024年中国新能源汽车市场规模与增速",
        "key_dimensions": ["销量", "渗透率", "市场规模(亿元)"],
        "research_type": "data_collection"
      }
    ]
  },
  "golden_report_url": "./bench/golden/bench_001_reference.md",
  "rag_test_docs": ["bench_001_doc1.pdf", "bench_001_doc2.txt"],
  "rag_annotations": [
    {"query": "2024年新能源汽车销量", "relevant_chunk_ids": ["doc1__chunk__3", "doc2__chunk__7"]}
  ],
  "expected_dimensions": ["市场规模", "竞争格局", "增长驱动", "政策环境"],
  "evaluation_focus": ["数据准确性", "竞争格局分析深度"]
}
```

### 4.2 评测执行流程

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Benchmark Runner: 对每个 task 执行完整 pipeline            │
│    → 产出: outline.json, chapter_*.md, draft.md, reviews.json │
├─────────────────────────────────────────────────────────────┤
│ 2. Stage Scorer: 逐阶段打分                                   │
│    → Outline Score: 结构分 + LLM 语义分                       │
│    → RAG Score: 检索 Precision/Recall + LLM 相关性           │
│    → Chapter Score: objective_achievement × source_quality   │
│    → E2E Score: deep_research_bench 4 维评分                 │
├─────────────────────────────────────────────────────────────┤
│ 3. Regression Detector: 对比历史基线                         │
│    → 任意指标下降 > 5% 触发告警                               │
│    → 生成 diff report: 哪些 task 质量下降，哪个 stage 导致    │
├─────────────────────────────────────────────────────────────┤
│ 4. Dashboard Output:                                         │
│    → per-task 详细报告                                       │
│    → per-stage 聚合统计                                      │
│    → 历史趋势折线图 (JSON 供前端渲染)                         │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 关键评测指标定义

#### Outline 与 Golden Outline 对比

| 指标 | 定义 | 计算 |
|------|------|------|
| `outline_structure_similarity` | 生成大纲与黄金大纲的结构相似度 | 章节标题 Embedding 余弦相似度 + 数量匹配 |
| `outline_dependency_similarity` | 依赖图相似度 | 图编辑距离 (GED) 归一化 |
| `outline_dimension_coverage` | 预期维度覆盖率 | `|generated_dimensions ∩ expected_dimensions| / |expected_dimensions|` |
| `outline_hallucination_rate` | 幻觉章节比例 | 黄金大纲中不存在的无关章节占比 |

#### 端到端业务指标

| 指标 | 定义 | 目标 |
|------|------|------|
| `task_success_rate` | 完整 pipeline 成功完成率（无 fallback, 无 error） | > 90% |
| `one_shot_pass_rate` | 章节一次通过 review 的比例 | > 60% |
| `avg_revision_rounds` | 平均 revision 轮次 | < 1.5 |
| `p95_total_latency` | 端到端 P95 延迟 | 视难度: easy<60s, medium<120s, hard<300s |
| `token_efficiency` | 输出字数 / 输入 token 数 | 持续优化 |
| `fallback_rate` | 触发 fallback outline / fallback plan 的比例 | < 5% |

### 4.4 A/B 对比支持

```python
# 伪代码：同时跑两个版本，输出对比报告
async def run_ab_evaluation(
    benchmark_path: str,
    version_a: str,  # git commit or branch
    version_b: str,
) -> ABReport:
    results_a = await run_benchmark(version_a, benchmark_path)
    results_b = await run_benchmark(version_b, benchmark_path)

    # 逐 task 对比
    for task in benchmark:
        winner, margin = compare_pairwise(task, results_a[task], results_b[task])

    # 统计显著性
    return ABReport(
        overall_winner=...,
        significant_dimensions=[...],  # 哪些维度差异显著
        per_task_breakdown=[...],
    )
```

---

## 5. 三种方案对比与选型建议

| 维度 | 方案一：工程化自动指标 | 方案二：LLM-as-Judge | 方案三：Benchmark 迭代 |
|------|---------------------|---------------------|----------------------|
| **运行成本** | 极低（本地计算） | 中（每次调用 LLM API） | 高（完整 pipeline + LLM Judge） |
| **运行速度** | 毫秒~秒级 | 秒~分钟级 | 分钟~小时级 |
| **适合频率** | 每次 commit / CI | 每日/每周 regression | 每次发布 / 月度基线 |
| **最适合检测** | 结构错误、类型错误、DAG 环 | 语义质量下降、逻辑矛盾 | 端到端 regression、业务效果 |
| **需要标注** | 少量（RAG 检索标注） | 无需 | 需要维护 golden 数据集 |
| **可解释性** | 高（精确到行/字段） | 中（有 reasoning） | 高（有 per-task diff） |
| **与人类感知相关性** | 中 | 高 | 高 |

### 推荐组合策略

```
日常开发 (Per PR)
  └─> 方案一：自动指标门禁
        ├─ DAG 结构验证 (必过)
        ├─ Outline 合规性检查 (必过)
        ├─ RAG 单元测试 (必过)
        └─ 运行时间: < 30s

迭代评估 (Weekly / 重要 feature 完成后)
  └─ 方案二：LLM Judge 语义评测
        ├─ Outline 语义质量 (6 维)
        ├─ RAG 检索语义质量 (4 维)
        ├─ 跨章节一致性检查
        └─ 运行时间: ~10min (30 tasks)

发布基线 (Monthly / Release 前)
  └─ 方案三：完整 Benchmark
        ├─ 30-task 标准 benchmark
        ├─ 与上月基线对比 (regression detection)
        ├─ A/B 对比 (如有架构调整)
        └─ 运行时间: ~1-2h
```

---

## 6. 实施路线图（建议）

### Phase 1：立即可做（1-2 天）

1. **DAG 结构验证器**：在 `OutlinePlanner` 和 `ResearchPlanner` 中扩展 `_is_valid_dag`，返回完整指标（拓扑深度、并行度等）。
2. **Outline 合规性检查器**：新增 `validate_outline()`，检查标题特异性、工具合法性、类型一致性。
3. **RAG Chunking 指标**：在 `test_rag.py` 中补充 chunk boundary bleed、length CV 测试。

### Phase 2：短期建设（1 周）

1. **RAG 检索评测数据集**：标注 50 条 `(query, relevant_chunks)`，基于现有测试文档。
2. **LLM Judge 扩展**：在 `LLMJudge` 中新增 `evaluate_outline()`, `evaluate_retrieval()` 方法。
3. **评测报告生成器**：扩展 `EvaluationReport`，支持 per-stage 分数聚合。

### Phase 3：中期建设（2-4 周）

1. **Benchmark 数据集**：构建 30-task 标准 benchmark，含 golden outline 和参考报告。
2. **Regression Detector**：实现历史基线对比逻辑，下降 > 5% 触发告警。
3. **CI 集成**：将方案一接入 GitHub Actions / pre-commit hook。

### Phase 4：长期优化（持续）

1. **Dashboard**：可视化历史趋势，per-stage 瓶颈分析。
2. **自动根因分析**：当 benchmark 分数下降时，自动定位到具体 stage（是 outline 变差了，还是 RAG 检索变差了）。
3. **用户反馈闭环**：收集真实用户对报告质量的评分，纳入 benchmark。

---

## 7. 附录：关键代码扩展点

| 扩展项 | 目标文件 | 说明 |
|--------|---------|------|
| DAG 完整指标 | `backend/deep_research/core/planner.py` | 扩展 `_is_valid_dag` → `analyze_dag(tasks) -> DAGMetrics` |
| Outline 验证器 | `backend/deep_research/core/outline_planner.py` | 新增 `OutlineValidator` class |
| RAG 检索评测 | `backend/deep_research/evaluation/metrics.py` | 新增 `retrieval_metrics()` |
| LLM Judge 扩展 | `backend/deep_research/evaluation/llm_judge.py` | 新增 `evaluate_outline()`, `evaluate_retrieval()` |
| Benchmark Runner | `backend/deep_research/evaluation/evaluator.py` | 扩展 `AgentEvaluator` 支持 stage-by-stage |
| 报告生成 | `backend/deep_research/evaluation/report.py` | 支持 per-stage 聚合和趋势对比 |
