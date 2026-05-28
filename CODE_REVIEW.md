# DeepResearchX 代码审查报告

> 审查标准：高质量开源社区项目（FastAPI、LangChain、LlamaIndex 级别）
> 审查范围：`backend/` 全量代码
> 审查日期：2026-05-27

## 执行摘要

| 维度 | 评分 | 关键问题 |
|------|------|---------|
| 架构设计 | C+ | 抽象层次合理，但核心 Pipeline 缺乏可测试性设计 |
| 代码质量 | C | 51 处 bare `except Exception`，大量重复解析逻辑，硬编码 prompt |
| 安全性 | D | **路径遍历漏洞**，无输入消毒，敏感信息可能泄露 |
| 性能 | B- | async/await 使用基本正确，但缺乏超时和背压控制 |
| 测试覆盖 | F | 核心 Pipeline（orchestrator/outline/reviser/editor）**零测试** |
| 工程规范 | D | 无 CI/CD，mypy 未启用严格模式，无预提交钩子 |

---

## Critical（必须立即修复）

### CR-1: 路径遍历攻击漏洞（Path Traversal）

**位置**：`api/streaming.py:88` → `deep_research/core/orchestrator.py:157`

**问题**：
```python
# api/streaming.py:85-88
session_id=session_id,  # 用户从 Query 参数传入

# orchestrator.py:157
return Path("./deep_research/data/sessions") / self.memory.session_id
```

`/analyze/stream` 端点允许用户传入任意 `session_id`，该值未经消毒直接用于文件路径拼接。攻击者可传入 `../../../etc/passwd` 将报告写入系统任意目录，或读取其他会话的敏感数据。

**对比**：`api/documents.py:55-61` 已实现了 `_validate_session()` 做字符过滤（`/` `\` `..`），但 streaming 端点完全未复用该验证。

**修复方案**：
```python
# 在 api/streaming.py 中复用 documents.py 的验证逻辑
from api.documents import _validate_session

# analyze_stream() 中
if session_id:
    session_id = _validate_session(session_id)
```

同时，在 `orchestrator.py:157` 增加防御性校验：
```python
@property
def session_dir(self) -> Path:
    sid = self.memory.session_id
    if any(c in sid for c in "/\\.."):
        raise ValueError(f"Invalid session_id: {sid}")
    path = Path("./deep_research/data/sessions") / sid
    # 确保解析后的路径仍在基目录内
    if not str(path.resolve()).startswith(str(Path("./deep_research/data/sessions").resolve())):
        raise ValueError(f"Session directory escape detected: {path}")
    return path
```

---

### CR-2: 核心 Pipeline 零单元测试

**位置**：`tests/unit/test_core.py` 及整个 `tests/` 目录

**问题**：
- `test_core.py` 只测试了 `Message`、`Registry`、`BaseAgent` 等**基础设施**
- **`orchestrator.py`**（460+ 行核心编排逻辑）—— **零测试**
- **`outline_planner.py`**（生成大纲，刚改造为 ReAct）—— **零测试**
- **`reviser.py`**（质量评审循环）—— **零测试**
- **`editor.py`**（编辑润色循环）—— **零测试**
- **`integration.py`**（章节合并）—— **零测试**
- **`chapter_worker.py`** —— 仅有极少量测试

**影响**：任何对核心流程的改动都无法通过自动化测试验证正确性，完全依赖人工端到端测试。这在开源项目中是不可接受的。

**修复方案**：
1. 为核心模块编写单元测试，使用 `pytest-asyncio` + `unittest.mock`：
   ```python
   # 示例：outline_planner 测试
   @pytest.mark.asyncio
   async def test_outline_planner_research_phase_timeout():
       planner = OutlinePlanner()
       # Mock research agent to simulate timeout
       planner.research_agent.run_research = AsyncMock(return_value="")
       outline = await planner.generate_outline("test query")
       assert outline is not None  # Should fallback gracefully
   ```
2. 使用 `aioresponses` 或 mock LLM client 来避免真实 API 调用
3. 目标覆盖率：核心 pipeline 模块 ≥ 70%

---

### CR-3: 全局内存存储 `_task_store` 无并发控制

**位置**：`api/streaming.py:29`

**问题**：
```python
_task_store: dict[str, dict] = {}  # 全局变量，无锁
```

在 Gunicorn + Uvicorn 多 worker 部署下，多个进程各自拥有独立的 `_task_store` 副本，导致：
- 任务状态查询可能返回 404（查询到了不同 worker）
- 内存泄漏（任务完成后无人清理）
- 生产环境完全不可用

**修复方案**：
```python
# 短期：使用线程锁（仅单进程有效）
import threading
_task_store: dict[str, dict] = {}
_task_store_lock = threading.Lock()

# 长期：使用 Redis / 数据库
# settings.py 中增加：
# task_backend: Literal["memory", "redis"] = "memory"
```

---

### CR-4: 51 处 bare `except Exception` 静默吞错误

**位置**：全项目分布（`deep_research/tools/` 最为严重）

**问题示例**：
```python
# deep_research/core/agent.py:319
try:
    result = await self.call_tool(tool_name, tool_args)
except Exception:  # ← 吞掉了所有异常，包括编程错误
    result = {"error": str(e)}
```

这会导致：
- **编程错误被隐藏**：`AttributeError`、`TypeError` 等本应在开发阶段暴露的 bug 被静默处理
- **调试困难**：生产环境出现问题时，没有堆栈信息
- **数据丢失**：工具调用失败但上层以为成功

**修复方案**：
1. 区分**预期异常**和**编程错误**：
   ```python
   # 预期异常（网络超时、API 限流）
   except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
       logger.warning(f"Tool timeout: {e}")
       result = {"error": f"Timeout: {e}"}
   
   # 编程错误（不应该被吞）
   # 不要 bare except，让上层处理或崩溃
   ```
2. 启用 ruff 规则 `BLE001`（bare-except）强制检查
3. 逐步替换全项目 51 处 bare except

---

## Major（强烈建议修复）

### MJ-1: `asyncio.gather(return_exceptions=True)` 异常处理不完整

**位置**：`orchestrator.py:509`, `orchestrator.py:566`

**问题**：
第 509 行的处理是正确的（循环中检查 `isinstance(result, Exception)`），但第 566 行的 `revision_results` 处理有问题：
```python
# 566 行：revision 失败后只设置 review_passed=False
if isinstance(result, Exception):
    logger.error(f"Revision failed: {result}")
    finding.details["review_passed"] = False
```

revision 失败意味着该章节质量未经验证，但流程继续执行，不健康的章节会被直接合并到最终报告中。

**修复方案**：
```python
# 增加失败标记，在最终报告中注明
failed_revisions = []
for result, finding in zip(revision_results, chapter_findings):
    if isinstance(result, Exception):
        finding.details["review_passed"] = False
        finding.details["revision_error"] = str(result)
        failed_revisions.append(finding.task_id)

if failed_revisions:
    logger.warning(f"Chapters with failed revision: {failed_revisions}")
```

---

### MJ-2: 无 CI/CD 流水线

**问题**：`.github/workflows/` 目录不存在。

**影响**：
- 无自动化测试（PR 合并前无法确认是否破坏现有功能）
- 无自动化代码风格检查（ruff/mypy）
- 无自动化安全扫描（bandit, safety）
- 无自动化发布流程

**修复方案**：
```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy deep_research/ api/ --strict
      - run: uv run pytest --cov=deep_research --cov-report=xml
      - run: uv run bandit -r deep_research/
```

---

### MJ-3: mypy 未启用严格模式

**位置**：`pyproject.toml:116-119`

**当前配置**：
```toml
[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
```

**问题**：缺少 `strict = true`，导致：
- `Optional` 返回值不强制检查 None
- 未类型化的函数不报错
- 大量 `Any` 滥用不被检测

**修复方案**：
```toml
[tool.mypy]
python_version = "3.10"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
```

然后逐步修复类型错误（可先在 CI 中设为 `continue-on-error: true`）。

---

### MJ-4: 重复的 JSON 解析逻辑

**位置**：
- `outline_planner.py:345-395`（`_parse_outline`）
- `intent_clarifier.py:350-400`
- `reviser.py:140-180`
- `editor.py:315-360`
- `chapter_worker.py:120-160`

**问题**：几乎每个 agent 模块都有独立的 JSON 解析/修复逻辑，包括：
- 提取 markdown code block 中的 JSON
- 修复未转义的控制字符
- 替换中文引号
- 提取最外层 `{}`

这些逻辑高度重复，维护成本高（修复一个解析 bug 需要改 5 个地方）。

**修复方案**：
```python
# deep_research/utils/json_parser.py
class RobustJSONParser:
    """Centralized JSON parsing with multiple fallback strategies."""
    
    @staticmethod
    def parse(text: str) -> dict | None:
        # 统一实现所有解析策略
        ...
```

然后各模块统一调用：
```python
from deep_research.utils.json_parser import RobustJSONParser

data = RobustJSONParser.parse(content)
```

---

### MJ-5: System Prompt 硬编码在 Python 文件中

**位置**：
- `outline_planner.py:105-148`（~120 行中文 prompt）
- `intent_clarifier.py:90-140`
- `reviser.py:50-90`
- `editor.py:60-110`
- `chapter_worker.py:80-130`

**问题**：
- 修改 prompt 需要改代码、重新部署
- 无法让非技术人员（如产品经理）调整 prompt
- 不同环境的 prompt 无法差异化配置
- 版本控制混乱（prompt 微调产生大量无意义的代码提交）

**修复方案**：
```yaml
# config/prompts/outline_planner.yaml
system_prompt: |
  你是一位资深研究报告规划专家...

# outline_planner.py
from deep_research.config.prompts import load_prompt

OUTLINE_SYSTEM_PROMPT = load_prompt("outline_planner")
```

或使用 Pydantic-Settings 管理：
```python
class PromptSettings(BaseSettings):
    outline_planner_system: str = Field(default_factory=lambda: load_prompt("outline_planner"))
```

---

### MJ-6: `progress_callback` 异常被静默吞掉

**位置**：`orchestrator.py:145-149`

```python
try:
    self.progress_callback(event_type, payload)
except Exception:
    pass  # ← 完全静默
```

**问题**：回调函数（如 SSE 推送）失败时没有任何日志，前端可能收不到状态更新但后端认为已发送。

**修复方案**：
```python
try:
    self.progress_callback(event_type, payload)
except Exception:
    logger.exception("Progress callback failed")  # 至少记录错误
```

---

### MJ-7: `_fix_json_string_escapes` 使用字符级状态机过于复杂

**位置**：`outline_planner.py:236-273`

**问题**：手写字符级状态机处理 JSON 字符串转义，代码复杂（40+ 行），容易出错。

**修复方案**：使用标准库 `json` 的 `JSONDecoder.raw_decode` 或第三方库 `json_repair`：
```python
# 方案 A：使用 json_repair 库
try:
    import json_repair
    data = json_repair.loads(content)
except ImportError:
    # fallback to current implementation
```

---

### MJ-8: `web_search.py` 和 `web_scraper.py` 缺乏请求超时控制

**位置**：`tools/web_search.py:131`, `tools/web_scraper.py:215`

**问题**：`except Exception` 捕获了超时异常但未设置合理的超时值。某些外部请求可能无限挂起。

**修复方案**：
```python
# httpx.AsyncClient 已配置 timeout，但工具级别的超时也需要
async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.get(url)
```

---

## Minor（建议优化）

### MN-1: 魔法数字散落

**位置**：全项目

| 魔法数字 | 位置 | 建议 |
|---------|------|------|
| `max_iterations=5` / `8` / `10` | `agent.py`, `outline_planner.py` | 提取到配置类 `AgentSettings` |
| `MAX_REVISION_ROUNDS = 2` | `reviser.py:28` | 配置化 |
| `MAX_EDIT_ROUNDS = 2` | `editor.py:28` | 配置化 |
| `max_tokens=8192` | `outline_planner.py`, `chapter_worker.py` | 配置化 |
| `word_count` 上限 2000 | `outline_planner.py:127` | 配置化 |
| `RESEARCH_TIMEOUT_SECONDS = 60` | `outline_planner.py:280` | 已较好，但可考虑配置化 |

### MN-2: 中英文文档混合

**问题**：部分文件使用中文 docstring（如 `streaming.py`、`router.py`），部分使用英文（如 `outline_planner.py`）。建议统一为英文（开源项目标准）。

### MN-3: `import re` 在函数内部

**位置**：`outline_planner.py:244`、`_parse_outline` 内部

**问题**：函数内导入 `re` 模块没有必要（导入开销极小），且降低了代码可读性。应移到模块顶部。

### MN-4: `uuid` 导入未使用

**位置**：`outline_planner.py:12`

**问题**：`import uuid` 未在模块中使用（`uuid.uuid4()` 在 orchestrator 中使用）。应移除。

---

## 整体架构评估

### 优点

1. **Pipeline 设计清晰**：Intent → Outline → Chapter Workers → Reviser → Integration → Editor 的分阶段设计合理
2. **DAG 执行**：章节依赖的拓扑排序执行是正确的架构选择
3. **抽象基类**：`BaseAgent` / `BaseTool` / `BaseSkill` 提供了合理的扩展点
4. **异步设计**：核心流程使用 `async/await`，阻塞操作正确使用了 `asyncio.to_thread()`
5. **配置管理**：Pydantic-Settings + YAML 的配置分层设计合理

### 缺点

1. **可测试性设计缺失**：核心类（OrchestratorAgent、OutlinePlanner 等）的依赖（LLMClient、各子 Agent）通过内部 `__init__` 硬编码创建，无法注入 mock
2. **状态管理耦合**：`MemoryManager` 同时管理会话状态、长期记忆、文档集合，职责过重
3. **错误处理策略不一致**：有的地方抛出异常，有的地方返回错误消息，有的地方静默吞掉
4. **无健康检查/监控端点**：FastAPI 应用没有 `/health` 或 `/metrics` 端点

---

## 优先修复路线图

### Phase 1（本周）：安全与稳定性
- [ ] CR-1: 修复路径遍历漏洞
- [ ] CR-4: 替换 bare `except Exception`（至少处理 tools/ 和 core/ 中的）
- [ ] MJ-6: progress_callback 异常日志
- [ ] MN-4: 移除未使用的 import

### Phase 2（下周）：测试覆盖
- [ ] CR-2: 为核心 Pipeline 编写单元测试（优先级：outline_planner → reviser → orchestrator）
- [ ] 引入 mock LLM client  fixtures

### Phase 3（两周内）：工程规范
- [ ] MJ-2: 添加 GitHub Actions CI
- [ ] MJ-3: 启用 mypy strict 模式
- [ ] MJ-4: 提取统一的 RobustJSONParser
- [ ] MJ-5: Prompt 外部化管理

### Phase 4（一个月内）：架构优化
- [ ] CR-3: 替换内存 `_task_store` 为 Redis
- [ ] 增加依赖注入支持（使核心类可测试）
- [ ] 添加 `/health` 和 `/metrics` 端点
