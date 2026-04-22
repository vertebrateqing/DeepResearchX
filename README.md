# A-Stock Analyzer - A股分析Agent系统

一个生产级别的A股投资分析Multi-Agent系统，具备市场热点推荐、行业筛选、TopN公司选取、财报RAG分析、投资建议生成等能力。

## 特性

- **Multi-Agent架构**：主Agent + 多个专业Sub-Agent，上下文隔离，并行执行
- **Skill系统**：模块化技能注册和执行
- **Tool Use**：LLM自动选择和调用工具
- **RAG系统**：向量检索（ChromaDB）+ BM25精准检索 + 混合检索
- **财报分析**：长文本财报阅读和分析能力
- **Agent评测**：自动化评测和LLM-as-Judge

## 技术栈

| 组件 | 选型 |
|------|------|
| 向量数据库 | ChromaDB |
| LLM | OpenAI / 本地模型（可配置） |
| Embedding | OpenAI / BGE-large-zh（可配置） |
| A股数据 | AKShare |
| Web搜索 | Tavily / DuckDuckGo |

## 项目结构

```
financial_agent/
├── config/          # 配置管理
├── core/            # Agent核心框架
├── agents/          # Agent实现
├── skills/          # Skill模块
├── tools/           # Tool模块
├── rag/             # RAG系统
├── evaluation/      # 评测系统
├── tests/           # 测试
└── scripts/         # 工具脚本
```

## 快速开始

### 安装依赖

```bash
pip install -e ".[dev]"
```

### 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入 API keys
```

### 运行分析

```bash
python -m financial_agent
```

## License

MIT
