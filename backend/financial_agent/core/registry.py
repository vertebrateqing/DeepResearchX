"""Global registry for agents, skills, and tools."""

from typing import Any, Optional

from financial_agent.core.base import BaseAgent, BaseSkill, BaseTool


class Registry:
    """Global registry for managing agents, skills, and tools."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._skills: dict[str, BaseSkill] = {}
        self._tools: dict[str, BaseTool] = {}

    # Agent registration
    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent."""
        if agent.name in self._agents:
            raise ValueError(f"Agent '{agent.name}' already registered")
        self._agents[agent.name] = agent

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """Get an agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def unregister_agent(self, name: str) -> None:
        """Unregister an agent."""
        self._agents.pop(name, None)

    # Skill registration
    def register_skill(self, skill: BaseSkill) -> None:
        """Register a skill."""
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' already registered")
        self._skills[skill.name] = skill

    def get_skill(self, name: str) -> Optional[BaseSkill]:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        """List all registered skill names."""
        return list(self._skills.keys())

    def unregister_skill(self, name: str) -> None:
        """Unregister a skill."""
        self._skills.pop(name, None)

    # Tool registration
    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def unregister_tool(self, name: str) -> None:
        """Unregister a tool."""
        self._tools.pop(name, None)


# Global registry instance
_registry: Optional[Registry] = None


def get_registry() -> Registry:
    """Get global registry instance (singleton)."""
    global _registry
    if _registry is None:
        _registry = Registry()
    return _registry


def reset_registry() -> Registry:
    """Reset and return a new global registry."""
    global _registry
    _registry = Registry()
    return _registry
