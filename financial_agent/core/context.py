"""Context management for agent execution with isolation support."""

from typing import Any, Optional
from uuid import uuid4

from financial_agent.core.message import AgentMessage, MessageType


class AgentRunContext:
    """Runtime context for a single agent execution.

    Provides context isolation between parent and child agents.
    Each sub-agent gets its own context instance.
    """

    def __init__(
        self,
        agent_name: str,
        parent_context: Optional["AgentRunContext"] = None,
        task_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.agent_name = agent_name
        self.task_id = task_id or str(uuid4())
        self.parent_context = parent_context
        self.metadata = metadata or {}
        self.messages: list[AgentMessage] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.skill_calls: list[dict[str, Any]] = []
        self._summary: Optional[str] = None

    def add_message(self, message: AgentMessage) -> None:
        """Add a message to the context history."""
        self.messages.append(message)

    def add_tool_call(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        """Record a tool call."""
        self.tool_calls.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
        })

    def add_skill_call(self, skill_name: str, inputs: dict[str, Any], result: dict[str, Any]) -> None:
        """Record a skill call."""
        self.skill_calls.append({
            "skill_name": skill_name,
            "inputs": inputs,
            "result": result,
        })

    def set_summary(self, summary: str) -> None:
        """Set the execution summary for parent agent consumption."""
        self._summary = summary

    def get_summary(self) -> str:
        """Get the execution summary.

        If no summary is set, generate a basic one from messages.
        """
        if self._summary:
            return self._summary

        # Generate basic summary from message history
        task_count = sum(1 for m in self.messages if m.msg_type == MessageType.TASK)
        result_count = sum(1 for m in self.messages if m.msg_type == MessageType.RESULT)
        error_count = sum(1 for m in self.messages if m.msg_type == MessageType.ERROR)

        parts = [f"Agent '{self.agent_name}' execution summary:"]
        parts.append(f"  - Tasks processed: {task_count}")
        parts.append(f"  - Results produced: {result_count}")
        parts.append(f"  - Errors: {error_count}")
        parts.append(f"  - Tool calls: {len(self.tool_calls)}")
        parts.append(f"  - Skill calls: {len(self.skill_calls)}")

        return "\n".join(parts)

    def get_child_context(self, child_agent_name: str, metadata: Optional[dict[str, Any]] = None) -> "AgentRunContext":
        """Create a child context for a sub-agent.

        The child context is isolated from the parent - it starts fresh
        but maintains a reference to the parent for hierarchical tracking.
        """
        child_metadata = {**(metadata or {}), "parent_agent": self.agent_name}
        return AgentRunContext(
            agent_name=child_agent_name,
            parent_context=self,
            task_id=str(uuid4()),
            metadata=child_metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize context to dictionary."""
        return {
            "agent_name": self.agent_name,
            "task_id": self.task_id,
            "metadata": self.metadata,
            "message_count": len(self.messages),
            "tool_call_count": len(self.tool_calls),
            "skill_call_count": len(self.skill_calls),
            "summary": self.get_summary(),
        }
