# A-Stock Analyzer V3 设计审查与改进方案

> 审查日期: 2026-04-21
> 基于 commit: 1d2c108 (Fix runtime errors) 及后续修改

---

## 一、功能缺陷 (Bugs)

### P0 - 阻塞/严重影响正确性

| # | 位置 | 问题描述 | 影响 |
|---|------|---------|------|
| 1 | `rag/pipeline.py:34` | `_merge_retrieval_results` 中 `if score < seen[doc_id]["score"]` 逻辑反了。cosine/l2 距离越小越好，应取 `>`。 | 多 query 改写后的合并检索结果**丢弃了高分文档、保留了低分文档**，检索质量严重下降。 |
| 2 | `core/agent.py:286,331,388` | `ReActAgent.run()` 和 `run_simple()` 仍在使用旧的 sanitize：`encode("utf-8", "surrogatepass").decode("utf-8", "replace")`。 | **中文乱码**。该方式会破坏多字节 UTF-8 序列，导致输出出现 � 或乱码。之前已在 `cli.py` 和 `memory/manager.py` 修复，但遗漏了 `agent.py`。 |
| 3 | `memory/session_store.py:63` | `_sanitize_text` 使用同样的旧 encode/decode 方式。 | Session 持久化时中文被污染，下次加载会话历史时乱码。 |
| 4 | `config/default.yaml:31,56` | `base_url` 多了路径后缀：`/chat/completions` 和 `/embeddings`。 | **API 调用 404**。OpenAI 兼容格式的 base_url 应只到 `/v1`，具体路径由 SDK/代码拼接。 |
| 5 | `tools/web_search.py:69` | `WebSearchTool._search_tavily()` 中 `client.search()` 是**同步调用**，未用 `asyncio.to_thread` 包装。 | **阻塞整个事件循环**。在 asyncio.gather 并行搜索多个 variants 时，每个 Tavily 调用都会阻塞，失去并行意义。 |

### P1 - 明显功能异常

| # | 位置 | 问题描述 | 影响 |
|---|------|---------|------|
| 6 | `agents/financial_rag_agent.py:39` | `_merge_web_results` 中 `result.get("query", "")` 的 `result` 是循环变量，循环结束后引用的是**最后一次迭代**的值。 | 返回的 merged result 中 query 字段永远错误。 |
| 7 | `core/intent_clarifier.py:59-72` | `_inject_year()` 函数仍在做字符串替换（`re.sub(r"去年\|...", f"{year}年", query)`）。 | **用户已明确拒绝字符串替换方式**。被 `_rebuild_merged_query()` 调用，当 slot 中有 report_year 时仍会做替换。 |
| 8 | `core/orchestrator.py:146` | 意图澄清阶段（`not clarification.complete`）就调用 `await self.memory.save()`。 | `memory.save()` → `LongTermStore.add_finding()` → `embed_query()` → 调用 Embedding API。**用户在等待澄清问题时，后台被阻塞做 embedding**，在网络慢时造成"卡住"假象。 |
| 9 | `core/intent_clarifier.py` | `company_name_short` 规则的 `negative_patterns` 只排除了带股票代码的情况，但 `\b[^\d\W]{2,3}` 正则仍会匹配"比亚迪"（3字）。 | **规则层先于 LLM 层执行**，即使 LLM 提示词已优化不将"比亚迪"视为歧义，rule-based 仍会在 LLM 之前触发澄清。 |
| 10 | `core/agent.py:223-287` | ReAct loop 的 `for iteration in range(self.max_iterations)` 如果 10 轮都未得到最终答案，`final_answer` 为空字符串，不会报错。 | Agent 可能返回空内容，调用方无法区分是"思考中"还是"失败了"。 |
| 11 | `core/intent_clarifier.py:27` | `_resolve_temporal_value` 定义了 `current_month` 但从未使用。 | 代码异味，但无功能影响。 |

---

## 二、架构与设计缺陷

### 2.1 Agent 编排层

| # | 问题 | 说明 |
|---|------|------|
| D1 | **Phase 2/3 串行执行** | `orchestrator.py` 中 `company_selection` 和 `financial_rag` 是串行的（`company_task` 先 await，然后才创建 `financial_task`）。这两个阶段理论上可并行， company 选股和财报分析互相独立。 |
| D2 | **异常被吞掉转为字符串** | `_extract_summary()` 将 `Exception` 转为 `"Error: {str(result)}"`，上层 orchestrator 无法区分是"部分失败"还是"完全失败"，报告合成时可能把错误信息当作有效分析摘要。 |
| D3 | **Task classification 无容错** | `_classify_task()` 仅做关键词匹配，若 LLM 输出不在 `[full_analysis, market_only, ...]` 列表中则默认 `full_analysis`，没有向用户确认或降级 graceful 处理。 |
| D4 | **Sub-agent 每次都重建 tool 实例** | 每个 sub-agent 的 `run()` 方法内部 `akshare = AKShareTool()`、`web_search = WebSearchTool()`，每次请求都重新创建，包括 Tavily client 的初始化。 |
| D5 | **Query rewriting 无跳过机制** | 对"退出""status""prefs"等内部命令，以及非常简单的查询，也调用 LLM 做 query rewriting，造成不必要的 API 调用和延迟。 |

### 2.2 记忆与存储层

| # | 问题 | 说明 |
|---|------|------|
| D6 | **每次交互都同步到 long-term memory** | `MemoryManager.save()` 每次都会将 `accumulated_findings` 全部 embed 并写入 ChromaDB。即使只有 1 条新 finding，也遍历全部历史 findings 做 embed。在长会话中越来越慢。 |
| D7 | **Session store 双写 I/O** | 每次 save 同时写 JSON + Markdown，Markdown 的 `_to_markdown` 处理大量字符串拼接。在高频交互下 I/O 开销明显。 |
| D8 | **Embedding service 无连接复用** | `EmbeddingTool` 每次创建新的 `httpx.AsyncClient`，HTTP 连接没有复用。 |
| D9 | **BM25 每次 add_document 都全量重建** | `BM25Store.add_documents()` 对全部已有文档重建索引，`O(N^2)` 复杂度随文档增长。 |

### 2.3 RAG 与检索层

| # | 问题 | 说明 |
|---|------|------|
| D10 | **Query rewriting 后 embedding 串行** | `pipeline.py:237` 调用 `embed_texts(queries)`，内部是 for 循环 batch，queries 之间是串行的。3 个 variants 无并行。 |
| D11 | **Reranker 缺少实现检查** | `pipeline.py` 初始化 `CrossEncoderReranker()` 但未检查是否可用。如果模型未下载，首次调用会触发下载，可能耗时数分钟且无日志提示。 |
| D12 | **Vector store 元数据中的 `related_entities` 是 JSON 字符串** | `LongTermStore.add_finding()` 将 `related_entities` 转为 JSON string 存入 metadata。ChromaDB 不支持对 JSON string 做过滤查询，entity_filter 只能在 Python 层做 post-filter。 |

---

## 三、报告质量改进 (PDF/Markdown)

### 3.1 当前报告的问题

| # | 问题 | 说明 |
|---|------|------|
| R1 | **中文 PDF 显示为方块** | `weasyprint` 默认没有中文字体。服务器/容器环境中通常缺少 `Noto Sans CJK SC` 等字体，生成的 PDF 中文全部显示为方框或空白。 |
| R2 | **目录锚点无法跳转** | Markdown TOC 使用中文标题作为锚点（如 `#{title}`），但 `markdown` 库生成的 HTML anchor 会将中文转义或移除，导致 TOC 链接失效。 |
| R3 | **没有独立执行摘要生成** | 当前直接把 orchestrator 合成的 `final_report` 放入"执行摘要"，如果 final_report 很长（>3000 字），摘要失去意义。应单独用 LLM 生成 300-500 字精炼摘要。 |
| R4 | **数据源和时间标注缺失** | 报告中各 section 没有标注数据来源（AKShare/Web Search/RAG）和数据获取时间。投资建议没有时效性标注，合规风险。 |
| R5 | **纯文本，无结构化表格** | 财务数据、行业对比等应使用 Markdown 表格呈现，但当前只是纯文本堆砌。 |
| R6 | **没有分页和页眉页脚** | PDF 缺少页码、报告标题页眉、生成时间页脚。 |
| R7 | **weasyprint 依赖过重** | `weasyprint` 依赖 GTK+/Pango/Cairo，在 Alpine Linux 等环境中安装困难。当前 graceful fallback 只到 HTML，但用户需要 PDF。 |

### 3.2 报告改进方案

```
建议方案 A（轻量）: markdown → playwright/pdf（通过浏览器打印）
- 优点: 中文字体由浏览器处理，排版好，无需 weasyprint 的 GTK 依赖
- 缺点: 需要 playwright/chromium

建议方案 B（保留现有）: 修复 weasyprint 字体问题 + 增加 playwright fallback
- 安装系统字体 + 在 CSS 中正确指定字体栈
- weasyprint 不可用时自动 fallback 到 playwright 或无头 chrome
```

---

## 四、性能优化点

| # | 位置 | 优化方案 | 预期收益 |
|---|------|---------|---------|
| O1 | `memory/manager.py:88-111` | `save()` 中只同步**新增**的 findings 到 long-term store，而非遍历全部历史。增加 `last_synced_index` 标记。 | 长会话 save 时间从数秒降至毫秒级。 |
| O2 | `tools/web_search.py:69` | Tavily 调用使用 `asyncio.to_thread()` 包装。 | 恢复并行搜索的真正并发性能。 |
| O3 | `core/orchestrator.py:364-381` | Phase 2 (company_selection) 和 Phase 3 (financial_rag) 并行执行。 | 减少整体响应时间 ~30-40%。 |
| O4 | `rag/query_rewriter.py` | 对简单查询（<10 字、纯命令词如"status"/"exit"）跳过 rewriting。 | 减少 1 次 LLM 调用 (~1-3 秒)。 |
| O5 | `rag/embedding.py` | `embed_texts()` 内部 batch 可并行发送多个 batch 请求（如果 API 支持）。 | 大批量文档入库速度提升。 |
| O6 | `rag/bm25_store.py` | 增量更新 BM25 索引，而非全量重建。 | 大量文档时索引更新速度提升 10x+。 |

---

## 五、待修改清单（按优先级排序）

### Phase 1 - 必须修复（阻塞正确性）

- [ ] **B1** 修复 `_merge_retrieval_results` 分数比较逻辑 (`>` 而非 `<`)
- [ ] **B2** 统一 sanitize 方法：`agent.py` 三处旧 encode/decode 改为字符级过滤
- [ ] **B3** 修复 `session_store.py` `_sanitize_text` 为字符级过滤
- [ ] **B4** 修复 `default.yaml` base_url 去掉 `/chat/completions` 和 `/embeddings` 后缀
- [ ] **B5** `WebSearchTool._search_tavily()` 用 `asyncio.to_thread()` 包装同步调用
- [ ] **B7** 移除 `_inject_year()` 中的字符串替换逻辑，或改为向 query 追加日期上下文
- [ ] **B8** Clarification 阶段不调用 `memory.save()`（或 save 时不 sync long-term）
- [ ] **B9** 修复 `company_name_short` 规则对知名公司的误触发（rule-based 层增加白名单逻辑或调整正则）

### Phase 2 - 架构改进

- [ ] **D1** Phase 2/3 并行化
- [ ] **D2** 异常处理改进：`_extract_summary` 返回结构化结果（含 `is_error` 标志）
- [ ] **D4** Sub-agent tool 实例复用（改为 agent 级别初始化）
- [ ] **D5** Query rewriting 增加跳过条件
- [ ] **D6** Memory save 只同步增量 findings
- [ ] **O2** Tavily 异步化

### Phase 3 - 报告质量提升

- [ ] **R1/R7** 解决 PDF 中文字体问题（weasyprint 字体配置 + playwright fallback）
- [ ] **R2** 修复 TOC 锚点（使用英文 slug 或移除锚点）
- [ ] **R3** 增加独立执行摘要生成（用 LLM 提炼 final_report）
- [ ] **R4** 在报告中增加数据来源标注和时间戳
- [ ] **R5** 子 agent 输出结构化数据（表格格式）以便报告生成表格
- [ ] **R6** 增加 PDF 页眉页脚

---

## 六、关于无法实际跑通流程的说明

当前环境缺少有效的 API Key（`OPENAI_API_KEY`、`TAVILY_API_KEY` 均未配置），因此无法触发完整的多 agent 并行流程。上述分析基于：

1. **静态代码审查** - 逐行阅读 15+ 核心文件
2. **局部运行时验证** - 运行 CLI 至 intent clarifier 阶段，确认 rule-based 规则的触发行为
3. **已知历史问题** - 从 session context 中继承的已修复/未修复 bug 记录

如配置 API Key 后，建议重点观察以下日志点验证修复效果：
- `[QueryRewriter] Generated N variants` — 确认改写生效
- `[RAGPipeline] Query variants: N, merged unique docs: M` — 确认合并逻辑正确
- `[FinancialRAG] Web search merged: N unique results` — 确认去重和合并正确
- `[Orchestrator] Report saved: md=..., pdf=...` — 确认报告文件生成
- 最终 `.md` 和 `.pdf` 文件的内容完整性和中文显示
