"""Tool manager for registering, discovering, and executing tools."""

import json
from typing import Any

from financial_agent.core.base import BaseTool
from financial_agent.core.registry import get_registry


class ToolManager:
    """Manages tool registration and execution."""

    def __init__(self) -> None:
        self._registry = get_registry()

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._registry.register_tool(tool)

    def get(self, name: str) -> BaseTool:
        """Get a tool by name."""
        tool = self._registry.get_tool(name)
        if tool is None:
            raise ValueError(f"Tool '{name}' not found")
        return tool

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return self._registry.list_tools()

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get JSON schemas for all registered tools."""
        schemas = []
        for name in self.list_tools():
            tool = self._registry.get_tool(name)
            if tool:
                schemas.append(tool.get_schema())
        return schemas

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by name with arguments."""
        tool = self.get(name)
        return await tool.execute(**arguments)

    async def execute_from_llm_call(self, function_call: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool from an LLM function call.

        Args:
            function_call: Dict with 'name' and 'arguments' keys.

        Returns:
            Tool execution result.
        """
        name = function_call.get("name")
        args_str = function_call.get("arguments", "{}")

        if isinstance(args_str, str):
            arguments = json.loads(args_str)
        else:
            arguments = args_str

        return await self.execute(name, arguments)


# Convenience functions

def register_tool(tool: BaseTool) -> None:
    """Register a tool globally."""
    get_registry().register_tool(tool)


def get_tool(name: str) -> BaseTool:
    """Get a tool by name."""
    tool = get_registry().get_tool(name)
    if tool is None:
        raise ValueError(f"Tool '{name}' not found")
    return tool
