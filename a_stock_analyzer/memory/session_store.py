"""Session memory storage using JSON and Markdown files."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from a_stock_analyzer.memory.models import SessionMemory

logger = logging.getLogger(__name__)

DEFAULT_SESSIONS_DIR = Path("./a_stock_analyzer/data/sessions")


class SessionStore:
    """Stores session memory as JSON (machine-readable) and Markdown (human-readable)."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir or DEFAULT_SESSIONS_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_paths(self, session_id: str) -> tuple[Path, Path]:
        """Get file paths for a session."""
        json_path = self.base_dir / f"{session_id}.json"
        md_path = self.base_dir / f"{session_id}.md"
        return json_path, md_path

    def save(self, session: SessionMemory) -> None:
        """Save session to both JSON and Markdown."""
        session.updated_at = datetime.now()
        json_path, md_path = self._get_paths(session.session_id)

        # Clean data to avoid Unicode surrogate errors
        data = session.to_dict()
        data = self._sanitize_for_json(data)

        # Save JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Save Markdown
        md_content = self._to_markdown(session)
        md_content = self._sanitize_text(md_content)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        logger.debug(f"Saved session {session.session_id}")

    def _sanitize_for_json(self, obj: Any) -> Any:
        """Recursively sanitize data for JSON serialization."""
        if isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_json(v) for v in obj]
        elif isinstance(obj, str):
            return self._sanitize_text(obj)
        return obj

    def _sanitize_text(self, text: str) -> str:
        """Remove invalid Unicode surrogate characters from text."""
        # Remove surrogate pairs and other invalid characters
        return text.encode("utf-8", "surrogatepass").decode("utf-8", "replace")

    def load(self, session_id: str) -> SessionMemory | None:
        """Load session from JSON."""
        json_path, _ = self._get_paths(session_id)
        if not json_path.exists():
            return None

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return SessionMemory.from_dict(data)

    def list_sessions(self) -> list[str]:
        """List all session IDs."""
        return [p.stem for p in self.base_dir.glob("*.json")]

    def delete(self, session_id: str) -> None:
        """Delete a session."""
        json_path, md_path = self._get_paths(session_id)
        if json_path.exists():
            json_path.unlink()
        if md_path.exists():
            md_path.unlink()

    def _to_markdown(self, session: SessionMemory) -> str:
        """Convert session to human-readable Markdown."""
        lines = [
            f"# Session: {session.session_id}",
            "",
            f"- **User**: {session.user_id}",
            f"- **Created**: {session.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"- **Updated**: {session.updated_at.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## User Preferences",
            "",
        ]

        prefs = session.user_preferences
        lines.extend([
            f"- **Investment Style**: {prefs.investment_style or 'Not set'}",
            f"- **Risk Tolerance**: {prefs.risk_tolerance or 'Not set'}",
            f"- **Time Horizon**: {prefs.time_horizon or 'Not set'}",
            f"- **Default Top-N**: {prefs.top_n_default}",
            f"- **Preferred Industries**: {', '.join(prefs.preferred_industries) or 'None'}",
            f"- **Excluded Industries**: {', '.join(prefs.excluded_industries) or 'None'}",
            "",
            "## Task Stack",
            "",
        ])

        for task in session.task_stack:
            status_emoji = {"pending": "⏳", "in_progress": "🔄", "completed": "✅", "failed": "❌", "blocked": "🚫"}.get(task.status, "❓")
            lines.extend([
                f"### {status_emoji} {task.task_type} ({task.task_id})",
                f"- **Status**: {task.status}",
                f"- **Agent**: {task.assigned_agent}",
                f"- **Inputs**: {json.dumps(task.inputs, ensure_ascii=False)}",
            ])
            if task.final_result:
                lines.append(f"- **Result**: {json.dumps(task.final_result, ensure_ascii=False)[:500]}")
            if task.error_message:
                lines.append(f"- **Error**: {task.error_message}")
            lines.append("")

        if session.completed_tasks:
            lines.extend(["## Completed Tasks", ""])
            for task in session.completed_tasks:
                emoji = "✅" if task.success else "❌"
                lines.append(f"- {emoji} **{task.task_type}**: {task.summary[:100]}...")
            lines.append("")

        if session.accumulated_findings:
            lines.extend(["## Key Findings", ""])
            for finding in session.accumulated_findings:
                expired = " [EXPIRED]" if finding.is_expired() else ""
                lines.extend([
                    f"### Finding: {finding.finding_id}{expired}",
                    f"- **Source**: {finding.source} ({finding.source_ref})",
                    f"- **Confidence**: {finding.confidence:.2f}",
                    f"- **Content**: {finding.content[:300]}",
                    "",
                ])

        if session.conversation_history:
            lines.extend(["## Conversation History", ""])
            for turn in session.conversation_history[-20:]:  # Last 20 turns
                role = "👤 User" if turn.role == "user" else "🤖 Assistant"
                lines.append(f"**{role}** ({turn.timestamp.strftime('%H:%M')}):")
                lines.append(f"> {turn.content[:500]}")
                lines.append("")

        return "\n".join(lines)
