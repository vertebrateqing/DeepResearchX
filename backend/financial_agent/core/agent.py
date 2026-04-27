"""Core agent implementation with LLM-based tool use."""

import json
import logging
import time
import traceback
from typing import Any, Optional

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from financial_agent.config.settings import get_settings
from financial_agent.core.base import AgentContext, BaseAgent, BaseSkill, BaseTool
from financial_agent.core.context import AgentRunContext
from financial_agent.core.message import AgentMessage, MessageType

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified LLM client supporting OpenAI-compatible APIs.

    Supports all Chinese LLMs via OpenAI-compatible format:
    - DeepSeek (deepseek-chat, deepseek-reasoner)
    - Kimi / Moonshot (moonshot-v1-*)
    - 通义千问 / Qwen (qwen-turbo, qwen-plus, qwen-max)
    - 智谱AI / GLM (glm-4, glm-4-plus)
    - 百度文心 / Qianfan (ernie-4.0, ernie-3.5)
    - Local models via vLLM / Ollama
    """

    def __init__(self, timeout: Optional[float] = None) -> None:
        self.settings = get_settings().llm
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            effective_timeout = self._timeout if self._timeout is not None else self.settings.timeout
            self._client = httpx.AsyncClient(timeout=effective_timeout)
        return self._client

    @property
    def _is_chinese_llm(self) -> bool:
        """Detect if using a Chinese LLM for response compatibility."""
        model = (self.settings.model or "").lower()
        url = (self.settings.base_url or "").lower()
        chinese_markers = [
            "deepseek", "moonshot", "kimi", "qwen", "glm", "ernie",
            "qianfan", "dashscope", "zhipu", "baidu",
        ]
        return any(m in model or m in url for m in chinese_markers)

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Send chat completion request to LLM.

        Args:
            max_retries: Number of retry attempts on failure (default 3).
        """
        retryer = AsyncRetrying(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            reraise=True,
        )
        return await retryer(
            self._openai_chat, messages, tools, temperature, max_tokens, model
        )

    async def _openai_chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Call OpenAI-compatible API."""
        url = self.settings.base_url or "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        # Some Chinese providers use x-api-key instead
        if "dashscope" in url.lower():
            headers = {
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            }

        payload: dict[str, Any] = {
            "model": model or self.settings.model,
            "messages": messages,
            "temperature": temperature or self.settings.temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens
        elif self.settings.max_tokens:
            payload["max_tokens"] = self.settings.max_tokens

        # DeepSeek Reasoner (R1) does not support tool calling / temperature=0
        model_name = (model or self.settings.model or "").lower()
        is_deepseek_r1 = "deepseek-reasoner" in model_name or "deepseek-r1" in model_name

        if is_deepseek_r1:
            payload.pop("temperature", None)
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
        elif tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        logger.debug(f"LLM request: {json.dumps(payload, ensure_ascii=False)}")

        t0 = time.perf_counter()
        response = await self.client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        llm_latency = time.perf_counter() - t0

        # Normalize Chinese LLM response differences
        result = self._normalize_response(result)

        # Log response summary
        usage = result.get("usage", {})
        choices = result.get("choices", [])
        msg = choices[0].get("message", {}) if choices else {}
        has_tools = bool(msg.get("tool_calls"))
        content = msg.get("content", "")
        logger.info(
            f"LLM response: latency={llm_latency:.2f}s, "
            f"prompt_tokens={usage.get('prompt_tokens', '?')}, "
            f"completion_tokens={usage.get('completion_tokens', '?')}, "
            f"has_tool_calls={has_tools}, content_len={len(content)}"
        )
        # Log full response content and reasoning without truncation
        logger.debug(f"LLM response full: {json.dumps(result, ensure_ascii=False)}")
        if content:
            logger.debug(f"LLM content: {content}")
        return result

    def _normalize_response(self, result: dict[str, Any]) -> dict[str, Any]:
        """Normalize response from various Chinese LLM providers to OpenAI format.

        Handles:
        - DeepSeek reasoning_content -> prepends to content
        - Moonshot/Kimi minor response format differences
        - Qianfan nested result structure
        """
        if "choices" not in result and "result" in result:
            # Baidu Qianfan v2 wraps response in "result"
            if isinstance(result["result"], dict) and "choices" in result["result"]:
                result = result["result"]

        if "choices" not in result:
            return result

        choices = result.get("choices", [])
        if not choices:
            return result

        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            return result

        # DeepSeek: merge reasoning_content into content
        reasoning = message.get("reasoning_content", "")
        if reasoning and not message.get("content", "").startswith("[思考]"):
            content = message.get("content", "")
            # Prepend reasoning for downstream consumption
            if reasoning.strip():
                message["content"] = f"[思考过程]\n{reasoning}\n\n[最终回答]\n{content}"
            choices[0]["message"] = message

        # Some providers (e.g., older Qwen) wrap tool_calls in different keys
        if "function_call" in message and "tool_calls" not in message:
            message["tool_calls"] = [{
                "id": "call_default",
                "type": "function",
                "function": message["function_call"],
            }]
            choices[0]["message"] = message

        result["choices"] = choices
        return result

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class ReActAgent(BaseAgent):
    """ReAct-style agent that uses LLM to reason and act with tools."""

    MAX_ITERATIONS = 10

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: Optional[list[BaseTool]] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
        max_iterations: int = 10,
    ):
        super().__init__(name, system_prompt, tools, skills)
        self.llm = LLMClient()
        self.model = model
        self.max_iterations = max_iterations

    async def run(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run the agent with user input using ReAct loop."""
        run_ctx = AgentRunContext(
            agent_name=self.name,
            task_id=context.task_id if context else None,
            metadata=context.metadata if context else {},
        )

        messages = self._build_messages(user_input)
        tools_schema = self.get_tool_schemas()

        final_answer = ""

        for iteration in range(self.max_iterations):
            logger.info(f"Agent {self.name} - iteration {iteration + 1}")

            try:
                response = await self.llm.chat(
                    messages=messages,
                    tools=tools_schema if tools_schema else None,
                    model=self.model,
                )
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                error_msg = AgentMessage.create_error(
                    sender=self.name,
                    receiver=context.parent_agent if context else "user",
                    error_message=f"LLM call failed: {str(e)}",
                    task_id=run_ctx.task_id,
                )
                run_ctx.add_message(error_msg)
                return error_msg

            choice = response["choices"][0]
            message = choice["message"]
            msg_content = message.get("content", "")

            # Log LLM thinking / reasoning output without truncation
            if msg_content:
                logger.debug(f"Agent {self.name} iteration {iteration + 1} thinking: {msg_content}")

            # Check for tool calls
            tool_calls = message.get("tool_calls", [])

            if tool_calls:
                logger.info(f"Agent {self.name} received {len(tool_calls)} tool call(s)")
                # Add assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": msg_content,
                    "tool_calls": tool_calls,
                })

                # Execute each tool call
                for tc in tool_calls:
                    function = tc["function"]
                    tool_name = function["name"]
                    tool_args = json.loads(function["arguments"])

                    logger.info(f"Agent {self.name} calling tool: {tool_name}")
                    logger.debug(f"Agent {self.name} tool args: {json.dumps(tool_args, ensure_ascii=False)}")

                    try:
                        result = await self.call_tool(tool_name, tool_args)
                        logger.info(f"Agent {self.name} tool {tool_name} executed")
                        try:
                            result_preview = str(result)[:200]
                        except Exception:
                            result_preview = "<unable to preview>"
                        logger.debug(f"Agent {self.name} tool {tool_name} result: {result_preview}")
                        run_ctx.add_tool_call(tool_name, tool_args, result)
                    except Exception as e:
                        logger.error(f"Tool {tool_name} failed: {e}")
                        logger.error(f"Tool {tool_name} traceback: {traceback.format_exc()}")
                        result = {"error": str(e)}

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                # No tool calls - this is the final answer
                final_answer = message.get("content", "")
                logger.info(f"Agent {self.name} final answer received, length={len(final_answer)}")
                # Sanitize to remove invalid Unicode surrogates
                final_answer = "".join(ch for ch in final_answer if not (0xD800 <= ord(ch) <= 0xDFFF))
                break

        if not final_answer:
            logger.warning(f"Agent {self.name} reached max iterations without final answer")
            error_msg = AgentMessage.create_error(
                sender=self.name,
                receiver=context.parent_agent if context else "user",
                error_message="分析完成但未获得有效结果，请重试或简化问题",
                task_id=run_ctx.task_id,
            )
            run_ctx.add_message(error_msg)
            return error_msg

        # Generate summary for parent agent
        summary = self._generate_summary(run_ctx, final_answer)
        run_ctx.set_summary(summary)

        result_msg = AgentMessage.create_result(
            sender=self.name,
            receiver=context.parent_agent if context else "user",
            result={"answer": final_answer, "summary": summary},
            task_id=run_ctx.task_id,
        )
        run_ctx.add_message(result_msg)
        return result_msg

    def _build_messages(self, user_input: str) -> list[dict[str, str]]:
        """Build the message list for LLM."""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]

    def _generate_summary(self, run_ctx: AgentRunContext, final_answer: str) -> str:
        """Generate a concise summary for the parent agent."""
        # For sub-agents, return a structured summary
        tool_names = [tc["tool_name"] for tc in run_ctx.tool_calls]
        skill_names = [sc["skill_name"] for sc in run_ctx.skill_calls]

        parts = [f"## {self.name} 执行摘要"]
        parts.append(f"\n**最终结论：**\n{final_answer[:500]}...")

        if tool_names:
            parts.append(f"\n**使用工具：** {', '.join(set(tool_names))}")
        if skill_names:
            parts.append(f"\n**使用技能：** {', '.join(set(skill_names))}")

        return "\n".join(parts)

    async def run_simple(self, user_input: str) -> str:
        """Simple LLM call without tool use."""
        messages = self._build_messages(user_input)
        response = await self.llm.chat(messages=messages, model=self.model)
        content = response["choices"][0]["message"].get("content", "")
        # Sanitize to remove invalid Unicode surrogates
        return "".join(ch for ch in content if not (0xD800 <= ord(ch) <= 0xDFFF))


class SimpleAgent(BaseAgent):
    """Simple agent without tool use - just LLM chat."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: Optional[list[BaseTool]] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
    ):
        super().__init__(name, system_prompt, tools, skills)
        self.llm = LLMClient()
        self.model = model

    async def run(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run simple LLM inference."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]

        try:
            response = await self.llm.chat(messages=messages, model=self.model)
            content = response["choices"][0]["message"].get("content", "")
        except Exception as e:
            return AgentMessage.create_error(
                sender=self.name,
                receiver=context.parent_agent if context else "user",
                error_message=str(e),
                task_id=context.task_id if context else None,
            )

        return AgentMessage.create_result(
            sender=self.name,
            receiver=context.parent_agent if context else "user",
            result={"answer": content},
            task_id=context.task_id if context else None,
        )

    async def run_simple(self, user_input: str) -> str:
        """Simple LLM call without tool use, returns raw text."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]

        response = await self.llm.chat(messages=messages, model=self.model)
        content = response["choices"][0]["message"].get("content", "")
        # Sanitize to remove invalid Unicode surrogates
        return "".join(ch for ch in content if not (0xD800 <= ord(ch) <= 0xDFFF))
