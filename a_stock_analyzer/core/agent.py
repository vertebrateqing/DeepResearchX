"""Core agent implementation with LLM-based tool use."""

import json
import logging
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.base import AgentContext, BaseAgent, BaseSkill, BaseTool
from a_stock_analyzer.core.context import AgentRunContext
from a_stock_analyzer.core.message import AgentMessage, MessageType

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified LLM client supporting OpenAI and local models."""

    def __init__(self) -> None:
        self.settings = get_settings().llm
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.settings.timeout)
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send chat completion request to LLM."""
        if self.settings.provider == "openai":
            return await self._openai_chat(messages, tools, temperature, max_tokens, model)
        else:
            raise NotImplementedError(f"Provider '{self.settings.provider}' not yet supported")

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

        payload: dict[str, Any] = {
            "model": model or self.settings.model,
            "messages": messages,
            "temperature": temperature or self.settings.temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens
        elif self.settings.max_tokens:
            payload["max_tokens"] = self.settings.max_tokens

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        logger.debug(f"LLM request: {json.dumps(payload, ensure_ascii=False)[:500]}")

        response = await self.client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        logger.debug(f"LLM response: {json.dumps(result, ensure_ascii=False)[:500]}")
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

            # Check for tool calls
            tool_calls = message.get("tool_calls", [])

            if tool_calls:
                # Add assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": message.get("content", ""),
                    "tool_calls": tool_calls,
                })

                # Execute each tool call
                for tc in tool_calls:
                    function = tc["function"]
                    tool_name = function["name"]
                    tool_args = json.loads(function["arguments"])

                    logger.info(f"Agent {self.name} calling tool: {tool_name}")

                    try:
                        result = await self.call_tool(tool_name, tool_args)
                        run_ctx.add_tool_call(tool_name, tool_args, result)
                    except Exception as e:
                        logger.error(f"Tool {tool_name} failed: {e}")
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
                break

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
        return response["choices"][0]["message"].get("content", "")


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
