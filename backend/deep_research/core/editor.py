from __future__ import annotations
"""EditorAgent: final polish for grammar, facts, and completeness.

Phase 4b of V4 architecture. Reads draft.md, evaluates quality,
generates revision suggestions, and IntegrationAgent applies them.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deep_research.config.settings import get_settings
from deep_research.core.agent import LLMClient
from deep_research.utils import extract_json_from_markdown, unwrap_markdown

logger = logging.getLogger(__name__)

# Known context window sizes (tokens) for common models.
# Used to dynamically compute safe input length.
# Unmapped models fall back to FALLBACK_CONTEXT_TOKENS.
_MODEL_CONTEXT_TOKENS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    # DeepSeek
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    # Qwen
    "qwen-long": 1_000_000,
    "qwen-max": 32_000,
    "qwen-plus": 131_072,
    "qwen-turbo": 1_000_000,
    # Kimi / Moonshot
    "moonshot-v1-8k": 8_000,
    "moonshot-v1-32k": 32_000,
    "moonshot-v1-128k": 128_000,
    # Zhipu
    "glm-4": 128_000,
    "glm-4-plus": 128_000,
    "glm-4-flash": 128_000,
    # MiniMax
    "minimax-m2.5": 1_000_000,
    "abab6.5s-chat": 245_760,
}
_FALLBACK_CONTEXT_TOKENS = 32_000
# Conservative chars-per-token estimate for mixed Chinese/English text
_CHARS_PER_TOKEN = 1.5


def _max_input_chars(model: str, output_reserve_tokens: int = 4096) -> int:
    """Estimate max safe input characters for the given model.

    Looks up the model's context window, subtracts a reserve for output and
    system/prompt overhead, then converts remaining tokens to characters.
    """
    model_lower = model.lower()
    ctx_tokens = _FALLBACK_CONTEXT_TOKENS
    for key, val in _MODEL_CONTEXT_TOKENS.items():
        if key in model_lower:
            ctx_tokens = val
            break
    # Reserve tokens: output + ~20% overhead for system prompt / formatting
    overhead = int(ctx_tokens * 0.2)
    available = max(ctx_tokens - output_reserve_tokens - overhead, 4096)
    return int(available * _CHARS_PER_TOKEN)


@dataclass
class EditResult:
    """Result of editorial review."""

    passed: bool
    scores: dict[str, int]
    revision_suggestions: list[str]
    critical_issues: list[str]
    review_round: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "scores": self.scores,
            "revision_suggestions": self.revision_suggestions,
            "critical_issues": self.critical_issues,
            "review_round": self.review_round,
        }


EDITOR_SYSTEM_PROMPT = """你是一位资深研究报告编辑。你的职责是对完整的分析报告进行最终润色和质量把控。

评估维度（每项 1-10 分，10分为最佳）：
1. grammar_style (语法与表达): 语言是否专业、流畅？是否有语病或冗余？术语使用是否准确？
2. factual_consistency (事实一致性): 全文数据是否前后一致？有无自相矛盾？引用是否准确？
3. completeness (报告完整度): 是否覆盖了应有内容？有无遗漏重要章节？结构是否完整？
4. formatting (格式统一): 标题层级、引用格式、表格样式是否统一？Markdown 格式是否正确？

通过标准：总分 >= 28 且 单项 >= 6

输出格式（严格JSON，不要任何解释文字）：
{
  "passed": true/false,
  "scores": {
    "grammar_style": 8,
    "factual_consistency": 9,
    "completeness": 8,
    "formatting": 7
  },
  "revision_suggestions": ["建议1", "建议2"],
  "critical_issues": ["必须修正的问题1"]
}"""


class EditorAgent:
    """Reviews and suggests improvements for the complete draft."""

    MAX_EDIT_ROUNDS = 2
    PASS_THRESHOLD_TOTAL = 28
    PASS_THRESHOLD_SINGLE = 6

    def __init__(self) -> None:
        # Dedicated client with longer timeout for revision tasks
        self.llm = LLMClient(timeout=300)
        self.model = get_settings().llm.model

    async def review_draft(
        self,
        draft_file: Path,
        review_round: int = 0,
    ) -> EditResult:
        """Review the complete draft report.

        Args:
            draft_file: Path to draft.md.
            review_round: Current edit round.

        Returns:
            EditResult with scores and suggestions.
        """
        if not draft_file.exists():
            logger.error(f"[Editor] Draft file not found: {draft_file}")
            return EditResult(
                passed=True,
                scores={"grammar_style": 7, "factual_consistency": 7, "completeness": 7, "formatting": 7},
                revision_suggestions=[],
                critical_issues=[],
                review_round=review_round,
            )

        draft_text = draft_file.read_text(encoding="utf-8")

        # Dynamically truncate based on model context window
        max_chars = _max_input_chars(self.model, output_reserve_tokens=4096)
        if len(draft_text) > max_chars:
            logger.warning(
                f"[Editor] Draft too long ({len(draft_text)} chars), "
                f"truncating to {max_chars} (model={self.model})"
            )
            draft_text = draft_text[:max_chars] + "\n\n... (内容截断)"

        prompt = f"""请对以下分析报告进行编辑评审。

【报告内容】
{draft_text}

请严格按照评估标准进行评分，并输出JSON格式的评审结果。"""

        logger.info(f"[Editor] Reviewing draft (round {review_round + 1})")

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": EDITOR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                max_tokens=4096,
            )
            content = response["choices"][0]["message"].get("content", "")
            result = self._parse_edit(content)
            result.review_round = review_round

            total = sum(result.scores.values())
            min_score = min(result.scores.values()) if result.scores else 0
            result.passed = total >= self.PASS_THRESHOLD_TOTAL and min_score >= self.PASS_THRESHOLD_SINGLE

            logger.info(
                f"[Editor] Round {review_round + 1}: total={total}, min={min_score}, passed={result.passed}"
            )
            return result

        except Exception as e:
            logger.error(f"[Editor] Review failed: {e}")
            return EditResult(
                passed=True,
                scores={"grammar_style": 7, "factual_consistency": 7, "completeness": 7, "formatting": 7},
                revision_suggestions=[],
                critical_issues=[],
                review_round=review_round,
            )

    async def apply_revisions(
        self,
        draft_file: Path,
        edit_result: EditResult,
    ) -> Path:
        """Apply editorial revisions to the draft.

        Uses LLM to rewrite the draft based on editor feedback.

        Args:
            draft_file: Path to current draft.
            edit_result: Editor feedback with revision suggestions.

        Returns:
            Path to revised draft file.
        """
        if not edit_result.revision_suggestions and not edit_result.critical_issues:
            logger.info("[Editor] No revisions needed")
            return draft_file

        draft_text = draft_file.read_text(encoding="utf-8")

        # Dynamically truncate based on model context window (reserve more tokens for output)
        max_chars = _max_input_chars(self.model, output_reserve_tokens=20000)
        truncated = False
        if len(draft_text) > max_chars:
            logger.warning(
                f"[Editor] Draft too long for revision ({len(draft_text)} chars), "
                f"truncating to {max_chars} (model={self.model})"
            )
            draft_text = draft_text[:max_chars]
            truncated = True

        suggestions_text = "\n".join(f"- {s}" for s in edit_result.revision_suggestions)
        critical_text = "\n".join(f"- {c}" for c in edit_result.critical_issues)

        prompt = f"""请根据以下编辑建议，修改和完善分析报告。

【当前报告】
{draft_text}
{"(内容已截断)" if truncated else ""}

【必须修正的问题】
{critical_text}

【改进建议】
{suggestions_text}

请输出修改后的完整报告 Markdown 文本。直接输出，不要用代码块包装。"""

        logger.info(f"[Editor] Applying {len(edit_result.revision_suggestions)} suggestions + {len(edit_result.critical_issues)} critical issues")

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": "你是一位资深研究报告编辑。请根据反馈意见修改报告，保持原有结构和核心内容，仅做必要的改进。"},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                max_tokens=20000,
                max_retries=1,  # Avoid cumulative timeout on long outputs
            )
            revised = response["choices"][0]["message"].get("content", "")

            # Clean up
            revised = revised.strip()
            revised = unwrap_markdown(revised)
            if revised.startswith("```"):
                revised = revised[3:].strip()
            if revised.endswith("```"):
                revised = revised[:-3].strip()

            # Save revised draft
            with open(draft_file, "w", encoding="utf-8") as f:
                f.write(revised)

            logger.info(f"[Editor] Revised draft saved: {len(revised)} chars")
            return draft_file

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e) or error_type
            logger.error(
                f"[Editor] Failed to apply revisions: {error_type}: {error_msg}",
                exc_info=True,
            )
            # Save diagnostic record for post-mortem analysis
            from datetime import datetime
            diag = {
                "timestamp": datetime.now().isoformat(),
                "error_type": error_type,
                "error_msg": error_msg,
                "draft_length": len(draft_text),
                "was_truncated": truncated,
                "suggestions_count": len(edit_result.revision_suggestions),
                "critical_count": len(edit_result.critical_issues),
                "review_round": edit_result.review_round,
            }
            diag_path = draft_file.parent / f"edit_failure_round{edit_result.review_round}.json"
            try:
                with open(diag_path, "w", encoding="utf-8") as f:
                    json.dump(diag, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return draft_file

    async def edit_loop(
        self,
        draft_file: Path,
        session_dir: Path,
    ) -> Path:
        """Run editor review loop until pass or max rounds.

        Args:
            draft_file: Path to initial draft.
            session_dir: Directory for saving edit records.

        Returns:
            Path to final draft file.
        """
        for round_num in range(self.MAX_EDIT_ROUNDS):
            result = await self.review_draft(draft_file, review_round=round_num)

            # Save edit result
            edits_path = session_dir / "edits.json"
            edits_data = {"edit_rounds": []}
            if edits_path.exists():
                try:
                    with open(edits_path, "r", encoding="utf-8") as f:
                        edits_data = json.load(f)
                except Exception:
                    pass
            edits_data["edit_rounds"].append(result.to_dict())
            with open(edits_path, "w", encoding="utf-8") as f:
                json.dump(edits_data, f, ensure_ascii=False, indent=2)

            if result.passed:
                logger.info(f"[Editor] Passed after {round_num + 1} round(s)")
                return draft_file

            # Apply revisions
            draft_file = await self.apply_revisions(draft_file, result)

        logger.info(f"[Editor] Max rounds ({self.MAX_EDIT_ROUNDS}) reached, using final version")
        return draft_file

    def _parse_edit(self, content: str) -> EditResult:
        """Parse LLM editorial response into EditResult."""
        try:
            data = json.loads(extract_json_from_markdown(content).lstrip("\ufeff"))
        except (json.JSONDecodeError, IndexError):
            logger.warning("[Editor] Failed to parse edit JSON, using fallback")
            return EditResult(
                passed=True,
                scores={"grammar_style": 7, "factual_consistency": 7, "completeness": 7, "formatting": 7},
                revision_suggestions=[],
                critical_issues=[],
            )

        scores = data.get("scores", {})
        defaults = {"grammar_style": 7, "factual_consistency": 7, "completeness": 7, "formatting": 7}
        for key, default in defaults.items():
            if key not in scores:
                scores[key] = default

        return EditResult(
            passed=data.get("passed", False),
            scores=scores,
            revision_suggestions=data.get("revision_suggestions", []),
            critical_issues=data.get("critical_issues", []),
        )
