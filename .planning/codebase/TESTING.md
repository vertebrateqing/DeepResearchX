# Testing Patterns

**Analysis Date:** 2026-04-25

## Test Framework

**Runner:**
- pytest >= 8.0
- pytest-asyncio >= 0.23
- pytest-cov >= 5.0
- Config: `pyproject.toml` (`financial_agent/pyproject.toml`)

**Config:**
```toml
[tool.pytest.ini_options]
testpaths = ["financial_agent/tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short"
```

**Assertion Library:**
- Built-in `assert` (Python standard)
- No external assertion library (e.g., `pytest-assert` behavior via pytest itself)

**Run Commands:**
```bash
pytest                              # Run all tests
pytest -v                           # Verbose (default via addopts)
pytest --tb=short                   # Short traceback (default via addopts)
pytest --cov=financial_agent        # Coverage report
pytest financial_agent/tests/unit/test_core.py  # Run specific test file
```

## Test File Organization

**Location:**
- All tests under `financial_agent/tests/`
- Unit tests in `financial_agent/tests/unit/`
- `conftest.py` exists but is empty (no shared fixtures defined yet)

**Naming:**
- Test files: `test_<module>.py`
- Test classes: `Test<Component>` (PascalCase)
- Test methods: `test_<description>` (snake_case)

**Structure:**
```
financial_agent/tests/
├── __init__.py
├── conftest.py
└── unit/
    ├── __init__.py
    ├── test_core.py
    ├── test_rag.py
    ├── test_skills.py
    └── test_tools.py
```

## Test Structure

**Suite Organization:**
```python
class TestMessage:
    def test_create_task(self):
        msg = AgentMessage.create_task(
            sender="orchestrator",
            receiver="sub_agent",
            task_description="test task",
        )
        assert msg.msg_type == MessageType.TASK
        assert msg.sender == "orchestrator"
```

**Async tests:**
```python
class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_run(self):
        agent = DummyAgent(name="test", system_prompt="test")
        result = await agent.run("hello")
        assert result.msg_type == MessageType.RESULT
```

**Setup/teardown:**
```python
class TestAKShareTool:
    def setup_method(self):
        reset_registry()
```
- `setup_method()` used for per-test setup (resetting global registry state)
- No `teardown_method` or class-level fixtures observed

## Test Dummy Implementations

**Pattern for testing abstract base classes:**
```python
class DummyTool(BaseTool):
    name = "dummy_tool"
    description = "A dummy tool for testing"
    parameters = {"input": {"type": "string"}}

    async def execute(self, **kwargs):
        return {"result": f"processed: {kwargs.get('input', '')}"}


class DummySkill(BaseSkill):
    name = "dummy_skill"
    description = "A dummy skill for testing"

    async def execute(self, context: SkillContext, **inputs):
        return {"result": "skill executed"}


class DummyAgent(BaseAgent):
    async def run(self, user_input: str, context=None):
        return AgentMessage.create_result(
            sender=self.name,
            receiver="user",
            result={"answer": user_input},
        )
```
- Dummies defined inline in test files (not in a shared fixtures module)
- Minimal implementations that satisfy abstract method requirements

## Mocking

**Framework:** None explicitly used

**Patterns:**
- No `unittest.mock`, `pytest-mock`, or `respx`/`aioresponses` observed
- Tests are shallow unit tests that instantiate real objects but do not exercise async I/O paths
- Registry is reset via `reset_registry()` to avoid cross-test state pollution

**What is mocked (implicitly):**
- LLM calls are NOT mocked in existing tests (async skill init tests avoid calling LLM)
- HTTP clients are NOT mocked
- Database/storage is NOT mocked

**What is NOT mocked:**
- Real Pydantic model instantiation
- Real tool schema generation (no network calls triggered by `get_schema()`)
- Real registry operations

## Fixtures and Factories

**Test Data:**
- No shared fixtures in `conftest.py`
- No factory functions or parameterized tests
- Test data created inline within each test method

**Example inline data:**
```python
def test_document_creation(self):
    doc = Document(
        content="test content",
        metadata={"source": "test"},
        source="test.txt",
    )
    assert doc.content == "test content"
```

## Coverage

**Requirements:** None enforced in CI (no CI config detected)

**View Coverage:**
```bash
pytest --cov=financial_agent --cov-report=term-missing
pytest --cov=financial_agent --cov-report=html
```

## Test Types

**Unit Tests:**
- Scope: Individual classes and methods in isolation
- Approach: Instantiate objects, call methods, assert on return values
- No integration with external services

**Current test inventory (19 test methods):**

| File | Tests | Coverage |
|------|-------|----------|
| `test_core.py` | 10 | Messages, Registry, BaseAgent |
| `test_rag.py` | 5 | TextSplitter, DocumentLoader |
| `test_skills.py` | 4 | Skill init, Pydantic input schemas |
| `test_tools.py` | 3 | Tool schema generation |

**Integration Tests:**
- Not present

**E2E Tests:**
- Not present

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_skill_init(self):
    from financial_agent.skills.market_analysis import MarketAnalysisSkill
    skill = MarketAnalysisSkill()
    assert skill.name == "market_analysis"
```
- `asyncio_mode = "auto"` means `@pytest.mark.asyncio` is technically optional for async tests, but tests still include it explicitly

**Error Testing:**
```python
def test_duplicate_registration(self):
    registry = get_registry()
    tool = DummyTool()
    registry.register_tool(tool)
    with pytest.raises(ValueError):
        registry.register_tool(tool)
```

**Schema Testing:**
```python
def test_tool_schema(self):
    tool = AKShareTool()
    schema = tool.get_schema()
    assert schema["function"]["name"] == "akshare_data"
    assert "data_type" in schema["function"]["parameters"]["properties"]
```

## Test Coverage Gaps

**Untested areas (high impact):**
- `core/agent.py` — `LLMClient.chat()`, `ReActAgent.run()` (no LLM mocking)
- `core/orchestrator.py` — Full V4 pipeline (5 phases)
- `core/chapter_worker.py` — Chapter writing and revision
- `core/reviser.py` — Review loop and JSON parsing
- `core/intent_clarifier.py` — Clarification dialogue
- `tools/web_search.py` — Tavily/DuckDuckGo search execution
- `tools/akshare_data.py` — AKShare data fetching
- `tools/web_scraper.py` — Web scraping and chunking
- `rag/pipeline.py` — Full RAG query-and-answer flow
- `memory/manager.py` — Session lifecycle, long-term sync
- `config/settings.py` — YAML loading, env var expansion

**What to mock for future tests:**
- `LLMClient.chat()` — patch at `financial_agent.core.agent.LLMClient.chat`
- `httpx.AsyncClient.post()` — for embedding/LLM HTTP calls
- `AKShareTool.ak` — for AKShare data fetching
- `WebSearchTool.execute()` — for search results
- `RAGPipeline.retriever` — for retrieval results
- `MemoryManager.save()` — for session persistence

**Recommended test additions:**
1. Mock-based tests for `ReActAgent.run()` with a mocked `LLMClient`
2. Mock-based tests for `OrchestratorAgent._execute_research()`
3. `respx` or `aioresponses` tests for `LLMClient._openai_chat()`
4. Parametrized tests for `RecursiveTextSplitter` edge cases
5. Tests for `Registry` thread-safety (if applicable)
6. Tests for `Settings.from_yaml()` with temp config files

---

*Testing analysis: 2026-04-25*
