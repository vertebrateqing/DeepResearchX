"""Agent message protocol for inter-agent communication."""

from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Message types for agent communication."""

    TASK = "task"  # Task assignment from orchestrator to sub-agent
    RESULT = "result"  # Task result from sub-agent to orchestrator
    ERROR = "error"  # Error occurred during task execution
    SUMMARY = "summary"  # Context summary (for parent-child isolation)
    QUERY = "query"  # Information query between agents
    RESPONSE = "response"  # Response to a query
    STATUS = "status"  # Status update


class AgentMessage(BaseModel):
    """Standard message format for inter-agent communication."""

    msg_type: MessageType = Field(..., description="Type of the message")
    sender: str = Field(..., description="Name of the sending agent")
    receiver: str = Field(..., description="Name of the receiving agent")
    content: Any = Field(..., description="Message payload")
    task_id: Optional[str] = Field(default=None, description="Task identifier for tracking")
    parent_task_id: Optional[str] = Field(
        default=None, description="Parent task ID for hierarchical tasks"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @classmethod
    def create_task(
        cls,
        sender: str,
        receiver: str,
        task_description: str,
        task_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "AgentMessage":
        """Create a task assignment message."""
        return cls(
            msg_type=MessageType.TASK,
            sender=sender,
            receiver=receiver,
            content=task_description,
            task_id=task_id or str(uuid4()),
            parent_task_id=parent_task_id,
            metadata=metadata or {},
        )

    @classmethod
    def create_result(
        cls,
        sender: str,
        receiver: str,
        result: Any,
        task_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "AgentMessage":
        """Create a result message."""
        return cls(
            msg_type=MessageType.RESULT,
            sender=sender,
            receiver=receiver,
            content=result,
            task_id=task_id,
            metadata=metadata or {},
        )

    @classmethod
    def create_error(
        cls,
        sender: str,
        receiver: str,
        error_message: str,
        task_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "AgentMessage":
        """Create an error message."""
        return cls(
            msg_type=MessageType.ERROR,
            sender=sender,
            receiver=receiver,
            content=error_message,
            task_id=task_id,
            metadata=metadata or {},
        )

    @classmethod
    def create_summary(
        cls,
        sender: str,
        receiver: str,
        summary: str,
        task_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "AgentMessage":
        """Create a context summary message (for parent-child isolation)."""
        return cls(
            msg_type=MessageType.SUMMARY,
            sender=sender,
            receiver=receiver,
            content=summary,
            task_id=task_id,
            metadata=metadata or {},
        )

    def is_task(self) -> bool:
        return self.msg_type == MessageType.TASK

    def is_result(self) -> bool:
        return self.msg_type == MessageType.RESULT

    def is_error(self) -> bool:
        return self.msg_type == MessageType.ERROR

    def is_summary(self) -> bool:
        return self.msg_type == MessageType.SUMMARY
