"""Report generator for creating markdown and PDF analysis reports."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Optional PDF dependencies - gracefully degrade if unavailable
_HAS_MARKDOWN = False
_HAS_WEASYPRINT = False

try:
    import markdown as md_lib

    _HAS_MARKDOWN = True
except ImportError:
    pass

try:
    from weasyprint import HTML

    _HAS_WEASYPRINT = True
except ImportError:
    pass


DEFAULT_CSS = """
body {
    font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Microsoft YaHei", sans-serif;
    font-size: 11pt;
    line-height: 1.8;
    color: #333;
    max-width: 900px;
    margin: 0 auto;
    padding: 40px;
}
h1 { font-size: 22pt; color: #1a1a1a; border-bottom: 2px solid #2c5282; padding-bottom: 10px; }
h2 { font-size: 16pt; color: #2c5282; margin-top: 30px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }
h3 { font-size: 13pt; color: #4a5568; margin-top: 20px; }
p { margin: 10px 0; }
ul, ol { margin: 10px 0; padding-left: 25px; }
li { margin: 4px 0; }
table { border-collapse: collapse; width: 100%; margin: 15px 0; }
th, td { border: 1px solid #cbd5e0; padding: 8px 12px; text-align: left; }
th { background-color: #edf2f7; font-weight: 600; }
blockquote { border-left: 4px solid #2c5282; margin: 15px 0; padding: 10px 20px; background: #f7fafc; color: #4a5568; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 30px 0; }
.toc { background: #f7fafc; padding: 20px; border-radius: 8px; margin: 20px 0; }
.toc ul { list-style: none; padding-left: 0; }
.toc li { margin: 6px 0; }
.toc a { color: #2c5282; text-decoration: none; }
.meta { color: #718096; font-size: 10pt; margin-bottom: 30px; }
.disclaimer { background: #fffaf0; border-left: 4px solid #ed8936; padding: 15px 20px; margin-top: 30px; font-size: 10pt; color: #744210; }
"""


class ReportGenerator:
    """Generates structured markdown and PDF analysis reports."""

    def generate_markdown(
        self,
        user_query: str,
        final_report: str,
        sections: dict[str, str],
        session_id: str,
        timestamp: datetime | None = None,
        is_v4: bool = False,
    ) -> str:
        """Generate a structured markdown report.

        Args:
            user_query: Original user query
            final_report: Final synthesized report from orchestrator
            sections: Dict of section_name -> section_content
            session_id: Session identifier
            timestamp: Report generation timestamp
            is_v4: If True, final_report is a complete report (V4 mode).

        Returns:
            Markdown string
        """
        ts = timestamp or datetime.now()
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

        if is_v4:
            return self._generate_v4_markdown(
                user_query=user_query,
                final_report=final_report,
                session_id=session_id,
                ts_str=ts_str,
            )

        return self._generate_legacy_markdown(
            user_query=user_query,
            final_report=final_report,
            sections=sections,
            session_id=session_id,
            ts_str=ts_str,
        )

    def _generate_v4_markdown(
        self,
        user_query: str,
        final_report: str,
        session_id: str,
        ts_str: str,
    ) -> str:
        """V4 mode: final_report is already a complete report."""
        lines: list[str] = []

        # Metadata header
        lines.extend([
            '<div class="meta">',
            "",
            f"**生成时间**: {ts_str}",
            f"**会话ID**: {session_id}",
            f"**用户查询**: {user_query}",
            "",
            "</div>",
            "",
            "---",
            "",
        ])

        # Main report content
        lines.append(final_report)
        lines.append("")
        lines.append("---")
        lines.append("")

        # Disclaimer
        lines.extend([
            "## 免责声明",
            "",
            '<div class="disclaimer">',
            "",
            "**本报告仅供参考，不构成投资建议。**",
            "",
            "1. 报告内容基于AI模型生成，可能存在信息遗漏或解读偏差。",
            "2. 投资有风险，入市需谨慎，请独立判断并承担投资风险。",
            "3. 过往业绩不代表未来表现，市场数据可能存在延迟。",
            "4. 建议在做出投资决策前咨询专业投资顾问。",
            "",
            "</div>",
            "",
        ])

        return "\n".join(lines)

    def _generate_legacy_markdown(
        self,
        user_query: str,
        final_report: str,
        sections: dict[str, str],
        session_id: str,
        ts_str: str,
    ) -> str:
        """Legacy V3 mode: build report from sections."""
        lines: list[str] = []

        # Title
        lines.extend([
            "# A股投资分析报告",
            "",
        ])

        # Metadata
        lines.extend([
            '<div class="meta">',
            "",
            f"**生成时间**: {ts_str}",
            f"**会话ID**: {session_id}",
            f"**用户查询**: {user_query}",
            "",
            "</div>",
            "",
        ])

        # Table of Contents
        lines.extend([
            '<div class="toc">',
            "",
            "## 目录",
            "",
            "- [执行摘要](#执行摘要)",
        ])

        role_titles = {
            "tavily_search": "信息检索",
            "data_fetch": "数据分析",
            "doc_analysis": "文档分析",
            "cross_verify": "交叉验证",
            "synthesis": "综合结论",
            "market": "市场分析",
            "industry": "行业推荐",
            "company": "公司选取",
            "financial": "财报深度分析",
        }

        for key in sections:
            title = role_titles.get(key, key)
            lines.append(f"- [{title}](#{title})")

        lines.extend([
            "- [免责声明](#免责声明)",
            "",
            "</div>",
            "",
            "---",
            "",
        ])

        # Executive Summary
        lines.extend([
            "## 执行摘要",
            "",
            final_report,
            "",
            "---",
            "",
        ])

        # Individual sections
        for key in sections:
            content = sections[key]
            if content:
                title = role_titles.get(key, key)
                lines.extend([
                    f"## {title}",
                    "",
                    content,
                    "",
                    "---",
                    "",
                ])

        # Disclaimer
        lines.extend([
            "## 免责声明",
            "",
            '<div class="disclaimer">',
            "",
            "**本报告仅供参考，不构成投资建议。**",
            "",
            "1. 报告内容基于AI模型生成，可能存在信息遗漏或解读偏差。",
            "2. 投资有风险，入市需谨慎，请独立判断并承担投资风险。",
            "3. 过往业绩不代表未来表现，市场数据可能存在延迟。",
            "4. 建议在做出投资决策前咨询专业投资顾问。",
            "",
            "</div>",
            "",
        ])

        return "\n".join(lines)

    def save(
        self,
        output_dir: Path,
        session_id: str,
        markdown: str,
        timestamp: datetime | None = None,
    ) -> tuple[Path, Path | None]:
        """Save markdown and convert to PDF.

        Args:
            output_dir: Directory to save files
            session_id: Session identifier for filename
            markdown: Markdown content
            timestamp: Optional timestamp for filename

        Returns:
            (md_path, pdf_path) where pdf_path may be None if PDF generation fails
        """
        ts = timestamp or datetime.now()
        ts_str = ts.strftime("%Y%m%d_%H%M%S")
        filename = f"report_{session_id}_{ts_str}"

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save Markdown
        md_path = output_dir / f"{filename}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        logger.info(f"[ReportGenerator] Markdown saved: {md_path}")

        # Try PDF generation
        pdf_path = self._try_pdf(output_dir, filename, markdown)
        if pdf_path:
            logger.info(f"[ReportGenerator] PDF saved: {pdf_path}")
        else:
            logger.warning("[ReportGenerator] PDF generation skipped (dependencies not available)")

        return md_path, pdf_path

    def _try_pdf(self, output_dir: Path, filename: str, markdown: str) -> Path | None:
        """Attempt to convert markdown to PDF. Returns path or None."""
        if not _HAS_MARKDOWN:
            logger.debug("[ReportGenerator] markdown library not available")
            return None

        try:
            # Convert markdown to HTML
            html_body = md_lib.markdown(
                markdown,
                extensions=["tables", "fenced_code", "toc"],
            )

            # Wrap with CSS
            html_full = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{DEFAULT_CSS}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

            if _HAS_WEASYPRINT:
                pdf_path = output_dir / f"{filename}.pdf"
                HTML(string=html_full).write_pdf(str(pdf_path))
                return pdf_path
            else:
                logger.debug("[ReportGenerator] weasyprint not available, saving HTML fallback")
                # Fallback: save HTML so user can print to PDF manually
                html_path = output_dir / f"{filename}.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_full)
                logger.info(f"[ReportGenerator] HTML saved (print to PDF): {html_path}")
                return None

        except Exception as e:
            logger.warning(f"[ReportGenerator] PDF generation failed: {e}")
            return None
