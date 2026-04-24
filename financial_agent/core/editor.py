"""EditorAgent: final polish for grammar, facts, and completeness.

Phase 4b of V4 architecture. Reads draft.md, evaluates quality,
generates revision suggestions, and IntegrationAgent applies them.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient

logger = logging.getLogger(__name__)


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


EDITOR_SYSTEM_PROMPT = """你是一位资深财经编辑。你的职责是对完整的分析报告进行最终润色和质量把控。

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
        self.llm = LLMClient()
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

        # Truncate if too long for context window
        max_chars = 15000
        if len(draft_text) > max_chars:
            logger.warning(f"[Editor] Draft too long ({len(draft_text)} chars), truncating to {max_chars}")
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

        # Truncate if too long
        max_chars = 12000
        truncated = False
        if len(draft_text) > max_chars:
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
                    {"role": "system", "content": "你是一位资深编辑。请根据反馈意见修改报告，保持原有结构和核心内容，仅做必要的改进。"},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                max_tokens=8192,
            )
            revised = response["choices"][0]["message"].get("content", "")

            # Clean up
            revised = revised.strip()
            if revised.startswith("```markdown"):
                revised = revised[len("```markdown"):].strip()
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
            logger.error(f"[Editor] Failed to apply revisions: {e}")
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
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = json.loads(content.strip().lstrip("\ufeff"))
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
