"""Data models for the memory system."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ConversationTurn:
    """A single turn in the conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    """Represents the state of a sub-task."""

    task_id: str
    task_type: str  # "market_analysis", "financial_rag", ...
    status: str = "pending"  # "pending", "in_progress", "completed", "failed", "blocked"
    assigned_agent: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    intermediate_results: list[dict] = field(default_factory=list)
    final_result: dict[str, Any] | None = None
    error_message: str = ""
    dependencies: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "assigned_agent": self.assigned_agent,
            "inputs": self.inputs,
            "intermediate_results": self.intermediate_results,
            "final_result": self.final_result,
            "error_message": self.error_message,
            "dependencies": self.dependencies,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            status=data.get("status", "pending"),
            assigned_agent=data.get("assigned_agent", ""),
            inputs=data.get("inputs", {}),
            intermediate_results=data.get("intermediate_results", []),
            final_result=data.get("final_result"),
            error_message=data.get("error_message", ""),
            dependencies=data.get("dependencies", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class TaskResult:
    """Result of a completed task."""

    task_id: str
    task_type: str
    success: bool
    summary: str = ""
    full_result: dict[str, Any] = field(default_factory=dict)
    completed_at: datetime = field(default_factory=datetime.now)


@dataclass
class MemoryFinding:
    """A piece of knowledge discovered during research, stored in session memory."""

    finding_id: str
    source: str  # "web_search", "akshare", "financial_report", "agent_analysis"
    source_ref: str = ""  # URL / doc_id / API_name
    content: str = ""
    confidence: float = 0.5
    related_entities: list[str] = field(default_factory=list)
    extracted_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


@dataclass
class UserPreferences:
    """User's investment preferences."""

    investment_style: str | None = None  # "value", "growth", "balanced", "aggressive"
    risk_tolerance: str | None = None  # "low", "medium", "high"
    preferred_industries: list[str] = field(default_factory=list)
    excluded_industries: list[str] = field(default_factory=list)
    time_horizon: str | None = None  # "short", "medium", "long"
    top_n_default: int = 10
    favorite_metrics: list[str] = field(default_factory=list)  # "ROE", "PE", "PB", ...

    def to_dict(self) -> dict[str, Any]:
        return {
            "investment_style": self.investment_style,
            "risk_tolerance": self.risk_tolerance,
            "preferred_industries": self.preferred_industries,
            "excluded_industries": self.excluded_industries,
            "time_horizon": self.time_horizon,
            "top_n_default": self.top_n_default,
            "favorite_metrics": self.favorite_metrics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserPreferences":
        return cls(
            investment_style=data.get("investment_style"),
            risk_tolerance=data.get("risk_tolerance"),
            preferred_industries=data.get("preferred_industries", []),
            excluded_industries=data.get("excluded_industries", []),
            time_horizon=data.get("time_horizon"),
            top_n_default=data.get("top_n_default", 10),
            favorite_metrics=data.get("favorite_metrics", []),
        )


@dataclass
class SessionMemory:
    """Complete memory for a user session."""

    session_id: str
    user_id: str = "anonymous"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Conversation
    conversation_history: list[ConversationTurn] = field(default_factory=list)

    # Tasks
    task_stack: list[TaskState] = field(default_factory=list)
    completed_tasks: list[TaskResult] = field(default_factory=list)

    # Knowledge
    accumulated_findings: list[MemoryFinding] = field(default_factory=list)

    # Preferences
    user_preferences: UserPreferences = field(default_factory=UserPreferences)

    # Clarification state
    clarification_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "conversation_history": [
                {
                    "role": turn.role,
                    "content": turn.content,
                    "timestamp": turn.timestamp.isoformat(),
                    "metadata": turn.metadata,
                }
                for turn in self.conversation_history
            ],
            "task_stack": [task.to_dict() for task in self.task_stack],
            "completed_tasks": [
                {
                    "task_id": t.task_id,
                    "task_type": t.task_type,
                    "success": t.success,
                    "summary": t.summary,
                    "full_result": t.full_result,
                    "completed_at": t.completed_at.isoformat(),
                }
                for t in self.completed_tasks
            ],
            "accumulated_findings": [
                {
                    "finding_id": f.finding_id,
                    "source": f.source,
                    "source_ref": f.source_ref,
                    "content": f.content,
                    "confidence": f.confidence,
                    "related_entities": f.related_entities,
                    "extracted_at": f.extracted_at.isoformat(),
                    "expires_at": f.expires_at.isoformat() if f.expires_at else None,
                }
                for f in self.accumulated_findings
            ],
            "user_preferences": self.user_preferences.to_dict(),
            "clarification_state": self.clarification_state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMemory":
        session = cls(
            session_id=data["session_id"],
            user_id=data.get("user_id", "anonymous"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

        session.conversation_history = [
            ConversationTurn(
                role=turn["role"],
                content=turn["content"],
                timestamp=datetime.fromisoformat(turn["timestamp"]),
                metadata=turn.get("metadata", {}),
            )
            for turn in data.get("conversation_history", [])
        ]

        session.task_stack = [
            TaskState.from_dict(task)
            for task in data.get("task_stack", [])
        ]

        session.completed_tasks = [
            TaskResult(
                task_id=t["task_id"],
                task_type=t["task_type"],
                success=t["success"],
                summary=t.get("summary", ""),
                full_result=t.get("full_result", {}),
                completed_at=datetime.fromisoformat(t["completed_at"]),
            )
            for t in data.get("completed_tasks", [])
        ]

        session.accumulated_findings = [
            MemoryFinding(
                finding_id=f["finding_id"],
                source=f["source"],
                source_ref=f.get("source_ref", ""),
                content=f.get("content", ""),
                confidence=f.get("confidence", 0.5),
                related_entities=f.get("related_entities", []),
                extracted_at=datetime.fromisoformat(f["extracted_at"]),
                expires_at=datetime.fromisoformat(f["expires_at"]) if f.get("expires_at") else None,
            )
            for f in data.get("accumulated_findings", [])
        ]

        session.user_preferences = UserPreferences.from_dict(
            data.get("user_preferences", {})
        )
        session.clarification_state = data.get("clarification_state", {})

        return session