# Tests — 测试说明

本目录包含 DeepResearchX 的测试套件，按功能模块组织。

---

## 目录结构

```
tests/
├── conftest.py                          # pytest 共享 fixture
├── test_langfuse_integration.py         # Langfuse 可观测性集成测试
└── unit/
    ├── test_bm25.py                     # BM25 稀疏检索
    ├── test_chapter_worker.py           # ChapterWorker 章节研究
    ├── test_chunking.py                 # 文本切分策略
    ├── test_core.py                     # 核心编排逻辑
    ├── test_documents.py                # 文档上传 API
    ├── test_documents_only.py           # documents_only 模式
    ├── test_evaluation_chunking.py      # 切分质量评测
    ├── test_evaluation_metrics.py       # 评测指标计算
    ├── test_evaluation_rag.py           # RAG 评测流程
    ├── test_rag.py                      # RAG Pipeline 端到端
    └── test_tools.py                    # 工具层（搜索、抓取、LLM）
```

---

## 运行测试

```bash
cd backend

# 运行全部测试
uv run pytest

# 运行特定模块
uv run pytest tests/unit/test_evaluation_metrics.py -v
uv run pytest tests/unit/test_chunking.py -v

# 运行带标记的测试
uv run pytest -m "not slow" -v

# 显示覆盖率
uv run pytest --cov=deep_research --cov-report=html
```

---

## 各测试模块说明

### `test_bm25.py`

测试 BM25 稀疏检索：
- jieba 中文分词正确性
- BM25Okapi 打分排序
- 分数归一化到 [0, 1]
- 与空查询的边界行为

### `test_chapter_worker.py`

测试章节研究 Worker：
- ReAct 循环工具调用
- 系统提示词动态构建（`_build_react_system_prompt`）
- 文档上下文注入
- 章节依赖 DAG 执行顺序

### `test_chunking.py`

测试三种切分策略：
- **RecursiveTextSplitter**：分隔符层级（段落 → 句子 → 词 → 字符）
- **FixedLengthTextSplitter**：固定长度 + overlap
- **SemanticTextSplitter**：段落/句子边界 + 主题漂移检测

### `test_evaluation_metrics.py`

测试 RAG 评测指标计算：
- Precision@k（精确率）
- Recall@k（召回率）
- MRR（平均倒数排名）
- NDCG@k（归一化折损累积增益）

测试覆盖边界情况：空结果、全相关、全不相关、重复 chunk ID。

### `test_evaluation_rag.py`

测试 RAG 评测流程：
- `RAGEvaluator` 加载 benchmark
- `evaluate_query` 单查询评测
- `run` 批量评测报告生成
- `EvaluationReporter` JSON + Markdown 输出

### `test_documents.py`

测试文档上传 API：
- 多文件上传
- chunking_strategy / embedding_model 参数校验
- 文件大小限制（50 MB）
- 不支持的文件类型拒绝
- session_id 验证

### `test_documents_only.py`

测试 `documents_only=true` 模式：
- 禁用网络搜索工具
- 仅使用 DocumentSearchTool
- ChapterWorker 工具集动态调整

### `test_rag.py`

测试 RAG Pipeline 端到端：
- `ingest_file()` → 解析 → 切分 → 嵌入 → 入库
- `query()` 向量检索
- `query(hybrid=True)` 混合检索 + RRF
- `list_documents()` 文档列表
- `delete_document()` 删除文档

### `test_tools.py`

测试工具层：
- `TavilySearch` / `DuckDuckGoSearch` 网络搜索
- `WebScraper` 网页抓取 + 混合排序
- `LLMCall` 直接 LLM 调用
- 工具超时和错误处理

### `test_langfuse_integration.py`

测试 Langfuse 可观测性：
- trace 创建和结束
- span 嵌套结构
- generation 记录 LLM 调用
- dataset 录制

---

## 测试 Fixture（conftest.py）

共享 fixture 提供：

```python
@pytest.fixture
def fake_embedding_service():
    """返回 FakeEmbeddingService，避免真实 API 调用。"""

@pytest.fixture
def tmp_chroma_collection(tmp_path):
    """创建临时 Chroma collection，测试结束后自动清理。"""

@pytest.fixture
def sample_document():
    """返回标准测试文档（content + metadata）。"""
```

---

## 编写新测试

```python
# tests/unit/test_xxx.py
import pytest
from deep_research.xxx import SomeClass

class TestSomeClass:
    def test_basic_behavior(self):
        obj = SomeClass()
        result = obj.do_something()
        assert result == expected

    @pytest.mark.asyncio
    async def test_async_behavior(self):
        obj = SomeClass()
        result = await obj.do_something_async()
        assert result == expected

    def test_edge_case_empty_input(self):
        obj = SomeClass()
        result = obj.do_something("")
        assert result == []
```

---

## 测试原则

1. **单元测试隔离**：每个测试独立运行，不依赖外部服务（LLM API、搜索引擎）
2. **Fake/Stub 替代**：使用 `FakeEmbeddingService`、mock HTTP client 替代真实调用
3. **临时数据**：Chroma collection 使用 `tmp_path`，测试后自动清理
4. **边界覆盖**：空输入、超长文本、异常格式、网络超时
