"""Extract structured data from LLM markdown responses."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def extract_json_from_markdown(content: str) -> str:
    """Extract JSON string from markdown code blocks.

    Handles ```json ... ``` and plain ``` ... ``` wrappers.
    Falls back to the original content if no code block found.
    """
    if not content:
        return content

    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]

    return content.strip()


def extract_first_json_object(text: str) -> dict | None:
    """Find and parse the first JSON object in a text block.

    Tries markdown extraction first, then scans for the first `{`...`}` pair.
    Returns None if parsing fails.
    """
    cleaned = extract_json_from_markdown(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: find first balanced JSON object
    start = cleaned.find("{")
    if start == -1:
        return None

    depth = 0
    for i, ch in enumerate(cleaned[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
