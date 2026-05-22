# DeepResearchX 文档处理与查询检索时序流程图

---

## 图 1：文档上传 → 切分 → 嵌入 → 存储

```mermaid
sequenceDiagram
    autonumber
    participant FE as 前端 (React)
    participant API as FastAPI Router<br/>api/router.py
    participant DOC as Documents API<br/>api/documents.py
    participant PIPE as RAGPipeline<br/>deep_research/rag/pipeline.py
    participant LOAD as DocumentLoader<br/>deep_research/rag/document_loader.py
    participant CHUNK as TextSplitter<br/>deep_research/rag/chunking.py
    participant EMB as EmbeddingService<br/>deep_research/rag/embedding.py
    participant VECT as ChromaVectorStore<br/>deep_research/rag/vector_store.py
    participant DB as ChromaDB<br/>(PersistentClient)

    Note over FE,DB: 一、用户上传文档 (POST /api/documents/upload)

    FE->>API: POST /api/documents/upload<br/>multipart: files[], session_id, chunking_strategy
    API->>DOC: upload_documents()<br/>L64

    DOC->>DOC: _validate_session(session_id)<br/>检查 session_id 合法性 L55
    DOC->>DOC: 校验 chunking_strategy ∈ {recursive, fixed, semantic}<br/>L88
    DOC->>DOC: 校验 embedding_model ∈ SUPPORTED_EMBEDDING_MODELS<br/>L96
    DOC->>DOC: _session_uploads_dir(sid)<br/>创建 ./data/sessions/{sid}/uploads/ L48
    DOC->>DOC: collection_for_session(sid)<br/>生成 collection 名 L104

    DOC->>PIPE: get_pipeline(collection, chunking_strategy=...)<br/>L112
    PIPE->>PIPE: _pipeline_cache 命中?<br/>命中则复用, 否则新建 L386
    alt Cache Miss
        PIPE->>PIPE: RAGPipeline.__init__()<br/>设置 splitter + embedding + vector_store L90
        PIPE->>CHUNK: get_splitter(strategy, chunk_size, overlap)<br/>L101
        CHUNK-->>PIPE: TextSplitter 实例
        PIPE->>EMB: EmbeddingService()<br/>L108
        EMB-->>PIPE: EmbeddingService 实例
        PIPE->>VECT: ChromaVectorStore(collection_name)<br/>L111
        VECT-->>PIPE: ChromaVectorStore 实例
    end
    PIPE-->>DOC: pipeline 实例

    loop 遍历每个上传文件
        DOC->>DOC: upload.read() 读取字节<br/>L134
        DOC->>DOC: doc_id = uuid.uuid4().hex<br/>L155
        DOC->>DOC: on_disk.write_bytes(data)<br/>保存到磁盘 L160<br/>路径: data/sessions/{sid}/uploads/{doc_id}{ext}

        DOC->>PIPE: ingest_file(file_path, doc_id, extra_metadata)<br/>L167
        Note right of PIPE: extra_metadata 包含:<br/>filename, stored_path,<br/>session_id, uploaded_at

        PIPE->>LOAD: load_document(path, meta)<br/>L127 (asyncio.to_thread)
        alt PDF 文件
            LOAD->>LOAD: pdfplumber.open() → extract_text()<br/>优先使用 pdfplumber
        else 失败 fallback
            LOAD->>LOAD: pypdf.PdfReader() → extract_text()
        else Word 文件
            LOAD->>LOAD: python-docx Document() → paragraphs
        else 文本文件
            LOAD->>LOAD: open(path, 'r')
        end
        LOAD-->>PIPE: Document(content, metadata, source)<br/>metadata 包含 doc_id

        PIPE->>PIPE: ingest_document(document, doc_id)<br/>L130
        PIPE->>CHUNK: splitter.split_text(document.content)<br/>L151
        alt strategy = "recursive"
            CHUNK->>CHUNK: RecursiveTextSplitter<br/>按分隔符递归拆分:<br/>paragraph → sentence → word → char
        else strategy = "fixed"
            CHUNK->>CHUNK: FixedLengthTextSplitter<br/>固定长度字符切分 + overlap
        else strategy = "semantic"
            CHUNK->>CHUNK: SemanticTextSplitter<br/>段落/句子边界 + 可选 embedding 主题漂移检测
        end
        CHUNK-->>PIPE: chunks: list[str]

        PIPE->>EMB: embed_texts(chunks)<br/>L156
        EMB->>EMB: EmbeddingTool.execute(texts)<br/>→ sentence-transformers
        EMB->>EMB: 模型: bge-large-zh-v1.5<br/>维度: 1024, CPU 推理
        EMB-->>PIPE: embeddings: list[list[float]]

        PIPE->>PIPE: 构建 chunk_ids<br/>format: "{doc_id}__chunk__{i}" L168
        PIPE->>PIPE: 构建 metadatas<br/>包含: doc_id, chunk_index,<br/>chunk_count, chunk_size,<br/>filename, session_id... L169-175

        PIPE->>VECT: add_documents(chunks, embeddings, metadatas, chunk_ids)<br/>L177
        VECT->>DB: collection.add()<br/>batch_size=100 L71
        DB-->>VECT: 存储完成
        VECT-->>PIPE: ids

        PIPE-->>DOC: {doc_id, chunks, chunk_ids, char_count}<br/>L191
        DOC->>DOC: 构建 DocumentInfo 响应<br/>L187
    end

    DOC-->>API: DocumentUploadResponse<br/>{session_id, collection, uploaded[], failed[]}
    API-->>FE: HTTP 200 JSON

    Note over FE,DB: 二、文档存储完成, collection 隔离按 session
```

---

## 图 2：查询 → 向量检索 → BM25 检索 → RRF 融合 → 返回

```mermaid
sequenceDiagram
    autonumber
    participant FE as 前端 (React)
    participant API as FastAPI Router<br/>api/router.py
    participant SSE as Streaming Service<br/>api/streaming.py
    participant ORCH as OrchestratorAgent<br/>deep_research/core/orchestrator.py
    participant CW as ChapterWorker<br/>deep_research/core/chapter_worker.py
    participant DST as DocumentSearchTool<br/>deep_research/tools/document_search.py
    participant PIPE as RAGPipeline<br/>deep_research/rag/pipeline.py
    participant EMB as EmbeddingService<br/>deep_research/rag/embedding.py
    participant VECT as ChromaVectorStore<br/>deep_research/rag/vector_store.py
    participant BM25 as BM25Retriever<br/>deep_research/rag/bm25_retriever.py
    participant DB as ChromaDB<br/>(PersistentClient)
    participant LLM as LLM API<br/>(OpenAI-compatible)

    Note over FE,LLM: 一、用户发起研究查询 (GET /api/analyze/stream)

    FE->>API: GET /api/analyze/stream<br/>?query=...&session_id=...&documents_only=...
    API->>SSE: analyze_stream(query, session_id, document_ids, documents_only)<br/>L86

    SSE->>SSE: task_id = uuid.uuid4()<br/>L56
    SSE->>SSE: 创建 progress_queue (asyncio.Queue)<br/>L75
    SSE->>ORCH: OrchestratorAgent(session_id, document_ids, documents_only)<br/>L87

    SSE->>ORCH: orchestrator.run(query)<br/>L99 (asyncio.create_task)

    Note over ORCH: Orchestrator Pipeline:<br/>1. IntentClarifier (可选)<br/>2. OutlinePlanner → ReportOutline<br/>3. ChapterWorker (并行执行各章节)

    ORCH->>CW: ChapterWorker.run()<br/>每个章节一个 Worker

    alt documents_only = false
        CW->>CW: 工具集 = {document_search, tavily_search, web_scraper}<br/>L360
    else documents_only = true
        CW->>CW: 工具集 = {document_search}<br/>禁用联网搜索
    end

    Note over CW: ChapterWorker 执行 ReAct 循环,<br/>LLM 决定调用哪个工具

    CW->>DST: DocumentSearchTool.execute(query, top_k, doc_ids)<br/>L66

    DST->>DST: 应用 doc_ids 范围过滤<br/>L76-83
    DST->>PIPE: get_pipeline(collection_name)<br/>L63
    PIPE-->>DST: RAGPipeline 实例 (缓存复用)

    DST->>PIPE: pipeline.query(query, top_k=k, doc_ids=scope_ids)<br/>L101

    PIPE->>PIPE: 构建 filter_dict<br/>单 doc: {"doc_id": id}<br/>多 doc: {"doc_id": {"$in": [...]}} L220-224

    PIPE->>EMB: embed_query(text)<br/>L227
    EMB->>EMB: embed_texts([query])<br/>→ sentence-transformers<br/>bge-large-zh-v1.5 (1024-dim)
    EMB-->>PIPE: query_embedding: list[float]

    PIPE->>VECT: search(embedding, top_k_vector, filter_dict)<br/>L228
    VECT->>DB: collection.query(<br/>query_embeddings=[embedding],<br/>n_results=top_k, where=filter)<br/>L88
    DB-->>VECT: {ids, documents, metadatas, distances}
    VECT-->>PIPE: vector_hits: [{id, content, metadata, score}]<br/>score = 1 - distance L237

    alt hybrid = true (默认)
        PIPE->>BM25: BM25Retriever.search(text, top_k_bm25, filter_dict)<br/>L251

        BM25->>DB: _fetch_candidates(filter_dict)<br/>L111
        DB-->>BM25: 全部文档 + metadata<br/>(从 Chroma collection 获取)

        BM25->>BM25: jieba.cut_for_search(text)<br/>中文分词 L23
        BM25->>BM25: rank_bm25.BM25Okapi<br/>k1={cfg.k1}, b={cfg.b} L83
        BM25->>BM25: get_scores(tokenized_query)<br/>L87
        BM25->>BM25: 按 score 排序, 取 top_k<br/>score 归一化到 [0,1] L105
        BM25-->>PIPE: bm25_hits: [{id, content, metadata, score}]<br/>score = raw_score / max_score

        PIPE->>PIPE: _reciprocal_rank_fusion(vector_hits, bm25_hits)<br/>L257 / L328
        Note right of PIPE: RRF 公式:<br/>score = Σ 1 / (k + rank)<br/>k = 60 (默认)<br/>vector 和 bm25 各贡献一个 rank
        PIPE->>PIPE: _register(vector_hits, "vector")<br/>_register(bm25_hits, "bm25")<br/>合并去重, 按 RRF score 排序<br/>取 final_top_k (默认 top_k_final=10)
    else hybrid = false
        PIPE->>PIPE: _merge_retrieval_results([vector_hits])<br/>去重, 按 score 排序
    end

    PIPE-->>DST: merged_hits: [{id, content, metadata, score, sources, rrf_score}]<br/>(hybrid 时含 vector_score + bm25_score)

    DST->>DST: 格式化 chunks<br/>{text, score, doc_id, filename, chunk_index, title}<br/>L109-121
    DST-->>CW: {query, chunks[], total}<br/>L144

    CW->>CW: 将 chunks 作为上下文<br/>拼接进 LLM Prompt
    CW->>LLM: LLM 调用 (generate)<br/>基于检索结果撰写章节内容
    LLM-->>CW: 章节正文

    CW-->>ORCH: AgentMessage(content)

    ORCH->>ORCH: ReviserAgent 审核 → IntegrationAgent 合并 → EditorAgent 润色

    ORCH-->>SSE: 最终结果
    SSE->>SSE: 通过 progress_queue<br/>yield SSE 事件

    loop 消费进度事件
        SSE->>FE: SSE event: status/progress/content<br/>data: {"event": "content", "data": {"text": "..."}}<br/>L108
    end

    SSE->>FE: SSE event: complete<br/>data: {"task_id": "...", "message": "分析完成"}<br/>L151

    Note over FE,LLM: 二、查询完成, 全程 SSE 流式推送
```

---

## 图 3：RAGPipeline.query() 内部细节 (Hybrid Retrieval)

```mermaid
sequenceDiagram
    autonumber
    participant Caller as Caller<br/>(DocumentSearchTool / Evaluator)
    participant PIPE as RAGPipeline.query()<br/>pipeline.py L200
    participant EMB as EmbeddingService<br/>embedding.py L27
    participant VECT as ChromaVectorStore<br/>vector_store.py L81
    participant BM25 as BM25Retriever<br/>bm25_retriever.py L52
    participant DB as ChromaDB

    Caller->>PIPE: query(text, top_k, doc_ids, hybrid=True)

    PIPE->>PIPE: filter_dict = build_filter(doc_ids)<br/>L220-224

    par 向量检索 (Vector Search)
        PIPE->>EMB: embed_query(text)<br/>L227
        EMB->>EMB: sentence-transformers<br/>bge-large-zh-v1.5
        EMB-->>PIPE: query_embedding
        PIPE->>VECT: search(embedding, top_k_vector, filter_dict)<br/>L228
        VECT->>DB: collection.query(n_results=k*2)
        DB-->>VECT: distances + documents
        VECT-->>PIPE: vector_hits[{id, content, metadata, score}]<br/>score = 1 - distance
    and BM25 检索 (Sparse Search)
        PIPE->>BM25: search(text, top_k_bm25, filter_dict)<br/>L251
        BM25->>DB: collection.get(where=filter, include=[docs, metas])
        DB-->>BM25: 全部候选文档
        BM25->>BM25: jieba.cut_for_search() 中文分词<br/>L23
        BM25->>BM25: BM25Okapi(tokenized_corpus)<br/>L83
        BM25->>BM25: get_scores(tokenized_query)<br/>排序 + score 归一化<br/>L87-106
        BM25-->>PIPE: bm25_hits[{id, content, metadata, score}]
    end

    PIPE->>PIPE: _reciprocal_rank_fusion(vector_hits, bm25_hits)<br/>L257 / L328
    Note right of PIPE: RRF Score = 1/(60+rank_vec) + 1/(60+rank_bm25)<br/>去重后按 RRF score 降序排列

    PIPE-->>Caller: merged_results[:final_top_k]<br/>每个结果含: id, content, metadata,<br/>score=rrf_score, sources=["vector","bm25"],<br/>vector_score, bm25_score
```

---

## 关键数据流与 ID 格式

| 阶段 | 关键 ID / 格式 | 代码位置 |
|------|---------------|---------|
| **Session ID** | 用户提供的会话标识 | `api/documents.py:64` |
| **Collection 名** | `session_uploads_{sid}` + hash 后缀 | `pipeline.py:77` `_safe_collection_name()` |
| **Doc ID** | `uuid.uuid4().hex` (32 位十六进制) | `api/documents.py:155` |
| **Chunk ID** | `{doc_id}__chunk__{i}` | `pipeline.py:168` |
| **文件存储路径** | `./deep_research/data/sessions/{sid}/uploads/{doc_id}{ext}` | `api/documents.py:158` |
| **Embedding 模型** | `BAAI/bge-large-zh-v1.5` (本地, 1024-dim) | `config/default.yaml` |
| **BM25 分词** | `jieba.cut_for_search()` | `bm25_retriever.py:23` |
| **RRF 常数 k** | `60` (可配置) | `pipeline.py:331` |
| **Chroma 距离函数** | `cosine` (默认) | `vector_store.py:46` |

---

## 切分策略对比

| 策略 | 实现类 | 核心逻辑 | 适用场景 |
|------|--------|---------|---------|
| **recursive** | `RecursiveTextSplitter` | 按分隔符递归拆分: `\n\n` → `\n` → `。！？` → 空格 → 字符 | 通用场景, 保留自然边界 |
| **fixed** | `FixedLengthTextSplitter` | 固定长度字符切分 + overlap | 最快, 最可预测 |
| **semantic** | `SemanticTextSplitter` | 段落/句子边界 + 可选 embedding 主题漂移合并 | 最佳语义保留, 较慢 |

---

*生成时间: 2026-05-22*
*基于代码版本: main branch (commit c90aa4f)*
