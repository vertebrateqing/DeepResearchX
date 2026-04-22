"""Context management with token budgeting and automatic compression.

Provides layered context management so that Planner, Workers, and
Synthesizer each operate within their own token budgets.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from financial_agent.core.agent import LLMClient

logger = logging.getLogger(__name__)

# Rough token estimate: ~1 token per Chinese char, ~0.75 per English char
CHARS_PER_TOKEN = 1.5


def estimate_tokens(text: str) -> int:
    """Rough token count estimation."""
    return max(1, int(len(text) / CHARS_PER_TOKEN))


@dataclass
class TokenBudget:
    """Tracks token consumption with a hard cap."""

    max_tokens: int
    consumed: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.consumed)

    def count(self, text: str) -> int:
        return estimate_tokens(text)

    def consume(self, tokens: int) -> None:
        self.consumed += tokens

    def can_fit(self, text: str) -> bool:
        return self.count(text) <= self.remaining

    def truncate_to_fit(self, text: str) -> str:
        """Simple truncation with ellipsis if over budget."""
        needed = self.count(text)
        if needed <= self.remaining:
            self.consume(needed)
            return text

        max_chars = int(self.remaining * CHARS_PER_TOKEN)
        if max_chars < 20:
            return ""

        truncated = text[:max_chars - 3] + "..."
        self.consume(self.count(truncated))
        return truncated


class ContextManager:
    """Manages layered context with automatic compression.

    Three layers:
      1. Planner layer: very compact, only task summaries
      2. Worker layer: moderate, task goal + dependency findings
      3. Synthesizer layer: full findings, but selected/deduplicated
    """

    def __init__(
        self,
        planner_budget: int = 2500,
        worker_budget: int = 4000,
        synthesizer_budget: int = 6000,
    ) -> None:
        self.planner_budget = TokenBudget(planner_budget)
        self.worker_budget = TokenBudget(worker_budget)
        self.synthesizer_budget = TokenBudget(synthesizer_budget)
        self._llm = LLMClient()

    def build_planner_context(
        self,
        user_query: str,
        plan_status: str,
        findings: list[dict[str, Any]],
        budget: TokenBudget | None = None,
    ) -> str:
        """Build compact context for Planner evaluation."""
        budget = budget or self.planner_budget
        parts = [f"用户请求: {user_query}", f"计划状态: {plan_status}"]

        if findings:
            parts.append("\n【已完成的任务摘要】")
            for f in findings:
                line = f"- [{f.get('role', '?')}] {f.get('summary', '')}"
                if not budget.can_fit(line):
                    parts.append("\n... (更多结果被截断)")
                    break
                parts.append(line)
                budget.consume(budget.count(line))

        return "\n".join(parts)

    def build_worker_context(
        self,
        task_goal: str,
        task_inputs: dict[str, Any],
        dependency_findings: list[dict[str, Any]],
        budget: TokenBudget | None = None,
    ) -> str:
        """Build context for a Worker execution."""
        budget = budget or self.worker_budget
        parts = [f"任务目标: {task_goal}"]

        if task_inputs:
            parts.append(f"\n【输入参数】\n{json.dumps(task_inputs, ensure_ascii=False, indent=2)[:500]}")

        if dependency_findings:
            parts.append("\n【前置任务结果】")
            for df in dependency_findings:
                summary = df.get("summary", "")
                task_id = df.get("task_id", "")
                prefix = f"[{task_id}] " if task_id else ""
                line = f"- {prefix}[{df.get('role', '?')}] {summary}"
                if not budget.can_fit(line):
                    parts.append("\n... (更多前置结果被截断)")
                    break
                parts.append(line)
                budget.consume(budget.count(line))

                # Include details if budget allows
                details = df.get("details", {})
                if details:
                    details_text = json.dumps(details, ensure_ascii=False, indent=2)
                    detail_line = f"  详细数据: {details_text}"
                    if budget.can_fit(detail_line):
                        parts.append(detail_line)
                        budget.consume(budget.count(detail_line))
                    else:
                        max_chars = int(budget.remaining * CHARS_PER_TOKEN)
                        if max_chars > 50:
                            truncated = details_text[:max_chars - 3] + "..."
                            parts.append(f"  详细数据: {truncated}")
                            budget.consume(budget.count(truncated))

        return "\n".join(parts)

    def build_synthesizer_context(
        self,
        user_query: str,
        findings: list[dict[str, Any]],
        budget: TokenBudget | None = None,
    ) -> str:
        """Build context for final report synthesis."""
        budget = budget or self.synthesizer_budget
        parts = [f"用户请求: {user_query}"]

        if not findings:
            return parts[0]

        parts.append("\n【研究发现】\n")
        sorted_findings = sorted(findings, key=lambda f: f.get("confidence", 0), reverse=True)

        for i, f in enumerate(sorted_findings, 1):
            block = self._format_finding_block(i, f)
            if not budget.can_fit(block):
                parts.append("\n... (更多发现被截断)")
                break
            parts.append(block)
            budget.consume(budget.count(block))

        return "\n".join(parts)

    def _format_finding_block(self, index: int, finding: dict[str, Any]) -> str:
        lines = [
            f"--- 发现 {index} [{finding.get('role', '?')}] ---",
            f"摘要: {finding.get('summary', '')}",
        ]

        details = finding.get("details", {})
        if details:
            details_text = json.dumps(details, ensure_ascii=False, indent=2)
            lines.append(f"详细数据:\n{details_text}")

        sources = finding.get("sources", [])
        if sources:
            src_lines = [f"  - [{s.get('type', '?')}] {s.get('title', '')}" for s in sources]
            lines.append("来源:\n" + "\n".join(src_lines))

        lines.append(f"置信度: {finding.get('confidence', 0):.0%}")
        return "\n".join(lines)

    async def compress_text(self, text: str, target_tokens: int) -> str:
        """Use LLM to compress text while preserving key information."""
        if estimate_tokens(text) <= target_tokens:
            return text

        prompt = f"""请将以下内容压缩到大约 {target_tokens} 个token的篇幅，保留所有关键事实、数据和结论：

{text}

压缩后内容："""

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=target_tokens,
            )
            compressed = response["choices"][0]["message"].get("content", text)
            return compressed
        except Exception as e:
            logger.warning(f"LLM compression failed: {e}, falling back to truncation")
            max_chars = int(target_tokens * CHARS_PER_TOKEN)
            return text[:max_chars - 3] + "..."

    def reset(self) -> None:
        """Reset all budgets for a new research cycle."""
        self.planner_budget = TokenBudget(self.planner_budget.max_tokens)
        self.worker_budget = TokenBudget(self.worker_budget.max_tokens)
        self.synthesizer_budget = TokenBudget(self.synthesizer_budget.max_tokens)
