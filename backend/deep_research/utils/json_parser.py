"""Extract structured data from LLM markdown responses."""

from __future__ import annotations

import json
import logging
import re

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


def _fix_json_string_escapes(text: str) -> str:
    """Fix unescaped control characters inside JSON string literals.

    LLMs sometimes emit literal newlines, tabs, or other control chars inside
    JSON string values, which makes json.loads fail with 'Expecting delimiter'.
    This function replaces bare control characters inside string literals with
    their proper JSON escape sequences.
    """
    result = []
    in_string = False
    escape_next = False
    i = 0
    while i < len(text):
        ch = text[i]
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        elif in_string and ord(ch) < 0x20:
            # Other control characters
            result.append(f'\\u{ord(ch):04x}')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


class RobustJSONParser:
    """Centralized JSON parser with multiple fallback strategies for LLM output.

    Handles common LLM output issues:
    - Markdown code block wrapping
    - <think> reasoning blocks
    - Unescaped control characters in strings
    - Chinese quotation marks
    - Truncated or malformed JSON
    """

    @staticmethod
    def parse(text: str) -> dict | None:
        """Parse text into a dict using multiple fallback strategies.

        Returns None if all strategies fail.
        """
        # Step 0: Strip <think> blocks
        content = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Step 1: Extract from markdown code block
        content = extract_json_from_markdown(content).lstrip("\ufeff")

        # Step 2: Replace Chinese quotation marks that break JSON
        content = content.replace("\u201c", '"').replace("\u201d", '"')
        content = content.replace("\u2018", "'").replace("\u2019", "'")

        # Step 3: Try direct parse
        data = RobustJSONParser._try_parse(content)
        if data is not None:
            return data

        # Step 4: Fix unescaped control characters and retry
        repaired = _fix_json_string_escapes(content)
        data = RobustJSONParser._try_parse(repaired)
        if data is not None:
            return data

        # Step 5: Extract outermost {...} and retry
        match = re.search(r'\{[\s\S]*\}', repaired)
        if match:
            data = RobustJSONParser._try_parse(match.group(0))
            if data is not None:
                return data

        logger.debug("[RobustJSONParser] All parse strategies failed")
        return None

    @staticmethod
    def _try_parse(text: str) -> dict | None:
        """Attempt to parse text as JSON. Returns None on failure."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
