# DeepResearch PWS 重构进度

## 已完成的架构改造

### 核心基础设施 (Phase 1)
- [x] `core/finding.py` — Finding + Source 结构化中间结果
- [x] `core/research_plan.py` — ResearchPlan + TaskNode + DAGScheduler (并行调度)
- [x] `core/worker.py` — GenericWorker 通用子Agent (role-based prompts)
- [x] `core/context_manager.py` — TokenBudget + 上下文压缩 (synthesizer 层已接入)

### Planner + Orchestrator (Phase 2)
- [x] `core/planner.py` — ResearchPlanner (LLM 动态生成 DAG + evaluate 扩展)
- [x] `core/orchestrator.py` — 重写为 PWS 模式 (消除硬编码 pipeline)
- [x] `cli.py` — 移除 register_sub_agent，适配新 Orchestrator
- [x] `config/default.yaml` — 清理旧 agent 配置，更新 orchestrator system_prompt

### 清理旧代码 (Phase 3)
- [x] 删除 `agents/market_agent.py`, `industry_agent.py`, `company_agent.py`
- [x] 保留 `agents/financial_rag_agent.py` (独立能力，当前未被 orchestrator 调用)
- [x] `config/settings.py` — 恢复 agents 配置兼容 skills

### 报告生成 (Phase 4)
- [x] `core/report_generator.py` — 适配 PWS role-based sections

## Bug 修复记录

| 优先级 | 问题 | 修复文件 | 说明 |
|--------|------|----------|------|
| P0 | Worker 解析 ReActAgent 输出丢失 JSON | `worker.py:182-193` | 从 `content["answer"]` 提取 JSON，而非消费整个 dict |
| P1 | `_extract_json_from_text` 括号匹配错误 | `worker.py:201-232` | `rfind` → 栈匹配，正确处理嵌套 JSON 和字符串内括号 |
| P1 | Failed task 永久阻塞下游依赖 | `research_plan.py:66-73` | `get_ready_tasks()` 将 `failed` 状态视为依赖已满足 |
| P2 | Report generator section titles 硬编码 | `report_generator.py:114-130,145-155` | 使用 role→中文动态映射 |
| P2 | Planner evaluate 未使用 findings 参数 | `planner.py:225-226` | 使用传入的 findings 替代 `plan.get_completed_tasks()` |
| P2 | BOM 导致 JSON 解析失败 | `planner.py:125,271`, `intent_clarifier.py:240,392` | `strip().lstrip('\ufeff')` |
| P2 | Orchestrator 未使用导入 | `orchestrator.py` | 已清理多余导入 |

## 测试状态
- [x] 全部 23 个单元测试通过
- [x] DAGScheduler failed-deps 逻辑验证通过
- [x] Worker JSON 提取逻辑验证通过
- [x] Report generator section 渲染验证通过

## 仍存在的问题 / 改进空间

### 未接入的设计（不阻塞运行）
- [x] ContextManager 的 `build_worker_context` 已接入 GenericWorker.execute()，每个 worker 使用独立 TokenBudget
- [ ] ContextManager 的 `build_planner_context` 暂未接入 planner.evaluate()（evaluate prompt 较短，当前手动构建已足够）
- [x] worker.execute() 中已接入 token budget 控制

### 潜在优化
- [x] AKShareTool 内部同步 pandas 调用已包装在 `asyncio.to_thread()` 中
- [x] DuckDuckGo 搜索已包装在 `asyncio.to_thread()` 中
- [x] `core/finding.py` 和 `memory/models.py` 的 `Finding` 命名冲突已解决（memory 侧重命名为 `MemoryFinding`）
- [x] RAGPipeline.generate_answer() 已添加上下文长度截断（MAX_CONTEXT_CHARS=6000）

### 架构演进方向
- [ ] 可将 `FinancialRAGAgent` 的能力（RAGPipeline + QueryRewriter）作为 tool 提供给 GenericWorker
- [ ]  skills（market_analysis, industry_screening, company_selection）当前未被 PWS 使用，可作为 Worker 的 optional skills 接入
