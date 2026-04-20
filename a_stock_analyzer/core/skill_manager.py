"""Skill manager for registering, discovering, and executing skills."""

from typing import Any

from a_stock_analyzer.core.base import BaseSkill, SkillContext
from a_stock_analyzer.core.registry import get_registry


class SkillManager:
    """Manages skill registration and execution."""

    def __init__(self) -> None:
        self._registry = get_registry()

    def register(self, skill: BaseSkill) -> None:
        """Register a skill."""
        self._registry.register_skill(skill)

    def get(self, name: str) -> BaseSkill:
        """Get a skill by name."""
        skill = self._registry.get_skill(name)
        if skill is None:
            raise ValueError(f"Skill '{name}' not found")
        return skill

    def list_skills(self) -> list[str]:
        """List all registered skill names."""
        return self._registry.list_skills()

    async def execute(
        self,
        name: str,
        agent_name: str,
        inputs: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a skill by name.

        Args:
            name: Skill name.
            agent_name: Name of the executing agent.
            inputs: Skill input parameters.
            task_id: Optional task ID.

        Returns:
            Skill execution result.
        """
        skill = self.get(name)
        context = SkillContext(
            agent_name=agent_name,
            task_id=task_id,
        )
        return await skill.execute(context, **inputs)


# Convenience functions

def register_skill(skill: BaseSkill) -> None:
    """Register a skill globally."""
    get_registry().register_skill(skill)


def get_skill(name: str) -> BaseSkill:
    """Get a skill by name."""
    skill = get_registry().get_skill(name)
    if skill is None:
        raise ValueError(f"Skill '{name}' not found")
    return skill
