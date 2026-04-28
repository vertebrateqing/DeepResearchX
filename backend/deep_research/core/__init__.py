from __future__ import annotations
"""Core framework module."""

from deep_research.core.agent import LLMClient, ReActAgent, SimpleAgent
from deep_research.core.base import (
    AgentContext,
    BaseAgent,
    BaseSkill,
    BaseTool,
    SkillContext,
)
from deep_research.core.context import AgentRunContext
from deep_research.core.message import AgentMessage, MessageType
from deep_research.core.chapter_worker import ChapterWorker
from deep_research.core.editor import EditorAgent
from deep_research.core.integration import IntegrationAgent
from deep_research.core.orchestrator import OrchestratorAgent
from deep_research.core.outline_planner import (
    ChapterOutline,
    OutlinePlanner,
    ReportOutline,
)
from deep_research.core.registry import Registry, get_registry, reset_registry
from deep_research.core.reviser import ReviserAgent
from deep_research.core.skill_manager import SkillManager, get_skill, register_skill
from deep_research.core.tool_manager import ToolManager, get_tool, register_tool

__all__ = [
    "BaseAgent",
    "BaseSkill",
    "BaseTool",
    "SkillContext",
    "AgentContext",
    "AgentMessage",
    "MessageType",
    "AgentRunContext",
    "Registry",
    "get_registry",
    "reset_registry",
    "ToolManager",
    "register_tool",
    "get_tool",
    "SkillManager",
    "register_skill",
    "get_skill",
    "LLMClient",
    "ReActAgent",
    "SimpleAgent",
    "OrchestratorAgent",
]
