# A-Stock Analyzer V2 架构升级方案

## 概述

针对以下新增需求进行架构升级设计：
1. Human-in-the-loop 意图澄清机制
2. 多模态内容处理能力（PDF/HTML中的图表等）
3. 长期记忆系统
4. 上下文压缩与摘要机制

---

## 1. Human-in-the-Loop 意图澄清机制

### 问题场景
- 用户请求"分析贵州茅台的财报" → 未指定年份/季度
- 用户请求"看看这个公司" → 公司名缩写歧义（BYD→比亚迪，还是其他？）
- 用户请求"推荐好的股票" → "好"的定义模糊（稳健型/成长型/价值型？）

### 设计方案

```
用户输入
    │
    ▼
┌─────────────────────────────────────┐
│      Intent Clarification Agent      │
│  (轻量级LLM，专门判断意图是否完整)     │
└─────────────────────────────────────┘
    │
    ├── 意图完整 ──► 继续执行主流程
    │
    └── 意图不完整 ──► 生成澄清问题列表
              │
              ▼
        ┌─────────────────────┐
        │   AskUserQuestion    │
        │  (向用户确认缺失信息)  │
        └─────────────────────┘
              │
              ▼
        用户回答 → 合并到原始query → 重新判断
              │
              └── 最多3轮澄清，仍不完整则基于默认值继续
```

### 缺失信息检测规则

| 场景 | 检测模式 | 澄清问题示例 |
|------|----------|-------------|
| 财报年份缺失 | 包含"财报/年报/季报"但无年份 | "请问您想分析哪一年的财报？" |
| 公司名歧义 | 简称匹配多个公司 | "'BYD'是指比亚迪(002594)吗？" |
| 投资风格未指定 | 包含"推荐/买"但无风格 | "您偏好稳健型、成长型还是价值型投资？" |
| 时间维度缺失 | 包含"近期/现在" | "分析的时间范围是？（短期1个月/中期半年/长期1年+）" |
| TopN未指定 | 包含"top"但无数字 | "您希望推荐多少家公司？默认10家" |

### 技术实现

```python
# core/intent_clarifier.py
class IntentClarifier:
    """Detects missing/ambiguous information in user queries."""

    def analyze(self, query: str, context: ConversationContext) -> ClarificationResult:
        """
        Returns:
            - complete: bool, 意图是否完整
            - missing_slots: list[MissingSlot], 缺失的信息槽
            - merged_query: str, 合并后的query（如果已有历史澄清）
        """

@dataclass
class MissingSlot:
    slot_name: str      # e.g., "report_year"
    slot_type: str      # e.g., "temporal", "entity", "preference"
    question: str       # 向用户提出的问题
    default_value: Any  # 默认值
    confidence: float   # 模型对"缺失"判断的置信度
```

### 对话状态机

```
STATE_NEW → STATE_CLARIFYING → STATE_CONFIRMED → STATE_EXECUTING → STATE_DONE
               │                    │
               └── 用户补充信息 ─────┘
```

---

## 2. 多模态处理能力

### 需求分析
- **PDF财报**: 包含表格、图表（收入趋势图、利润结构图等）
- **HTML网页**: 研报页面含图表、K线图截图
- **当前局限**: 纯文本RAG无法利用图表中的视觉信息

### 设计方案

```
┌─────────────────────────────────────────────────────────────┐
│                    Multimodal Pipeline                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  PDF/HTML Input                                               │
│       │                                                       │
│       ▼                                                       │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │ Text Extract │    │ Table Extract│    │ Image Extract│      │
│  │  (现有)      │    │  (pdfplumber)│    │  (pdf2image) │      │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘      │
│         │                  │                  │              │
│         ▼                  ▼                  ▼              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Unified Document Schema                  │   │
│  │  {                                                    │   │
│  │    "chunks": [                                        │   │
│  │      {                                                │   │
│  │        "type": "text",                                │   │
│  │        "content": "营业收入100亿..."                   │   │
│  │      },                                               │   │
│  │      {                                                │   │
│  │        "type": "table",                               │   │
│  │        "content": "Markdown表格",                      │   │
│  │        "structured": {...}                            │   │
│  │      },                                               │   │
│  │      {                                                │   │
│  │        "type": "image",                               │   │
│  │        "content": "base64/路径",                       │   │
│  │        "caption": "图表标题",                          │   │
│  │        "ocr_text": "OCR识别出的文字",                   │   │
│  │        "vllm_description": "VLM生成的图表描述"          │   │
│  │      }                                                │   │
│  │    ]                                                  │   │
│  │  }                                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                                                   │
│         ▼                                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Multimodal Embedding                      │   │
│  │                                                       │   │
│  │  Text chunks → text-embedding-3-large / BGE          │   │
│  │  Table chunks → text embedding (结构化文本化)         │   │
│  │  Image chunks → CLIP / 多模态embedding               │   │
│  │         + VLM生成textual description后嵌入            │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                                                   │
│         ▼                                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Vector Store (ChromaDB)                   │   │
│  │  - 同一张量空间存储所有模态的embedding                │   │
│  │  - metadata标记模态类型                               │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 图表理解（VLM Pipeline）

```python
# rag/multimodal/vlm_processor.py
class VLMProcessor:
    """Process images/charts using Vision-Language Model."""

    async def describe_image(self, image_path: str) -> str:
        """Generate textual description of an image/chart."""
        # 使用GPT-4V / Qwen-VL / 本地多模态模型
        # 返回结构化描述：图表类型、X/Y轴、关键数据点、趋势等

    async def extract_chart_data(self, image_path: str) -> dict:
        """Extract structured data from chart image."""
        # 针对财报图表优化：识别柱状图、折线图、饼图
        # 返回：{chart_type, x_labels, y_values, series, trends}
```

### 图像处理链路

```
PDF Page
   │
   ├── Text Stream → text_splitter → text chunks
   │
   ├── Table Regions → pdfplumber → structured table → markdown text → text chunks
   │
   └── Image Regions
            │
            ├── 图表类 (charts/graphs)
            │      ├── OCR提取文字标注
            │      ├── VLM生成自然语言描述
            │      ├── 结构化数据提取（如可能）
            │      └── 存储为：描述文本 + 图像embedding
            │
            └── 非图表类 (logos/decorative)
                   └── 过滤丢弃
```

---

## 3. 长期记忆系统

### 需求分析
- 研究一个公司可能涉及多次查询、多份财报、多轮web搜索
- 上下文容易溢出，需要持久化中间结果
- 需要记住：已查过的数据、已分析过的结论、待办事项、用户偏好

### 记忆分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory Architecture                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Layer 1: Working Memory (工作记忆)                          │
│  ─────────────────────────────────                           │
│  - 当前对话轮次的信息                                          │
│  - 短期tool调用结果缓存                                        │
│  - 生命周期：单次请求                                          │
│  - 存储：Python对象/内存                                       │
│                                                               │
│  Layer 2: Session Memory (会话记忆)                          │
│  ─────────────────────────────────                           │
│  - 当前用户会话的完整上下文                                    │
│  - 已执行的子任务和结果                                        │
│  - 用户的澄清回答和历史                                        │
│  - 待办事项列表（当前任务栈）                                  │
│  - 生命周期：整个用户会话                                      │
│  - 存储：SQLite / JSON文件                                     │
│                                                               │
│  Layer 3: Long-term Memory (长期记忆)                        │
│  ─────────────────────────────────                           │
│  - 用户投资偏好（风格、风险偏好、行业偏好）                    │
│  - 历史分析过的公司和结论                                      │
│  - 常用的分析维度和关注指标                                    │
│  - 生命周期：跨会话持久化                                      │
│  - 存储：向量数据库 + 结构化存储                               │
│                                                               │
│  Layer 4: Episodic Memory (情景记忆)                         │
│  ─────────────────────────────────                           │
│  - 完整的任务执行轨迹（可复盘）                                │
│  - Agent决策过程的记录                                         │
│  - 用于后续分析和Agent改进                                     │
│  - 存储：日志文件 + 数据库                                     │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 记忆数据模型

```python
# memory/models.py

@dataclass
class SessionMemory:
    session_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    conversation_history: list[ConversationTurn]
    task_stack: list[TaskState]          # 当前待办/进行中的任务
    completed_tasks: list[TaskResult]    # 已完成的任务
    accumulated_findings: list[Finding]  # 累积的研究发现
    user_preferences: UserPreferences    # 本次会话中观察到的偏好

@dataclass
class TaskState:
    task_id: str
    task_type: str                       # "market_analysis", "financial_rag", ...
    status: str                          # "pending", "in_progress", "completed", "failed"
    assigned_agent: str
    inputs: dict
    intermediate_results: list[dict]     # 中间结果
    final_result: dict | None
    dependencies: list[str]              # 依赖的其他任务ID
    created_at: datetime
    updated_at: datetime

@dataclass
class Finding:
    """A piece of knowledge discovered during research."""
    finding_id: str
    source: str                          # "web_search", "akshare", "financial_report", ...
    source_ref: str                      # URL / 文档ID / API名称
    content: str
    confidence: float
    related_entities: list[str]          # 相关公司/行业/概念
    extracted_at: datetime
    expires_at: datetime | None          # 信息过期时间（行情数据易过期）

@dataclass
class UserPreferences:
    investment_style: str | None         # "value", "growth", "balanced"
    risk_tolerance: str | None           # "low", "medium", "high"
    preferred_industries: list[str]
    excluded_industries: list[str]
    time_horizon: str | None             # "short", "medium", "long"
    top_n_default: int                   # 默认推荐数量
```

### 记忆写入策略

| 触发条件 | 写入内容 | 目标层级 |
|---------|---------|---------|
| Tool调用返回 | Tool结果摘要 | Working → Session |
| Sub-Agent完成 | 执行摘要、关键发现 | Session |
| 用户确认信息 | 澄清后的意图、偏好 | Session → Long-term |
| 任务完成 | 完整任务结果、结论 | Session + Episodic |
| 会话结束 | 用户偏好更新 | Long-term |
| 新会话开始 | 加载用户长期偏好 | Long-term → Session |

### 记忆读取时机

```
新请求到达
    │
    ├── 加载用户长期偏好 → 注入System Prompt
    │
    ├── 检查Session中是否有相关历史发现
    │   └── 有 → 作为上下文注入
    │
    ├── 检查是否有未完成的依赖任务
    │   └── 有 → 自动恢复或询问用户
    │
    └── 开始执行
```

---

## 4. 上下文压缩机制

### 触发条件
- 上下文Token数达到模型上下文窗口的 **80%**
- 或者：消息轮数超过 **20轮**

### 压缩策略

```
Context Window Usage: ████████████████████░░░░  80%
                              │
                              ▼
                    ┌─────────────────────┐
                    │   Context Compactor  │
                    └─────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌─────────┐    ┌─────────┐    ┌─────────┐
        │ 保留头部 │    │ 摘要中部 │    │ 保留尾部 │
        │(系统指令)│    │(任务进展)│    │(最近对话)│
        └─────────┘    └─────────┘    └─────────┘
```

### 压缩算法

```python
# core/context_compactor.py

class ContextCompactor:
    """Compress context when approaching token limit."""

    COMPRESSION_THRESHOLD = 0.8  # 80%
    RECENT_ROUNDS_TO_KEEP = 4    # 保留最近4轮对话

    async def compact(self, messages: list[dict], model: str) -> list[dict]:
        """
        1. 计算当前token数
        2. 如果低于阈值，直接返回
        3. 否则执行压缩：
           a. 识别可压缩区域（中间的老旧对话/工具调用）
           b. 生成压缩摘要（保留任务进展、执行状态、todo项）
           c. 保留最近的对话轮次
           d. 重新组装消息列表
        """

    def _identify_compressible_regions(self, messages: list[dict]) -> list[Slice]:
        """识别可以压缩的消息区域。"""
        # 规则：
        # - System Prompt: 永不压缩
        # - 最近的 RECENT_ROUNDS_TO_KEEP 轮对话: 保留
        # - 工具调用详细结果: 可压缩为摘要
        # - 已完成子Agent的完整输出: 可压缩为摘要
        # - 用户的澄清对话: 压缩为最终确认结果

    async def _generate_summary(self, messages: list[dict], metadata: dict) -> str:
        """生成压缩摘要。

        摘要必须包含：
        1. 当前任务目标
        2. 已完成的子任务和关键结论
        3. 待办事项（未完成的子任务）
        4. 已获取的关键数据/发现
        5. 用户确认的偏好/约束
        6. 最近N轮对话的简要回顾
        """
```

### 压缩摘要模板

```markdown
## [上下文摘要 - 生成时间: YYYY-MM-DD HH:MM]

### 当前任务
{主任务描述}

### 执行状态
- 整体进度: {X/Y 子任务完成}
- 当前阶段: {具体阶段}
- 阻塞项: {如有}

### 已完成的关键工作
1. [{agent_name}] {任务摘要} → 结论: {关键结论}
2. ...

### 待办事项
- [ ] {待办任务1} (依赖: {依赖项})
- [ ] {待办任务2}

### 关键发现
- {发现1}
- {发现2}

### 用户偏好/约束
- 投资风格: {style}
- 风险偏好: {risk}
- 其他约束: {constraints}

### 最近对话回顾
- 用户: {最近用户输入摘要}
- Agent: {最近Agent回复摘要}
```

### 压缩后的消息结构

```python
[
    # 1. System Prompt (保留)
    {"role": "system", "content": "..."},

    # 2. 压缩摘要 (替代中间历史)
    {"role": "system", "content": "## 此前对话摘要\n..."},

    # 3. 保留的最近对话 (完整保留)
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},

    # 4. 当前请求
    {"role": "user", "content": "..."},
]
```

---

## 5. 整体架构升级图

```
┌─────────────────────────────────────────────────────────────┐
│                         用户交互层                            │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │   CLI/接口   │  │ Human-in-the-Loop │  │ 意图澄清对话  │  │
│  └──────────────┘  └──────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      意图处理层                               │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────┐ │
│  │ Intent Parser   │─►│ Intent Clarifier │─►│ Query Merge │ │
│  │  (意图解析)      │  │  (缺失信息检测)   │  │ (合并确认)   │ │
│  └─────────────────┘  └──────────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      记忆管理层                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Working Mem  │  │ Session Mem  │  │ Long-term Mem    │  │
│  │ (短期缓存)    │  │ (会话状态)    │  │ (用户偏好/历史)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent                         │
│              (上下文压缩感知的主控Agent)                       │
│                    ┌─────────────────┐                      │
│                    │ Context Compactor│  (80%触发自动压缩)   │
│                    └─────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐
│ Sub-Agents  │     │  RAG系统    │     │   Tool Use系统      │
│ (上下文隔离) │     │             │     │                     │
│             │     │ ┌─────────┐ │     │ ┌─────────────────┐ │
│ MarketAgent │◄────┤│ Multimodal│ │     │ │ Web Search      │ │
│ IndustryAgent│    ││ Pipeline │ │     │ │ AKShare Data    │ │
│ CompanyAgent │    ││ (Text/   │ │     │ │ LLM Call        │ │
│ FinancialRAG │    ││ Table/   │ │     │ │ Embedding       │ │
│              │    ││ Image)   │ │     │ └─────────────────┘ │
└─────────────┘    │└─────────┘ │     └─────────────────────┘
                    └─────────────┘
```

---

## 6. 实施计划

### Phase A: Human-in-the-Loop (优先级: P0)
- `core/intent_clarifier.py` - 意图澄清模块
- 修改 `core/orchestrator.py` - 集成意图检查
- 添加缺失信息检测规则库

### Phase B: 记忆系统 (优先级: P0)
- `memory/` 模块完整实现
- `memory/session_store.py` - SQLite会话存储
- `memory/long_term_store.py` - 向量+结构化长期存储
- 修改所有Agent集成记忆读写

### Phase C: 上下文压缩 (优先级: P1)
- `core/context_compactor.py` - 压缩引擎
- 修改 `core/agent.py` - 每次LLM调用前检查token用量
- 压缩摘要模板和策略

### Phase D: 多模态处理 (优先级: P1)
- `rag/multimodal/` 模块
- PDF图表检测与提取
- VLM图表理解Pipeline
- 多模态embedding统一

---

## 待确认事项

1. **Human-in-the-Loop**: 最多允许几轮澄清？默认基于推断继续还是必须确认？
2. **VLM模型**: 使用GPT-4V（云端）还是本地部署Qwen-VL等开源模型？
3. **记忆存储**: 长期记忆是否使用项目的ChromaDB，还是单独的数据库？
4. **上下文压缩**: 80%阈值是否合适？是否需要在配置中可调？
5. **多模态优先级**: 先支持PDF图表还是HTML网页图表？
