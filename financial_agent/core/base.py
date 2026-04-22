"""Base classes for Agent, Skill, and Tool."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel


class BaseTool(ABC):
    """Base class for all tools."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool with given arguments.

        Args:
            **kwargs: Tool-specific arguments.

        Returns:
            Dict containing the tool execution result.
        """
        ...

    def get_schema(self) -> dict[str, Any]:
        """Get JSON schema representation for LLM function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                },
            },
        }


class SkillContext(BaseModel):
    """Context passed to skill execution."""

    agent_name: str = ""
    task_id: Optional[str] = None
    parent_context: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = {}


class BaseSkill(ABC):
    """Base class for all skills."""

    name: str = ""
    description: str = ""
    input_schema: Optional[type[BaseModel]] = None
    output_schema: Optional[type[BaseModel]] = None

    @abstractmethod
    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        """Execute the skill.

        Args:
            context: Execution context.
            **inputs: Skill-specific input parameters.

        Returns:
            Dict containing the skill execution result.
        """
        ...


class AgentContext(BaseModel):
    """Context for agent execution."""

    agent_name: str = ""
    task_id: Optional[str] = None
    parent_agent: Optional[str] = None
    metadata: dict[str, Any] = {}


class BaseAgent(ABC):
    """Base class for all agents."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: Optional[list["BaseTool"]] = None,
        skills: Optional[list["BaseSkill"]] = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.skills = skills or []

    @abstractmethod
    async def run(self, user_input: str, context: Optional[AgentContext] = None) -> "AgentMessage":
        """Run the agent with user input.

        Args:
            user_input: User's request or query.
            context: Optional execution context.

        Returns:
            AgentMessage containing the result.
        """
        ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool by name.

        Args:
            tool_name: Name of the tool to call.
            arguments: Arguments to pass to the tool.

        Returns:
            Tool execution result.
        """
        for tool in self.tools:
            if tool.name == tool_name:
                return await tool.execute(**arguments)
        raise ValueError(f"Tool '{tool_name}' not found in agent '{self.name}'")

    async def use_skill(self, skill_name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Use a skill by name.

        Args:
            skill_name: Name of the skill to use.
            inputs: Input parameters for the skill.

        Returns:
            Skill execution result.
        """
        for skill in self.skills:
            if skill.name == skill_name:
                ctx = SkillContext(agent_name=self.name)
                return await skill.execute(ctx, **inputs)
        raise ValueError(f"Skill '{skill_name}' not found in agent '{self.name}'")

    def get_context_summary(self) -> str:
        """Get a summary of this agent's context for parent agent.

        Sub-agents should override this to return a concise summary
        instead of full conversation history.
        """
        return f"Agent {self.name} execution completed."

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all available tools."""
        return [tool.get_schema() for tool in self.tools]
