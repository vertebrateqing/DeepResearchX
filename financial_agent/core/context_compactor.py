"""Context compression mechanism for agents.

When context window usage reaches threshold (default 80%),
compresses middle history into a structured summary while preserving:
- System prompt
- Recent conversation rounds
- Task progress, todo items, and metadata
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient

logger = logging.getLogger(__name__)

# Approximate token counts (very rough estimation)
TOKENS_PER_CHAR = 0.5


@dataclass
class CompressionResult:
    """Result of context compression."""

    compressed_messages: list[dict[str, str]]
    original_count: int
    compressed_count: int
    summary: str
    preserved_recent: int


class ContextCompactor:
    """Compresses agent context when approaching token limit."""

    DEFAULT_THRESHOLD = 0.8
    RECENT_ROUNDS_TO_KEEP = 4

    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = threshold or self.DEFAULT_THRESHOLD
        self.llm = LLMClient()

    def check_needs_compression(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
    ) -> bool:
        """Check if context needs compression."""
        current_tokens = self._estimate_tokens(messages)
        limit = max_tokens * self.threshold
        return current_tokens >= limit

    def _estimate_tokens(self, messages: list[dict[str, str]]) -> int:
        """Roughly estimate token count from messages."""
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            else:
                total_chars += len(str(content))
        return int(total_chars * TOKENS_PER_CHAR)

    async def compact(
        self,
        messages: list[dict[str, str]],
        context_metadata: dict[str, Any] | None = None,
    ) -> CompressionResult:
        """Compress messages by summarizing middle portion.

        Strategy:
        1. Identify compressible regions (old tool calls, completed agent outputs)
        2. Generate structured summary
        3. Keep system prompt + summary + recent rounds
        """
        if len(messages) <= 3:
            # Too short to compress
            return CompressionResult(
                compressed_messages=messages,
                original_count=len(messages),
                compressed_count=len(messages),
                summary="",
                preserved_recent=0,
            )

        # Identify regions
        system_msg = None
        recent_start_idx = max(1, len(messages) - self.RECENT_ROUNDS_TO_KEEP * 2)

        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                system_msg = msg
                break

        # Split into: [system] + [compressible middle] + [recent to keep]
        compressible = []
        start_idx = 1 if system_msg else 0

        for i in range(start_idx, recent_start_idx):
            msg = messages[i]
            # Skip tool results (they'll be summarized)
            if msg.get("role") == "tool":
                continue
            compressible.append(msg)

        recent_messages = messages[recent_start_idx:]

        # Generate summary
        summary = await self._generate_summary(
            compressible_messages=compressible,
            metadata=context_metadata,
        )

        # Build compressed messages
        compressed = []
        if system_msg:
            compressed.append(system_msg)

        if summary:
            compressed.append({
                "role": "system",
                "content": f"【此前对话摘要】\n\n{summary}",
            })

        compressed.extend(recent_messages)

        return CompressionResult(
            compressed_messages=compressed,
            original_count=len(messages),
            compressed_count=len(compressed),
            summary=summary,
            preserved_recent=len(recent_messages),
        )

    async def _generate_summary(
        self,
        compressible_messages: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Generate structured summary of compressible messages.

        Must preserve:
        - Task goal
        - Execution progress
        - Completed sub-tasks and key conclusions
        - Todo items
        - Key findings/data
        - User preferences/constraints
        - Recent conversation highlights
        """
        metadata = metadata or {}

        # Build prompt for summarization
        conversation_text = "\n\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')[:500]}"
            for msg in compressible_messages
        ])

        prompt = f"""请将以下对话历史压缩为结构化的摘要。摘要必须包含关键信息，用于后续对话的上下文理解。

需要保留的信息：
1. 当前任务目标
2. 已完成的子任务和关键结论
3. 待办事项（未完成的任务）
4. 已获取的关键数据/发现
5. 用户确认的偏好或约束
6. 最近几轮对话的核心内容

对话历史：
{conversation_text}

额外上下文：
{json.dumps(metadata, ensure_ascii=False, indent=2) if metadata else "无"}

请生成简洁的结构化摘要（不超过800字）："""

        try:
            messages = [
                {"role": "system", "content": "你是一个上下文压缩助手，擅长提取对话中的关键信息并生成结构化摘要。"},
                {"role": "user", "content": prompt},
            ]
            response = await self.llm.chat(messages=messages)
            summary = response["choices"][0]["message"].get("content", "")
            return summary.strip()
        except Exception as e:
            logger.error(f"Context compression failed: {e}")
            # Fallback: simple truncation
            return self._fallback_summary(compressible_messages)

    def _fallback_summary(self, messages: list[dict[str, str]]) -> str:
        """Generate a simple fallback summary when LLM fails."""
        parts = ["【上下文摘要 - 系统自动生成】\n"]

        # Extract key information heuristically
        user_queries = []
        assistant_answers = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                user_queries.append(content[:100])
            elif role == "assistant":
                assistant_answers.append(content[:100])

        if user_queries:
            parts.append("用户请求:")
            for q in user_queries[-3:]:
                parts.append(f"  - {q}")

        if assistant_answers:
            parts.append("\n助手回复:")
            for a in assistant_answers[-3:]:
                parts.append(f"  - {a}")

        return "\n".join(parts)
