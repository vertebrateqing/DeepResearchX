# DeepResearch 架构重构方案 V1

## 一、当前架构的核心问题

### 1.1 硬编排耦合

```
当前流程（写死）：
  run_full_analysis()
    → Phase 1: market_analysis + industry_screening (并行)
    → Phase 2: company_selection (串行)
    → Phase 3: financial_rag (串行)
    → Phase 4: synthesize_report
```

- 每个 sub-agent 的类名、system_prompt、调用顺序全部硬编码
- 新增一个 agent 需要修改 orchestrator 的 5+ 处代码
- sub-agent 无法根据自身角色自主决策下一步，只是被动接收 orchestrator 的命令

### 1.2 缺乏真正的 ReAct 范式

当前 ReAct 只体现在单个 sub-agent 内部（LLM 调用工具），但跨 agent 协作是**预编排**的，而非**自主规划**的。真正的 multi-agent ReAct 应该是：

```
Planner (主Agent) 自主决定:
  - 需要哪些信息？
  - 拆分成什么子任务？
  - 哪些可以并行？哪些有依赖？
  - 结果是否充分？是否需要补充调研？
```

### 1.3 角色固化

```python
# 当前：角色 = 类名
class MarketAnalysisAgent(ReActAgent): ...
class IndustryScreeningAgent(ReActAgent): ...
class CompanySelectionAgent(ReActAgent): ...
```

每个角色一个类，system_prompt 写在 class 定义里。这导致：
- 无法动态调整 sub-agent 的职责边界
- 无法根据任务需求组合能力（如一个 agent 既要搜索又要分析数据）
- 新增角色需要新建类文件

### 1.4 上下文膨胀

当前所有 sub-agent 的结果摘要通过字符串拼接传给最终 synthesizer，没有任何 token 预算控制。deepresearch 场景下：
- 10+ 次 web search 结果
- 多份财报数据
- 行业对比表格
轻松超过 8K-16K token 上下文窗口。

---

## 二、新架构：Planner-Worker-Synthesizer (PWS)

```
┌─────────────────────────────────────────────────────────────┐
│                        User Query                            │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Planner Agent (主控)                                        │
│  - 分析用户意图                                              │
│  - 生成 Research Plan (任务DAG)                              │
│  - 评估中间结果，决定是否需要补充调研                          │
│  - 最终调用 Synthesizer 生成报告                              │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Task Scheduler (DAG Executor)                   │
│  - 拓扑排序确定执行顺序                                       │
│  - 无依赖的任务并行调度                                       │
│  - 有依赖的任务等待前置完成                                   │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Generic Worker Pool (Sub-Agents)                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Worker #1    │  │ Worker #2    │  │ Worker #3    │      │
│  │ role=search  │  │ role=data    │  │ role=analyze │      │
│  │ 搜索比亚迪   │  │ 获取财务数据 │  │ 分析毛利率   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │ Worker #4    │  │ Worker #5    │                         │
│  │ role=search  │  │ role=verify  │                         │
│  │ 搜索行业趋势 │  │ 交叉验证数据 │                         │
│  └──────────────┘  └──────────────┘                         │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Finding Store (中间结果池)                       │
│  - 每个 Worker 输出结构化 Finding (JSON)                      │
│  - 按 task_id 索引，带置信度和来源                             │
│  - Planner 可随时读取评估                                     │
└─────────────────────────┬───────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Synthesizer Agent (报告生成)                                │
│  - 读取全部 Finding + 用户原始需求                            │
│  - 生成结构化 Markdown 报告                                   │
│  - 标注数据来源和置信度                                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 核心设计原则

| 原则 | 说明 |
|------|------|
| **Planner 拥有唯一决策权** | 只有 Planner 能创建/调度任务，Worker 只执行不决策 |
| **Worker 完全通用** | 所有 Worker 是同一个类，通过动态提示词赋予不同角色 |
| **任务即数据** | Research Plan 是结构化数据（JSON/DAG），不是代码逻辑 |
| **结果即 Finding** | Worker 输出必须是结构化 Finding，不是自由文本 |
| **上下文分层** | Planner 只看 Finding 摘要，Worker 只看自己的任务输入 |

---

## 三、核心组件设计

### 3.1 Planner Agent

Planner 的职责是"做什么"和"什么时候做"，不是"怎么做"。

```python
class ResearchPlanner:
    """Generates and manages research plans."""

    async def plan(self, user_query: str, context: dict) -> ResearchPlan:
        """Generate initial research plan from user query."""
        # LLM call with structured output (JSON mode / function calling)
        pass

    async def evaluate(self, plan: ResearchPlan, findings: list[Finding]) -> PlanUpdate:
        """Evaluate if findings are sufficient, suggest new tasks if needed."""
        pass
```

**Planning Prompt 核心指令**：

```
你是一个研究规划专家。请根据用户需求，设计一份深度调研计划。

用户需求：{user_query}

要求：
1. 将调研拆分为多个子任务，每个子任务有明确的 role 和 goal
2. role 只能从以下选择：[web_search, data_fetch, doc_analysis, cross_verify, synthesis]
3. 标注任务依赖关系（哪些任务可以并行，哪些必须串行）
4. 每个子任务只负责获取/分析一小部分信息
5. 不要在一个任务里混合太多目标

输出格式（JSON）：
{
  "tasks": [
    {
      "task_id": "t1",
      "role": "web_search",
      "goal": "搜索比亚迪2025年财报核心数据",
      "depends_on": [],
      "estimated_tokens": 2000
    },
    ...
  ],
  "overall_strategy": "先获取数据，再交叉验证，最后综合分析"
}
```

### 3.2 Generic Worker (统一 Sub-Agent)

```python
class GenericWorker(ReActAgent):
    """通用 Worker，通过动态 system_prompt 扮演不同角色。"""

    ROLE_PROMPTS: dict[str, str] = {
        "web_search": """你是一个信息检索专家。...""",
        "data_fetch": """你是一个数据获取专家，擅长从结构化数据源提取信息。...""",
        "doc_analysis": """你是一个文档分析专家，擅长从财报/研报中提取关键信息。...""",
        "cross_verify": """你是一个事实核查专家，擅长交叉验证多个来源的信息一致性。...""",
        "synthesis": """你是一个综合分析专家，擅长将多个信息源整合为连贯结论。...""",
    }

    def __init__(self, task: TaskNode):
        role_prompt = self.ROLE_PROMPTS[task.role]
        # 动态注入任务专属上下文
        system_prompt = f"""{role_prompt}

【当前任务】
目标：{task.goal}
任务ID：{task.task_id}

【要求】
1. 专注完成当前任务目标，不要偏离
2. 输出必须是结构化数据，不要自由发挥
3. 如果信息不足，明确说明缺失了什么
4. 标注你使用的数据来源
"""
        super().__init__(system_prompt=system_prompt)
        self.task = task

    async def execute(self, inputs: dict) -> Finding:
        """Execute task and return structured finding."""
        # Run ReAct loop with tools
        result = await self.run(task.goal, inputs)
        # Parse result into Finding
        return Finding.from_agent_result(result, self.task.task_id)
```

**关键设计**：Worker 不知道自己是什么"业务 agent"（market/industry/company），它只知道自己的**角色能力**（search/data/analyze）和**当前任务目标**。这让 Worker 完全通用化。

### 3.3 Task DAG (有向无环图)

```python
@dataclass
class TaskNode:
    task_id: str
    role: str  # web_search | data_fetch | doc_analysis | cross_verify | synthesis
    goal: str
    depends_on: list[str]  # task_id list
    inputs: dict  # 静态输入参数
    status: str = "pending"  # pending | running | completed | failed
    output: Finding | None = None
    retry_count: int = 0

@dataclass
class ResearchPlan:
    plan_id: str
    user_query: str
    tasks: list[TaskNode]
    strategy: str = ""  # 整体策略说明

    def get_ready_tasks(self) -> list[TaskNode]:
        """Get tasks whose dependencies are all completed."""
        completed_ids = {t.task_id for t in self.tasks if t.status == "completed"}
        return [
            t for t in self.tasks
            if t.status == "pending"
            and all(dep in completed_ids for dep in t.depends_on)
        ]

    def is_complete(self) -> bool:
        return all(t.status in ("completed", "failed") for t in self.tasks)
```

### 3.4 DAG Scheduler

```python
class DAGScheduler:
    """Executes research plan with parallelism."""

    async def execute(self, plan: ResearchPlan) -> list[Finding]:
        """Execute plan until completion."""
        while not plan.is_complete():
            ready = plan.get_ready_tasks()
            if not ready:
                # Deadlock or all failed
                break

            # Execute ready tasks in parallel
            results = await asyncio.gather(
                *[self._run_task(t) for t in ready],
                return_exceptions=True,
            )

            # Update task status
            for task, result in zip(ready, results):
                if isinstance(result, Exception):
                    task.status = "failed"
                    task.retry_count += 1
                    if task.retry_count < MAX_RETRIES:
                        task.status = "pending"  # Will be retried
                else:
                    task.status = "completed"
                    task.output = result

        return [t.output for t in plan.tasks if t.output]

    async def _run_task(self, task: TaskNode) -> Finding:
        """Run a single task with a Worker."""
        worker = GenericWorker(task)
        # Build inputs: static inputs + outputs from dependencies
        inputs = self._build_inputs(task)
        return await worker.execute(inputs)
```

### 3.5 Finding (结构化中间结果)

```python
@dataclass
class Finding:
    """Structured output from a Worker."""

    task_id: str
    role: str
    summary: str  # 100-200 字摘要（给 Planner 看的）
    details: dict  # 完整结构化数据
    sources: list[Source]  # 数据来源
    confidence: float  # 0-1
    timestamp: datetime

    def to_planner_context(self) -> str:
        """Convert to brief string for Planner context."""
        return f"[{self.role}] {self.summary} (置信度: {self.confidence:.0%})"

@dataclass
class Source:
    type: str  # web | akshare | report | calculation
    url: str = ""
    title: str = ""
    accessed_at: datetime = field(default_factory=datetime.now)
```

**关键设计**：Worker 输出**两份内容**：
- `summary`：给 Planner 看的简短摘要（100-200 字）
- `details`：完整结构化数据（给最终 Synthesizer 用的）

这样 Planner 做 evaluate 时不会被海量细节淹没。

### 3.6 上下文/记忆管理

```
上下文分层：

Layer 1: Planner Context (最紧凑)
  - 用户原始 query
  - Research Plan 当前状态
  - 每个已完成任务的 Finding.summary
  - Token 预算: ~2000 tokens

Layer 2: Worker Context (中等)
  - 当前 task.goal
  - 依赖任务的 Finding.details (按需加载)
  - 工具调用历史
  - Token 预算: ~4000 tokens

Layer 3: Finding Store (完整数据)
  - 所有 Finding.details (JSON)
  - 不在任何 LLM 上下文中，只在内存/持久化中
  - Synthesizer 读取时按需选择
```

**上下文压缩策略**：

1. **Worker 输出即压缩**：Worker 完成任务后自己生成 summary，Planner 永远只看 summary
2. **Planner 轮次压缩**：每轮 evaluate 后，旧的 plan + findings 被压缩为 "round_summary"，只保留关键结论
3. **Token 预算监控**：每层都有 max_tokens，超过时自动触发压缩
4. **任务隔离**：Worker 之间不共享上下文，只通过 Finding 传递数据

```python
class ContextManager:
    """Manages token budget and automatic compression."""

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.budget = TokenBudget(max_tokens)

    def add(self, content: str) -> str | None:
        """Add content, return compressed version if over budget."""
        tokens = self.budget.count(content)
        if self.budget.remaining >= tokens:
            self.budget.consume(tokens)
            return content

        # Over budget — need to compress
        return self._compress(content, self.budget.remaining)

    def _compress(self, content: str, target_tokens: int) -> str:
        """Use LLM to compress content while preserving key info."""
        # Or use simple truncation with ellipsis
        pass
```

---

## 四、完整执行流程

```
User: "分析比亚迪002594的2025年财报"
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 1: Intent Clarifier                        │
│ - 确认是否需要澄清（股票代码已明确 → 无需澄清）   │
│ - 注入当前日期上下文                             │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 2: Planner.generate_plan()                 │
│ LLM 输出 ResearchPlan:                          │
│ {                                               │
│   tasks: [                                      │
│     {task_id: "t1", role: "data_fetch",         │
│      goal: "获取比亚迪002594最新财务指标", ...}, │
│     {task_id: "t2", role: "web_search",         │
│      goal: "搜索比亚迪2025年报分析师解读", ...}, │
│     {task_id: "t3", role: "web_search",         │
│      goal: "搜索新能源车企2025年竞争格局", ...}, │
│     {task_id: "t4", role: "doc_analysis",       │
│      goal: "分析比亚迪毛利率和净利率变化趋势",    │
│      depends_on: ["t1"]},                       │
│     {task_id: "t5", role: "cross_verify",       │
│      goal: "交叉验证财务数据与分析师预测一致性",  │
│      depends_on: ["t1", "t2"]},                 │
│     {task_id: "t6", role: "synthesis",          │
│      goal: "生成投资建议",                       │
│      depends_on: ["t3", "t4", "t5"]}            │
│   ]                                             │
│ }                                               │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 3: DAGScheduler.execute()                  │
│ Round 1 (并行): t1, t2, t3 同时执行             │
│   - Worker(data_fetch) → 获取 AKShare 数据      │
│   - Worker(web_search) → Tavily 搜索财报解读     │
│   - Worker(web_search) → Tavily 搜索行业格局     │
│ Round 2 (并行): t4, t5 同时执行（依赖已满足）    │
│   - Worker(doc_analysis) → 分析财务趋势          │
│   - Worker(cross_verify) → 交叉验证              │
│ Round 3 (串行): t6 执行                         │
│   - Worker(synthesis) → 生成投资建议             │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 4: Planner.evaluate()                      │
│ - 检查 findings 是否充分                         │
│ - 如果某方面信息薄弱，追加 task                  │
│ - 例如：发现缺少比亚迪海外业务数据 → 追加搜索任务 │
└─────────────────────────────────────────────────┘
  │
  ▼ (若无需补充)
┌─────────────────────────────────────────────────┐
│ Step 5: Synthesizer.generate_report()           │
│ - 读取所有 Finding.details                       │
│ - 按报告结构组织内容                             │
│ - 生成 Markdown + PDF                           │
└─────────────────────────────────────────────────┘
```

---

## 五、与现有代码的映射关系

| 现有组件 | 新架构对应 | 说明 |
|---------|-----------|------|
| `OrchestratorAgent` | `PlannerAgent` + `DAGScheduler` | 从硬编码流程变为动态规划+调度 |
| `MarketAnalysisAgent` | `GenericWorker(role="web_search")` + `GenericWorker(role="data_fetch")` | 市场分析 = 搜索市场数据 + 获取指数数据 |
| `IndustryScreeningAgent` | `GenericWorker(role="web_search")` + `GenericWorker(role="data_fetch")` | 行业分析 = 搜索行业资讯 + 获取行业数据 |
| `CompanySelectionAgent` | `GenericWorker(role="doc_analysis")` | 公司分析 = 分析基本面数据 |
| `FinancialRAGAgent` | `GenericWorker(role="data_fetch")` + `GenericWorker(role="doc_analysis")` | 财报分析 = 获取财务数据 + 深度分析 |
| `ReportGenerator` | `SynthesizerAgent` + `ReportGenerator` | 专门负责最终报告生成 |
| `MemoryManager` | `ContextManager` + `FindingStore` | 分层上下文管理 |
| `IntentClarifier` | 保留，作为 Planner 的前置 | 澄清逻辑不变，仍由 LLM 全权负责 |

---

## 六、实施路线图

### Phase 1: 基础设施（1-2 天）
- [ ] 创建 `core/planner.py`：ResearchPlan + TaskNode + DAGScheduler
- [ ] 创建 `core/worker.py`：GenericWorker（统一 sub-agent）
- [ ] 创建 `core/finding.py`：Finding + Source 数据模型
- [ ] 创建 `core/context_manager.py`：TokenBudget + 压缩策略

### Phase 2: Planner 集成（1-2 天）
- [ ] 实现 Planner.generate_plan() 的 LLM 调用 + JSON 解析
- [ ] 实现 Planner.evaluate() 的自评估逻辑
- [ ] 实现 DAGScheduler 的并行执行
- [ ] 重写 OrchestratorAgent.run() 为 Planner 模式

### Phase 3: Worker 替换（1 天）
- [ ] 将现有 4 个 sub-agent 的 system_prompt 提取为 ROLE_PROMPTS
- [ ] 删除 `agents/market_agent.py`、`agents/industry_agent.py` 等具体类
- [ ] 保留 `agents/financial_rag_agent.py` 中的 RAG pipeline，作为 data_fetch 角色的工具

### Phase 4: 报告与记忆（1 天）
- [ ] Synthesizer 读取所有 Finding 生成报告
- [ ] 报告标注数据来源和置信度
- [ ] ContextManager 接入 Planner 和 Worker

### Phase 5: 测试与调优（持续）
- [ ] Planner prompt engineering（确保生成的 plan 合理）
- [ ] Worker role prompt tuning
- [ ] Token 预算参数调优

---

## 七、风险评估

| 风险 | 缓解措施 |
|------|---------|
| Planner 生成的 plan 不合理 | 增加 plan validation（检查 role 合法性、依赖无环） |
| LLM 输出不符合 JSON schema | 使用 function calling / JSON mode；增加 retry + fallback |
| Worker 执行失败导致整个 plan 失败 | 单个 task 失败不阻塞其他 task；支持 retry 和跳过 |
| 并行 Worker 过多导致 API 限流 | Scheduler 增加并发控制（max_parallel_workers） |
| Context 仍可能溢出 | 多级压缩策略；超限时 gracefully degrade（截断而非崩溃） |

---

## 八、总结

新架构的核心变化：

1. **从"类名决定角色" → "动态提示词决定角色"**：不再为每个业务场景建一个类，而是用一个 GenericWorker + 动态 system_prompt
2. **从"写死流程" → "Planner 自主规划"**：Planner 根据用户请求生成任务 DAG，Scheduler 负责拓扑执行
3. **从"字符串传递" → "结构化 Finding 传递"**：Worker 输出结构化数据，Planner 只看摘要，Synthesizer 按需读取详情
4. **从"单层上下文" → "分层上下文管理"**：Planner/Worker/Synthesizer 各自有独立的 token 预算和压缩策略

这个设计让系统从一个"预编排的剧本"变成一个"自主规划的研究团队"，符合 deepresearch 的范式。
