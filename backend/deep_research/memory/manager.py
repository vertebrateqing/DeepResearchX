from __future__ import annotations
"""High-level memory manager coordinating working, session, and long-term memory."""

import logging
from datetime import datetime
from typing import Any

from deep_research.memory.long_term_store import LongTermStore
from deep_research.memory.models import (
    ConversationTurn,
    MemoryFinding,
    SessionMemory,
    TaskResult,
    TaskState,
    UserPreferences,
)
from deep_research.memory.session_store import SessionStore

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages all memory layers for a user session.

    Usage pattern:
        mm = MemoryManager(session_id="sess_123", user_id="user_456")

        # Load existing session or create new
        mm.init_session()

        # Add conversation turn
        mm.add_user_message("分析茅台")
        mm.add_assistant_message("好的，请问分析哪个年份？")

        # Record task
        mm.start_task("research_task", agent="research_agent", inputs={"topic": "AI发展"})

        # Record finding
        mm.add_finding(
            source="web_search",
            content="2024年全球AI市场规模超过5000亿美元",
            related_entities=["人工智能", "AI市场"],
        )

        # Save everything
        await mm.save()
    """

    def __init__(
        self,
        session_id: str,
        user_id: str = "anonymous",
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.session_store = SessionStore()
        self.long_term_store = LongTermStore(user_id=user_id)

        self._session: SessionMemory | None = None
        self._loaded = False

    # --- Session Lifecycle ---

    def init_session(self) -> SessionMemory:
        """Initialize or load a session."""
        session = self.session_store.load(self.session_id)
        if session is None:
            # Load long-term preferences
            prefs = self.long_term_store.load_preferences()
            session = SessionMemory(
                session_id=self.session_id,
                user_id=self.user_id,
                user_preferences=prefs,
            )
            logger.info(f"Created new session: {self.session_id}")
        else:
            logger.info(f"Loaded existing session: {self.session_id}")

        self._session = session
        self._loaded = True
        return session

    @property
    def session(self) -> SessionMemory:
        if self._session is None:
            return self.init_session()
        return self._session

    async def save(self, sync_long_term: bool = True) -> None:
        """Save session state and optionally sync findings to long-term memory."""
        if self._session is None:
            return

        logger.info(f"[MemoryManager] Saving session {self.session_id}, findings={len(self._session.accumulated_findings)}, tasks={len(self._session.task_stack)}, completed={len(self._session.completed_tasks)}, sync_lt={sync_long_term}")
        # Save session
        self.session_store.save(self._session)
        logger.info(f"[MemoryManager] Session store saved")

        if not sync_long_term:
            return

        # Sync non-expired findings to long-term memory
        synced = 0
        failed = 0
        for finding in self._session.accumulated_findings:
            try:
                await self.long_term_store.add_finding(finding)
                synced += 1
            except Exception as e:
                failed += 1
                logger.warning(f"Failed to sync finding {finding.finding_id}: {e}")

        logger.info(f"[MemoryManager] Synced {synced} findings to long-term memory, {failed} failed")

    def close(self) -> None:
        """Close session, final save, and cleanup."""
        # Note: async save should be called explicitly
        self._session = None
        self._loaded = False

    # --- Conversation ---

    @staticmethod
    def _sanitize(text: str) -> str:
        """Remove invalid Unicode surrogate characters without corrupting valid text."""
        # Strip lone surrogates (U+D800–U+DFFF) only; keep everything else intact.
        return "".join(ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF))

    def add_user_message(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        """Record a user message."""
        self.session.conversation_history.append(
            ConversationTurn(
                role="user",
                content=self._sanitize(content),
                metadata=metadata or {},
            )
        )

    def add_assistant_message(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        """Record an assistant message."""
        self.session.conversation_history.append(
            ConversationTurn(
                role="assistant",
                content=self._sanitize(content),
                metadata=metadata or {},
            )
        )

    def get_recent_conversation(self, n: int = 10) -> list[ConversationTurn]:
        """Get recent conversation turns."""
        return self.session.conversation_history[-n:]

    # --- Tasks ---

    def start_task(
        self,
        task_type: str,
        agent: str,
        inputs: dict[str, Any],
        task_id: str | None = None,
    ) -> TaskState:
        """Record the start of a new task."""
        import uuid

        task = TaskState(
            task_id=task_id or str(uuid.uuid4()),
            task_type=task_type,
            status="in_progress",
            assigned_agent=agent,
            inputs=inputs,
        )
        self.session.task_stack.append(task)
        return task

    def update_task(
        self,
        task_id: str,
        status: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Update a task's status."""
        for task in self.session.task_stack:
            if task.task_id == task_id:
                if status:
                    task.status = status
                if result:
                    task.final_result = result
                if error:
                    task.error_message = error
                task.updated_at = datetime.now()

                # If completed or failed, move to completed_tasks
                if status in ("completed", "failed"):
                    self.session.completed_tasks.append(
                        TaskResult(
                            task_id=task.task_id,
                            task_type=task.task_type,
                            success=(status == "completed"),
                            summary=str(result)[:500] if result else "",
                            full_result=result or {},
                        )
                    )
                    self.session.task_stack.remove(task)
                break

    def get_pending_tasks(self) -> list[TaskState]:
        """Get tasks that are pending or in_progress."""
        return [t for t in self.session.task_stack if t.status in ("pending", "in_progress")]

    def get_task_by_id(self, task_id: str) -> TaskState | None:
        """Get a task by ID."""
        for task in self.session.task_stack:
            if task.task_id == task_id:
                return task
        return None

    # --- Findings ---

    def add_finding(
        self,
        source: str,
        content: str,
        source_ref: str = "",
        confidence: float = 0.5,
        related_entities: list[str] | None = None,
        expires_hours: int | None = None,
    ) -> MemoryFinding:
        """Add a finding to session memory."""
        import uuid

        expires = None
        if expires_hours:
            expires = datetime.now() + timedelta(hours=expires_hours)

        finding = MemoryFinding(
            finding_id=f"finding_{uuid.uuid4().hex[:8]}",
            source=source,
            source_ref=source_ref,
            content=content,
            confidence=confidence,
            related_entities=related_entities or [],
            expires_at=expires,
        )
        self.session.accumulated_findings.append(finding)
        return finding

    async def search_relevant_findings(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search both session and long-term memory for relevant findings."""
        # Search long-term memory
        lt_results = await self.long_term_store.search_findings(query, top_k=top_k)

        # Search session memory (simple text match for now)
        session_findings = []
        for finding in self.session.accumulated_findings:
            if not finding.is_expired():
                # Simple relevance: check if query terms in content
                if any(term in finding.content for term in query.split()):
                    session_findings.append({
                        "id": finding.finding_id,
                        "content": finding.content,
                        "metadata": {
                            "source": finding.source,
                            "confidence": finding.confidence,
                        },
                        "score": 0.5,  # placeholder
                    })

        # Combine and deduplicate
        seen_ids = set()
        combined = []
        for r in lt_results + session_findings:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                combined.append(r)

        return combined[:top_k]

    # --- User Preferences ---

    def get_preferences(self) -> UserPreferences:
        """Get current user preferences."""
        return self.session.user_preferences

    def update_preferences(self, **kwargs: Any) -> None:
        """Update user preferences in both session and long-term storage."""
        for key, value in kwargs.items():
            if hasattr(self.session.user_preferences, key):
                setattr(self.session.user_preferences, key, value)

        # Sync to long-term
        self.long_term_store.save_preferences(self.session.user_preferences)

    def detect_preferences_from_query(self, query: str) -> dict[str, Any]:
        """Try to detect user preferences from their query."""
        detected = {}

        # Investment style
        style_keywords = {
            "value": ["价值", "低估", "便宜", "安全边际"],
            "growth": ["成长", "高增长", "爆发", "潜力"],
            "aggressive": ["激进", "高风险高收益", "杠杆", "短线"],
            "balanced": ["均衡", "稳健", "平衡"],
        }
        for style, keywords in style_keywords.items():
            if any(kw in query for kw in keywords):
                detected["investment_style"] = style
                break

        # Risk tolerance
        if any(kw in query for kw in ["保守", "稳健", "低风险", "安全"]):
            detected["risk_tolerance"] = "low"
        elif any(kw in query for kw in ["激进", "高风险", "大胆", "满仓"]):
            detected["risk_tolerance"] = "high"

        # Time horizon
        if any(kw in query for kw in ["短期", "短线", "一个月", "几天"]):
            detected["time_horizon"] = "short"
        elif any(kw in query for kw in ["中期", "半年", "一年"]):
            detected["time_horizon"] = "medium"
        elif any(kw in query for kw in ["长期", "持有", "三年以上", "养老"]):
            detected["time_horizon"] = "long"

        return detected

    # --- Context Building ---

    def build_context_prompt(self) -> str:
        """Build a context prompt from session memory for injection into LLM.

        This is used when starting a new task to provide relevant background.
        """
        parts = []

        # User preferences
        prefs = self.session.user_preferences
        if prefs.investment_style or prefs.risk_tolerance:
            pref_parts = []
            if prefs.investment_style:
                pref_parts.append(f"投资风格: {prefs.investment_style}")
            if prefs.risk_tolerance:
                pref_parts.append(f"风险偏好: {prefs.risk_tolerance}")
            if prefs.time_horizon:
                pref_parts.append(f"时间维度: {prefs.time_horizon}")
            parts.append(f"【用户偏好】{', '.join(pref_parts)}")

        # Recent findings
        recent_findings = [
            f for f in self.session.accumulated_findings
            if not f.is_expired()
        ][-5:]
        if recent_findings:
            parts.append("【已知信息】")
            for f in recent_findings:
                parts.append(f"- [{f.source}] {f.content[:150]}...")

        # Pending tasks
        pending = self.get_pending_tasks()
        if pending:
            parts.append("【进行中任务】")
            for t in pending:
                parts.append(f"- {t.task_type}: {t.status}")

        # Recent conversation summary
        recent = self.get_recent_conversation(3)
        if recent:
            parts.append("【最近对话】")
            for turn in recent:
                prefix = "用户:" if turn.role == "user" else "助手:"
                parts.append(f"- {prefix} {turn.content[:100]}...")

        return "\n\n".join(parts) if parts else ""


# Re-export for convenience
from datetime import timedelta  # noqa: F401
