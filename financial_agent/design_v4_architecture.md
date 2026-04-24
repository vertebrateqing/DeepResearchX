# V4 分层报告生成架构设计

## 1. 架构总览

```
+----------------+     +----------------+     +------------------+
|  User Query    | --> | IntentClarifier| --> | Merged Query     |
|  (已有)        |     | (HITL, 已有)   |     | (确认后)         |
+----------------+     +----------------+     +--------+---------+
                                                         |
+----------------+     +----------------+     +--------v---------+
| ReportGenerator| <-- | EditorAgent    | <-- | IntegrationAgent |
| (MD/PDF, 已有) |     | (润色)         |     | (整合所有章节)   |
+----------------+     +----------------+     +--------+---------+
                                                       ^
+----------------+     +----------------+   +--------|---------+
|  ReviserAgent  | --> | ChapterWorker  |   | 读取所有         |
|  (评审反馈)    |     | (自主研究撰写) |   | chapter_{id}.md |
+-------+--------+     +-------+--------+   +------------------+
        ^                      |
        |   feedback           |
        +----------------------+
                         +-----v----------+
                         | OutlinePlanner |
                         | (制定大纲)     |
                         +----------------+
```

## 2. 详细流程

```
Phase 0: 意图澄清 (已有, 不变)
  输入: 用户原始查询
  输出: merged_query (经 HITL 确认)

Phase 1: 大纲制定 (OutlinePlanner)
  输入: merged_query + 当前日期
  输出: ReportOutline (JSON)
    - title: 报告标题
    - executive_summary_points: 执行摘要要点列表
    - chapters: [
        {
          chapter_id: "c1",
          title: "公司概况与业务分析",
          objective: "...",
          suggested_tools: ["web_search", "data_fetch"],
          word_count: 800,
          depends_on: [],
          key_questions: ["..."]
        }
      ]
  持久化: {session_dir}/outline.json

Phase 2: 章节并行研究 (ChapterWorker, DAGScheduler)
  输入: chapter outline
  流程:
    1. ChapterWorker 接收章节目标 + 关键问题
    2. 自主调用工具 (web_search, data_fetch, doc_analysis) 收集信息
    3. 基于研究结果撰写完整章节 Markdown
    4. 写入: {session_dir}/chapter_{chapter_id}.md
    5. 返回 Finding:
       {
         summary: "章节摘要",
         chapter_id: "c1",
         file_path: ".../chapter_c1.md",
         word_count: 850,
         sources: [...],
         confidence: 0.85
       }

Phase 3: 评审循环 (ReviserAgent)
  输入: chapter_{id}.md + outline 中对应章节要求
  评估维度:
    - research_depth (研究深度): 1-10
    - data_reliability (数据可靠性): 1-10
    - content_safety (内容安全性): 1-10
    - rigor (严谨程度): 1-10
    - formatting (格式规范): 1-10
  输出: ReviewResult
    {
      passed: bool,
      scores: {dimension: score},
      feedback: "具体修改建议",
      action_required: "revise" | "accept"
    }
  循环: 未通过 -> 反馈给 ChapterWorker 修订 -> 重写 chapter_{id}.md
       最多 2 轮修订

Phase 4a: 整合 (IntegrationAgent)
  输入: outline.json + 所有 chapter_{id}.md
  策略: 清空上下文 / 新建 LLMClient 实例（无历史）
  流程:
    1. 读取所有章节文件
    2. 按大纲顺序拼接
    3. 添加章节间过渡段落
    4. 消除跨章节重复内容
    5. 统一术语和引用格式
    6. 写入: {session_dir}/draft.md

Phase 4b: 编辑 (EditorAgent)
  输入: draft.md + outline.json
  评估维度:
    - grammar_style (语法与表达): 1-10
    - factual_consistency (事实一致性): 1-10
    - completeness (报告完整度 vs 大纲): 1-10
    - formatting (格式统一): 1-10
  输出: EditResult
    {
      passed: bool,
      scores: {dimension: score},
      revision_suggestions: ["具体修改建议1", "..."],
      critical_issues: ["必须修正的问题"]
    }
  循环: IntegrationAgent 根据建议修订 draft.md
       最多 2 轮

Phase 5: 输出 (ReportGenerator, 已有)
  输入: 最终 draft.md
  输出: report_{session_id}_{ts}.md + .pdf
```

## 3. Agent Prompt 设计

### 3.1 OutlinePlanner

```
System Prompt:
你是一位资深投研报告规划专家。你的职责是根据用户的研究需求，设计一份专业、结构化的深度分析报告大纲。

要求：
1. 报告大纲必须覆盖用户问题的所有维度
2. 每个章节有明确的 objective（研究目标）和 key_questions（需要回答的核心问题）
3. suggested_tools 从 [web_search, data_fetch, doc_analysis, cross_verify] 中选择
4. word_count 是建议字数，深度研究每章 600-1200 字
5. depends_on 标注章节依赖关系（如"财务分析"依赖"公司概况"）
6. 章节数量：简单分析 3-5 章，深度研究 6-10 章

输出格式（严格JSON）：
{
  "title": "报告标题",
  "executive_summary_points": ["要点1", "要点2"],
  "chapters": [
    {
      "chapter_id": "c1",
      "title": "章节标题",
      "objective": "本章节需要完成的研究目标",
      "suggested_tools": ["web_search", "data_fetch"],
      "word_count": 800,
      "depends_on": [],
      "key_questions": ["问题1", "问题2"]
    }
  ]
}
```

### 3.2 ChapterWorker

```
System Prompt:
你是一位专业的投研分析师，负责撰写分析报告的一个独立章节。

【当前章节】
章节标题: {chapter_title}
研究目标: {objective}
关键问题: {key_questions}
建议字数: {word_count}

工作要求：
1. 你需要自主调用可用工具收集信息（网络搜索、数据获取、文档分析）
2. 基于收集到的信息，撰写完整、专业、有深度的章节内容
3. 内容必须直接回答关键问题，不要泛泛而谈
4. 所有数据必须标注来源，使用 [来源: 标题/URL] 格式
5. 承认信息缺口和不确定性
6. 使用 Markdown 格式，包含必要的小标题、列表、表格
7. 输出必须是完整的 Markdown 文本（不是JSON）

输出格式：
直接输出 Markdown 格式的章节正文，不需要包装在代码块中。
```

### 3.3 ReviserAgent

```
System Prompt:
你是一位资深投研报告质量评审专家。你的职责是审查分析报告的每个章节，确保质量达标。

评审维度（每项 1-10 分）：
1. research_depth (研究深度): 内容是否有深度分析，还是仅停留在表面描述？是否有独到的洞察？
2. data_reliability (数据可靠性): 数据是否有明确来源？是否最新？关键数据是否准确？
3. content_safety (内容安全性): 是否包含违规投资建议？风险提示是否充分？
4. rigor (严谨程度): 逻辑是否自洽？论证是否充分？结论是否有数据支撑？
5. formatting (格式规范): Markdown 格式是否正确？引用格式是否统一？

通过标准：总分 >= 35 且 单项 >= 6

输出格式（严格JSON）：
{
  "passed": true/false,
  "scores": {
    "research_depth": 8,
    "data_reliability": 7,
    "content_safety": 9,
    "rigor": 7,
    "formatting": 8
  },
  "feedback": "具体评审意见和修改建议",
  "action_required": "revise" 或 "accept"
}
```

### 3.4 IntegrationAgent

```
System Prompt:
你是一位资深报告整合专家。你将收到一份报告大纲和多个已完成的章节文件。
你的任务是将这些章节整合为一份连贯、完整的分析报告。

整合要求：
1. 按大纲顺序排列章节
2. 为章节之间添加过渡段落，确保逻辑流畅
3. 消除跨章节的重复内容（合并或删减）
4. 统一全文的术语、格式和引用风格
5. 添加执行摘要（基于大纲中的 executive_summary_points）
6. 在报告末尾添加"数据来源与参考文献"章节
7. 保持各章节的完整内容，不要过度压缩

注意：你是从零开始整合，没有历史对话上下文。所有信息来自提供的章节文件。
```

### 3.5 EditorAgent

```
System Prompt:
你是一位资深财经编辑。你的职责是对完整的分析报告进行最终润色和质量把控。

评估维度（每项 1-10 分）：
1. grammar_style (语法与表达): 语言是否专业、流畅？是否有语病或冗余？
2. factual_consistency (事实一致性): 全文数据是否前后一致？有无自相矛盾？
3. completeness (报告完整度): 是否覆盖了大纲所有要求？有无遗漏章节？
4. formatting (格式统一): 标题层级、引用格式、表格样式是否统一？

通过标准：总分 >= 28 且 单项 >= 6

输出格式（严格JSON）：
{
  "passed": true/false,
  "scores": {
    "grammar_style": 8,
    "factual_consistency": 9,
    "completeness": 8,
    "formatting": 7
  },
  "revision_suggestions": ["建议1", "建议2"],
  "critical_issues": ["必须修正的问题1"]
}
```

## 4. 数据流与文件 I/O 契约

```
session_dir = ./financial_agent/data/sessions/{session_id}/

文件清单：
- {session_dir}/outline.json          # Phase 1 输出
- {session_dir}/chapter_c1.md         # Phase 2 输出
- {session_dir}/chapter_c2.md
- ...
- {session_dir}/reviews.json          # Phase 3 输出 (所有评审记录)
- {session_dir}/draft.md              # Phase 4a 输出
- {session_dir}/edits.json            # Phase 4b 输出 (编辑评审记录)
- {output_dir}/report_{session_id}_{ts}.md   # Phase 5 输出
- {output_dir}/report_{session_id}_{ts}.pdf  # Phase 5 输出

Finding 扩展字段：
class ChapterFinding(Finding):
    chapter_id: str
    file_path: str
    word_count: int
    review_passed: bool = False
    review_rounds: int = 0
```

## 5. 关键改动点

| 模块 | 改动类型 | 说明 |
|------|---------|------|
| core/outline_planner.py | 新增 | OutlinePlanner 类 |
| core/chapter_worker.py | 新增 | ChapterWorker 类（替代 GenericWorker） |
| core/reviser.py | 新增 | ReviserAgent 类 |
| core/integration.py | 新增 | IntegrationAgent 类 |
| core/editor.py | 新增 | EditorAgent 类 |
| core/orchestrator.py | 修改 | _execute_research() 改为 V4 五阶段流程 |
| core/finding.py | 修改 | 扩展 Finding 支持 chapter 相关字段 |
| core/context_manager.py | 修改 | 增大 synthesizer_budget |
| config/default.yaml | 修改 | 新增 outline / chapter 相关配置 |

## 6. 实现 TODO

- [ ] Task 1: 创建 OutlinePlanner 类及 prompt
- [ ] Task 2: 创建 ChapterWorker 类（自主研究+撰写）
- [ ] Task 3: 创建 ReviserAgent 类及评审循环
- [ ] Task 4: 创建 IntegrationAgent 类（整合章节）
- [ ] Task 5: 创建 EditorAgent 类及润色循环
- [ ] Task 6: 扩展 Finding 数据模型
- [ ] Task 7: 重构 Orchestrator 使用 V4 流程
- [ ] Task 8: 更新配置（budget、timeout 等）
- [ ] Task 9: 端到端测试验证
