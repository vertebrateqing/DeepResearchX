# DeepResearch 重构进度

## 已完成
- [x] P0 Bug 修复提交 (commit 80513c0)

## Phase 1: 基础设施 (进行中)
- [ ] core/finding.py — Finding + Source 结构化中间结果
- [ ] core/research_plan.py — ResearchPlan + TaskNode + DAGScheduler
- [ ] core/worker.py — GenericWorker 通用子Agent
- [ ] core/context_manager.py — TokenBudget + 上下文压缩

## Phase 2: Planner 集成
- [ ] core/planner.py — ResearchPlanner (plan 生成 + evaluate)
- [ ] 重写 OrchestratorAgent.run() 为 Planner 模式

## Phase 3: Worker 替换
- [ ] 提取现有 agent 的 system_prompt 为 ROLE_PROMPTS
- [ ] 删除 agents/market_agent.py, industry_agent.py, company_agent.py
- [ ] 保留 financial_rag_agent.py 的 RAG pipeline 作为工具

## Phase 4: 报告与记忆
- [ ] Synthesizer 读取所有 Finding 生成报告
- [ ] 报告标注数据来源和置信度
- [ ] ContextManager 接入 Planner 和 Worker

## Phase 5: 测试与调优
- [ ] Planner prompt engineering
- [ ] Worker role prompt tuning
- [ ] Token 预算参数调优
