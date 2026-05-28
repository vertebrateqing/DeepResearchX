"""Prompt loader for externalized system prompts."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Default prompts file path (relative to this module)
DEFAULT_PROMPTS_PATH = Path(__file__).with_suffix("").parent / "prompts" / "default.yaml"

# In-memory fallback for when YAML is missing or malformed.
# These are minimal placeholders so the system never crashes.
_FALLBACK_PROMPTS: dict[str, Any] = {
    "outline_planner": {
        "research": "You are a research assistant. Gather information about the user's topic and summarize findings.",
        "outline": "You are a report planning expert. Design a structured report outline in JSON format.",
    },
}


@lru_cache(maxsize=1)
def load_prompts(path: Path | None = None) -> dict[str, Any]:
    """Load prompts from YAML file.

    Falls back to built-in minimal prompts if the file is missing,
    yaml is not installed, or the file is malformed.

    Args:
        path: Path to the YAML prompts file. Uses default if None.

    Returns:
        Nested dict of prompt categories and their prompts.
    """
    prompts_path = path or DEFAULT_PROMPTS_PATH

    if yaml is None:
        logger.warning("PyYAML not installed, using fallback prompts")
        return _FALLBACK_PROMPTS

    if not prompts_path.exists():
        logger.warning(f"Prompts file not found: {prompts_path}, using fallback prompts")
        return _FALLBACK_PROMPTS

    try:
        with open(prompts_path, "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f)
        if not isinstance(prompts, dict):
            logger.warning(f"Invalid prompts file format: {prompts_path}, using fallback prompts")
            return _FALLBACK_PROMPTS
        logger.info(f"Loaded prompts from {prompts_path}")
        return prompts
    except Exception as e:
        logger.warning(f"Failed to load prompts from {prompts_path}: {e}, using fallback prompts")
        return _FALLBACK_PROMPTS


def get_prompt(category: str, name: str, path: Path | None = None) -> str:
    """Get a single prompt by category and name.

    Args:
        category: Top-level key in the prompts YAML (e.g. "outline_planner").
        name: Second-level key (e.g. "research" or "outline").
        path: Optional custom prompts file path.

    Returns:
        The prompt string, or a minimal fallback if not found.
    """
    prompts = load_prompts(path)
    category_prompts = prompts.get(category, {})
    prompt = category_prompts.get(name)
    if prompt is None:
        logger.warning(f"Prompt not found: {category}.{name}, using fallback")
        fallback = _FALLBACK_PROMPTS.get(category, {}).get(name)
        return fallback or f"You are an AI assistant. Please follow instructions carefully."
    return prompt
