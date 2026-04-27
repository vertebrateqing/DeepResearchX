"""IntegrationAgent: merges all chapter files into a coherent draft report.

Phase 4a of V4 architecture. Reads all chapter files, adds transitions,
eliminates cross-chapter duplication, and produces draft.md.
"""

import logging
import time
from pathlib import Path
from typing import Any

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient

logger = logging.getLogger(__name__)


INTEGRATION_SYSTEM_PROMPT = """你是一位资深报告整合专家。你将收到一份报告大纲和多个已完成的章节文件。
你的任务是将这些章节整合为一份连贯、完整的分析报告。

整合要求：
1. 按大纲顺序排列章节
2. 为章节之间添加过渡段落，确保逻辑流畅
3. 消除跨章节的重复内容（合并或删减）
4. 统一全文的术语、格式和引用风格
5. 添加执行摘要（基于大纲中的要点）
6. 在报告末尾添加"数据来源与参考文献"章节
7. 保持各章节的完整内容，不要过度压缩
8. 报告开头应包含：标题、日期、摘要

注意：你是从零开始整合，没有历史对话上下文。所有信息来自提供的章节文件。"""


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
    ) -> Path:
        """Merge all chapter files into a coherent draft.

        Args:
            title: Report title.
            summary_points: Executive summary bullet points.
            chapter_files: List of chapter markdown file paths.
            session_dir: Directory to save draft.md.

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

        prompt = f"""请将以下章节整合为一份完整的分析报告。

【报告标题】
{title}

【执行摘要要点】
{summary_text}

【各章节内容】
{all_chapters}

请输出整合后的完整报告 Markdown 文本。要求：
1. 以一级标题 # {title} 开头
2. 包含报告元数据（日期、生成说明）
3. 添加执行摘要章节
4. 保持各章节的核心内容完整
5. 添加过渡段落使逻辑流畅
6. 末尾添加数据来源说明和免责声明
7. 直接输出 Markdown，不要用代码块包装"""

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
            draft_text = draft_text.strip()
            if draft_text.startswith("```markdown"):
                draft_text = draft_text[len("```markdown"):].strip()
            if draft_text.startswith("```"):
                draft_text = draft_text[3:].strip()
            if draft_text.endswith("```"):
                draft_text = draft_text[:-3].strip()

            # Ensure title
            if not draft_text.startswith("# "):
                draft_text = f"# {title}\n\n{draft_text}"

        except Exception as e:
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
                "## 数据来源与免责声明",
                "",
                "本报告由 AI 辅助生成，仅供参考，不构成投资建议。",
                "数据来源于公开信息和第三方数据平台。",
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
