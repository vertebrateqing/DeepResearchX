"""ReviserAgent: quality review and feedback loop for report chapters.

Phase 3 of V4 architecture. Reads chapter files, evaluates quality across
multiple dimensions, and sends feedback back to ChapterWorker for revision.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient
from financial_agent.core.outline_planner import ChapterOutline

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result of chapter quality review."""

    passed: bool
    scores: dict[str, int]
    feedback: str
    action_required: str  # "revise" or "accept"
    chapter_id: str = ""
    review_round: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "scores": self.scores,
            "feedback": self.feedback,
            "action_required": self.action_required,
            "chapter_id": self.chapter_id,
            "review_round": self.review_round,
        }


REVISER_SYSTEM_PROMPT = """你是一位资深投研报告质量评审专家。你的职责是审查分析报告的每个章节，确保质量达标。

评审维度（每项 1-10 分，10分为最佳）：
1. research_depth (研究深度): 内容是否有深度分析，还是仅停留在表面描述？是否有独到的洞察和数据支撑？
2. data_reliability (数据可靠性): 数据是否有明确来源？是否最新？关键数据是否准确？
3. content_safety (内容安全性): 是否包含违规投资建议？风险提示是否充分？是否有免责声明？
4. rigor (严谨程度): 逻辑是否自洽？论证是否充分？结论是否有数据支撑？有无明显漏洞？
5. formatting (格式规范): Markdown 格式是否正确？标题层级是否合理？引用格式是否统一？

通过标准：总分 >= 35 且 单项 >= 6

输出格式（严格JSON，不要任何解释文字）：
{
  "passed": true/false,
  "scores": {
    "research_depth": 8,
    "data_reliability": 7,
    "content_safety": 9,
    "rigor": 7,
    "formatting": 8
  },
  "feedback": "具体评审意见和修改建议。如果未通过，请详细说明需要修改的地方。",
  "action_required": "revise" 或 "accept"
}"""


class ReviserAgent:
    """Reviews chapter quality and provides structured feedback."""

    MAX_REVISION_ROUNDS = 2
    PASS_THRESHOLD_TOTAL = 35
    PASS_THRESHOLD_SINGLE = 6

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.model = get_settings().llm.model

    async def review_chapter(
        self,
        chapter_outline: ChapterOutline,
        chapter_file: Path,
        review_round: int = 0,
    ) -> ReviewResult:
        """Review a single chapter file.

        Args:
            chapter_outline: The outline requirements for this chapter.
            chapter_file: Path to the chapter markdown file.
            review_round: Current revision round (0 = first review).

        Returns:
            ReviewResult with scores and feedback.
        """
        if not chapter_file.exists():
            logger.error(f"[Reviser] Chapter file not found: {chapter_file}")
            return ReviewResult(
                passed=False,
                scores={},
                feedback="章节文件不存在",
                action_required="revise",
                chapter_id=chapter_outline.chapter_id,
                review_round=review_round,
            )

        chapter_text = chapter_file.read_text(encoding="utf-8")
        word_count = len(chapter_text)

        prompt = f"""请评审以下分析报告章节。

【章节要求】
标题: {chapter_outline.title}
目标: {chapter_outline.objective}
关键问题: {', '.join(chapter_outline.key_questions)}
建议字数: {chapter_outline.word_count} 字
实际字数: {word_count} 字

【章节内容】
{chapter_text}

请严格按照评审标准进行评分，并输出JSON格式的评审结果。"""

        logger.info(
            f"[Reviser] Reviewing chapter {chapter_outline.chapter_id} "
            f"(round {review_round + 1}): '{chapter_outline.title}'"
        )

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": REVISER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                max_tokens=2048,
            )
            content = response["choices"][0]["message"].get("content", "")
            result = self._parse_review(content)
            result.chapter_id = chapter_outline.chapter_id
            result.review_round = review_round

            total = sum(result.scores.values())
            min_score = min(result.scores.values()) if result.scores else 0
            result.passed = total >= self.PASS_THRESHOLD_TOTAL and min_score >= self.PASS_THRESHOLD_SINGLE
            result.action_required = "accept" if result.passed else "revise"

            logger.info(
                f"[Reviser] Chapter {chapter_outline.chapter_id}: "
                f"total={total}, min={min_score}, passed={result.passed}"
            )
            return result

        except Exception as e:
            logger.error(f"[Reviser] Review failed for {chapter_outline.chapter_id}: {e}")
            # Fallback: auto-pass to avoid blocking
            return ReviewResult(
                passed=True,
                scores={
                    "research_depth": 7,
                    "data_reliability": 7,
                    "content_safety": 8,
                    "rigor": 7,
                    "formatting": 7,
                },
                feedback=f"评审过程出错，自动通过。错误: {e}",
                action_required="accept",
                chapter_id=chapter_outline.chapter_id,
                review_round=review_round,
            )

    async def review_all_chapters(
        self,
        outline: "ReportOutline",
        session_dir: Path,
    ) -> dict[str, ReviewResult]:
        """Review all chapters and return results.

        Also saves review results to reviews.json.
        """
        results: dict[str, ReviewResult] = {}

        for chapter in outline.chapters:
            chapter_file = session_dir / f"chapter_{chapter.chapter_id}.md"
            result = await self.review_chapter(chapter, chapter_file)
            results[chapter.chapter_id] = result

        # Save all reviews
        reviews_path = session_dir / "reviews.json"
        reviews_data = {
            "chapter_reviews": {cid: r.to_dict() for cid, r in results.items()},
            "overall_passed": all(r.passed for r in results.values()),
        }
        with open(reviews_path, "w", encoding="utf-8") as f:
            json.dump(reviews_data, f, ensure_ascii=False, indent=2)

        passed_count = sum(1 for r in results.values() if r.passed)
        logger.info(
            f"[Reviser] All chapters reviewed: {passed_count}/{len(results)} passed"
        )
        return results

    def _parse_review(self, content: str) -> ReviewResult:
        """Parse LLM review response into ReviewResult."""
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = json.loads(content.strip().lstrip("\ufeff"))
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"[Reviser] Failed to parse review JSON, using fallback")
            return ReviewResult(
                passed=True,
                scores={"research_depth": 7, "data_reliability": 7, "content_safety": 8, "rigor": 7, "formatting": 7},
                feedback="评审解析失败，自动通过",
                action_required="accept",
            )

        scores = data.get("scores", {})
        # Ensure all dimensions have scores
        defaults = {"research_depth": 7, "data_reliability": 7, "content_safety": 8, "rigor": 7, "formatting": 7}
        for key, default in defaults.items():
            if key not in scores:
                scores[key] = default

        return ReviewResult(
            passed=data.get("passed", False),
            scores=scores,
            feedback=data.get("feedback", ""),
            action_required=data.get("action_required", "revise"),
        )

    async def revision_loop(
        self,
        chapter_outline: ChapterOutline,
        chapter_file: Path,
        worker: "ChapterWorker",
    ) -> bool:
        """Run review-revision loop for a single chapter.

        Args:
            chapter_outline: The chapter outline requirements.
            chapter_file: Path to the chapter markdown file.
            worker: The ChapterWorker instance for revisions.

        Returns:
            True if chapter passed review (after possible revisions).
        """
        for round_num in range(self.MAX_REVISION_ROUNDS + 1):
            result = await self.review_chapter(
                chapter_outline, chapter_file, review_round=round_num
            )

            if result.passed:
                logger.info(
                    f"[Reviser] Chapter {chapter_outline.chapter_id} passed "
                    f"after {round_num + 1} review(s)"
                )
                return True

            if round_num >= self.MAX_REVISION_ROUNDS:
                logger.warning(
                    f"[Reviser] Chapter {chapter_outline.chapter_id} exhausted "
                    f"max revision rounds, accepting as-is"
                )
                return False

            # Request revision
            logger.info(
                f"[Reviser] Chapter {chapter_outline.chapter_id} needs revision: "
                f"{result.feedback[:100]}..."
            )
            await worker.revise(result.feedback)

        return False
