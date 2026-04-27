"""Unit tests for core framework."""

import pytest

from financial_agent.core.base import AgentContext, BaseAgent, BaseSkill, BaseTool, SkillContext
from financial_agent.core.message import AgentMessage, MessageType
from financial_agent.core.registry import Registry, get_registry, reset_registry


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


class TestMessage:
    def test_create_task(self):
        msg = AgentMessage.create_task(
            sender="orchestrator",
            receiver="sub_agent",
            task_description="test task",
        )
        assert msg.msg_type == MessageType.TASK
        assert msg.sender == "orchestrator"
        assert msg.receiver == "sub_agent"
        assert msg.content == "test task"
        assert msg.task_id is not None

    def test_create_result(self):
        msg = AgentMessage.create_result(
            sender="sub_agent",
            receiver="orchestrator",
            result={"answer": "test"},
        )
        assert msg.msg_type == MessageType.RESULT
        assert msg.content == {"answer": "test"}

    def test_is_task(self):
        msg = AgentMessage.create_task("a", "b", "task")
        assert msg.is_task()
        assert not msg.is_result()


class TestRegistry:
    def setup_method(self):
        reset_registry()

    def test_register_tool(self):
        registry = get_registry()
        tool = DummyTool()
        registry.register_tool(tool)
        assert "dummy_tool" in registry.list_tools()
        assert registry.get_tool("dummy_tool") == tool

    def test_register_skill(self):
        registry = get_registry()
        skill = DummySkill()
        registry.register_skill(skill)
        assert "dummy_skill" in registry.list_skills()

    def test_register_agent(self):
        registry = get_registry()
        agent = DummyAgent(name="test_agent", system_prompt="test")
        registry.register_agent(agent)
        assert "test_agent" in registry.list_agents()

    def test_duplicate_registration(self):
        registry = get_registry()
        tool = DummyTool()
        registry.register_tool(tool)
        with pytest.raises(ValueError):
            registry.register_tool(tool)


class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_run(self):
        agent = DummyAgent(name="test", system_prompt="test")
        result = await agent.run("hello")
        assert result.msg_type == MessageType.RESULT
        assert result.content["answer"] == "hello"

    @pytest.mark.asyncio
    async def test_call_tool(self):
        agent = DummyAgent(
            name="test",
            system_prompt="test",
            tools=[DummyTool()],
        )
        result = await agent.call_tool("dummy_tool", {"input": "test"})
        assert result["result"] == "processed: test"

    def test_get_tool_schemas(self):
        agent = DummyAgent(
            name="test",
            system_prompt="test",
            tools=[DummyTool()],
        )
        schemas = agent.get_tool_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "dummy_tool"


class TestReActAgent:
    @pytest.mark.asyncio
    async def test_react_loop_exhaustion_returns_error(self):
        from financial_agent.core.agent import ReActAgent

        class FailingLLMClient:
            async def chat(self, **kwargs):
                return {
                    "choices": [{
                        "message": {
                            "content": "",
                            "tool_calls": [{
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "dummy_tool", "arguments": "{}"}
                            }]
                        }
                    }]
                }

        agent = ReActAgent(name="test", system_prompt="test", max_iterations=2)
        agent.llm = FailingLLMClient()
        result = await agent.run("test query")
        assert result.msg_type == MessageType.ERROR
        assert "未获得有效结果" in result.content or "请重试" in result.content
