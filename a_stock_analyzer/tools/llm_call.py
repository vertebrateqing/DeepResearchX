"""LLM call tool for agents."""

from typing import Any, Optional

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.base import BaseTool


class LLMCallTool(BaseTool):
    """Tool for calling LLM from within agents."""

    name = "llm_call"
    description = "调用大语言模型进行文本生成、分析或推理。可用于需要额外LLM推理的子任务。"
    parameters = {
        "prompt": {
            "type": "string",
            "description": "给LLM的提示词",
        },
        "system_prompt": {
            "type": "string",
            "description": "系统提示词（可选）",
            "default": "你是一个专业的金融分析师。",
        },
        "temperature": {
            "type": "number",
            "description": "生成温度，0-2之间",
            "default": 0.3,
        },
        "max_tokens": {
            "type": "integer",
            "description": "最大生成token数",
            "default": 2048,
        },
    }

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from a_stock_analyzer.core.agent import LLMClient

            self._client = LLMClient()
        return self._client

    async def execute(
        self,
        prompt: str,
        system_prompt: str = "你是一个专业的金融分析师。",
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Execute LLM call."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        response = await self.client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response["choices"][0]["message"].get("content", "")
        return {
            "content": content,
            "model": response.get("model", "unknown"),
            "usage": response.get("usage", {}),
        }
