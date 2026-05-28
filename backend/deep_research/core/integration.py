from __future__ import annotations
"""IntegrationAgent: merges all chapter files into a coherent draft report.

Phase 4a of V4 architecture. Reads all chapter files, adds transitions,
eliminates cross-chapter duplication, and produces draft.md.
"""

import logging
import time
from pathlib import Path
from typing import Any

from deep_research.config.prompt_loader import get_prompt
from deep_research.config.settings import get_settings
from deep_research.core.agent import LLMClient
from deep_research.core.intent_clarifier import ResearchPlanBrief
from deep_research.utils import unwrap_markdown

logger = logging.getLogger(__name__)


INTEGRATION_SYSTEM_PROMPT = get_prompt("integration", "system")


class IntegrationAgent:
    """Merges chapters into a complete report draft."""

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.model = get_settings().llm.model

    async def integrate(
        self,
        title: str,
        summary_points: list[str],
        chapter_files: list[Path],
        session_dir: Path,
        original_query: str = "",
        plan_brief: ResearchPlanBrief | None = None,
    ) -> Path:
        """Merge all chapter files into a coherent draft.

        Args:
            title: Report title.
            summary_points: Executive summary bullet points.
            chapter_files: List of chapter markdown file paths.
            session_dir: Directory to save draft.md.
            original_query: User's original raw input.
            plan_brief: User-confirmed structured research plan.

        Returns:
            Path to the saved draft file.
        """
        # Read all chapter contents
        chapters_data = []
        for f in chapter_files:
            if f.exists():
                text = f.read_text(encoding="utf-8")
                chapters_data.append({
                    "file": f.name,
                    "content": text,
                })
                logger.info(f"[Integration] Loaded chapter: {f.name} ({len(text)} chars)")
            else:
                logger.warning(f"[Integration] Chapter file missing: {f}")

        if not chapters_data:
            logger.error("[Integration] No chapter files found")
            draft_path = session_dir / "draft.md"
            draft_path.write_text("# 报告草稿\n\n未能获取章节内容。", encoding="utf-8")
            return draft_path

        # Build integration prompt
        chapter_texts = []
        for i, cd in enumerate(chapters_data, 1):
            chapter_texts.append(f"【章节 {i}: {cd['file']}】\n\n{cd['content']}\n")

        all_chapters = "\n---\n".join(chapter_texts)
        summary_text = "\n".join(f"- {p}" for p in summary_points)

        # Build research context block from original query + confirmed plan brief
        research_context = ""
        if original_query or plan_brief:
            parts = ["【研究背景与目标】"]
            if original_query:
                parts.append(f"用户原始请求: {original_query}")
            if plan_brief:
                parts.append(plan_brief.to_prompt_block())
            parts.append(
                "\n整合要求：执行摘要和综合结论必须紧扣上述研究目标，"
                "回答用户最初提出的问题。不得偏离研究背景。\n"
            )
            research_context = "\n".join(parts)

        prompt = f"""{research_context}

【报告标题】
{title}

【研究方向参考】
{summary_text}

【各章节内容】
{all_chapters}

请输出整合后的完整报告 Markdown 文本。要求：
1. 以一级标题 # {title} 开头，包含生成日期
2. 执行摘要（## 执行摘要）：基于各章节实际研究发现提炼 3-5 个核心结论要点，同时呼应研究背景与目标
3. 各章节内容完整保留，章节间添加过渡段落
4. 综合结论（## 综合结论）：跨章节综合分析，紧扣研究目标，给出最终判断和建议，400-600 字
5. 参考来源（## 参考来源）：整理各章节中引用的信息来源
6. 直接输出 Markdown，不要用代码块包装"""

        logger.info(f"[Integration] Starting integration of {len(chapters_data)} chapters")
        t0 = time.perf_counter()

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": INTEGRATION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                max_tokens=8192,
            )
            draft_text = response["choices"][0]["message"].get("content", "")
            latency = time.perf_counter() - t0

            # Clean up
            draft_text = unwrap_markdown(draft_text)

            # Ensure title
            if not draft_text.startswith("# "):
                draft_text = f"# {title}\n\n{draft_text}"

        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.error(f"[Integration] LLM integration failed: {e}, using fallback concatenation")
            # Fallback: simple concatenation
            lines = [f"# {title}", "", "## 执行摘要", ""]
            for p in summary_points:
                lines.append(f"- {p}")
            lines.append("")
            for cd in chapters_data:
                lines.append(cd["content"])
                lines.append("")
            lines.extend([
                "## 综合结论",
                "",
                "（报告整合过程出错，综合结论未能生成。请参阅各章节内容。）",
                "",
                "## 参考来源",
                "",
                "本报告由 AI 辅助生成，仅供参考，不构成专业建议。",
                "信息来源于公开资料和第三方数据平台，可能存在延迟或不完整。",
            ])
            draft_text = "\n".join(lines)
            latency = time.perf_counter() - t0

        # Save draft
        draft_path = session_dir / "draft.md"
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(draft_text)

        logger.info(
            f"[Integration] Draft saved to {draft_path} "
            f"({len(draft_text)} chars, {latency:.2f}s)"
        )
        return draft_path
