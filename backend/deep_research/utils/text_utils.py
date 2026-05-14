"""Text sanitization and formatting utilities."""

from __future__ import annotations


def sanitize_unicode(text: str) -> str:
    """Remove invalid Unicode surrogate characters without corrupting valid text."""
    return "".join(ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF))


def unwrap_markdown(text: str) -> str:
    """Remove Markdown code block wrapper if present.

    Handles ```markdown, ```, and trailing ```.
    """
    text = text.strip()
    if text.startswith("```markdown"):
        text = text[len("```markdown"):]
    elif text.startswith("```"):
        text = text[len("```"):]
    if text.endswith("```"):
        text = text[: -len("```")]
    return text.strip()
