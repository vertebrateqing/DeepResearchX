from __future__ import annotations
"""LLM-driven intent clarification module.

Single-LLM-call approach: the model decides whether to ask ONE clarification
question or to directly produce an enriched research prompt. Eliminates slot
detection, numbered parsing, and string-concatenation injection.

skip_clarification=True bypasses this module entirely (eval/batch mode).
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from deep_research.core.agent import LLMClient
from deep_research.utils import extract_json_from_markdown

logger = logging.getLogger(__name__)


@dataclass
class ClarificationResult:
    """Result of intent clarification analysis.

    When complete=True, enriched_query holds the final high-quality prompt
    ready to pass to OutlinePlanner.

    When complete=False, clarification_question holds the single question
    to ask the user.
    """

    complete: bool
    original_query: str
    enriched_query: str = ""
    clarification_question: str = ""
    rounds_completed: int = 0


_ANALYZE_SYSTEM_PROMPT = (
    "你是一个专业的研究助理，负责优化用户的研究请求。"
    "你的目标是输出一个高质量、信息完整的研究提示词。"
    "你只在信息真正模糊、且无法合理推断时才向用户提问，"
    "绝大多数情况下应直接补全信息并优化提示词。"
)

_INCORPORATE_SYSTEM_PROMPT = (
    "你是一个专业的研究助理，负责将用户补充的信息融入研究请求，"
    "生成一个高质量、完整的研究提示词。"
)


class IntentClarifier:
    """LLM-driven intent clarification — single call per step."""

    MAX_ROUNDS = 2
    MAX_LLM_RETRIES = 2

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def analyze(self, query: str) -> ClarificationResult:
        """Analyze query with a single LLM call.

        Returns ClarificationResult with either:
        - complete=True  + enriched_query (ready to research)
        - complete=False + clarification_question (one question for user)

        Falls back to complete=True with original query on LLM failure.
        """
        t0 = time.perf_counter()
        result = await self._analyze_with_retry(query)
        logger.info(
            f"[IntentClarifier] analyze in {time.perf_counter()-t0:.2f}s, "
            f"complete={result.complete}, query={query[:60]}..."
        )
        return result

    async def incorporate_response(
        self,
        original_query: str,
        clarification_question: str,
        user_response: str,
    ) -> ClarificationResult:
        """Incorporate user's answer to produce final enriched query.

        Always returns complete=True. Falls back to concatenation on failure.
        """
        t0 = time.perf_counter()
        result = await self._incorporate_with_retry(
            original_query, clarification_question, user_response
        )
        logger.info(
            f"[IntentClarifier] incorporate_response in {time.perf_counter()-t0:.2f}s"
        )
        return result

    # ------------------------------------------------------------------
    # Internal: analyze
    # ------------------------------------------------------------------

    async def _analyze_with_retry(self, query: str) -> ClarificationResult:
        import asyncio
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_LLM_RETRIES + 1):
            try:
                result = await self._llm_analyze(query)
                if result is not None:
                    return result
            except Exception as e:
                last_error = e
                logger.warning(f"[IntentClarifier] analyze attempt {attempt+1} failed: {e}")
                if attempt < self.MAX_LLM_RETRIES:
                    await asyncio.sleep(2 ** attempt)

        logger.error(f"[IntentClarifier] analyze failed after all retries: {last_error}. Passthrough.")
        return ClarificationResult(complete=True, original_query=query, enriched_query=query)

    async def _llm_analyze(self, query: str) -> Optional[ClarificationResult]:
        today = datetime.now().strftime("%Y年%m月%d日")
        year = datetime.now().year

        user_prompt = f"""【当前日期】{today}

用户的原始研究请求：
{query}

请按以下逻辑处理：

**第一步：判断是否存在真正无法推断的关键歧义**

"真正无法推断"的标准（必须同时满足）：
1. 该信息的不同取值会导致研究方向根本不同
2. 无法从上下文、常识或当前日期合理推断
3. 只有用户本人才知道正确答案

**可自动补全的情况（不需要提问）：**
- 没有指定时间/年份 → 使用当前年份（{year}年）或"最新"
- 没有指定研究深度/范围 → 选择合理的全面分析
- 使用"最近""近期""最新"等词 → 理解为{year}年附近
- 没有指定报告格式 → 使用标准研究报告格式

**需要提问的情况（极少数）：**
- 名称真正有歧义且无法从语境判断（如孤立的"苹果"不知是公司还是水果）
- 研究对象完全缺失（用户只说"帮我分析一下"，没有任何主题）
- 两个完全不同的研究方向都合理且无法判断

**第二步：输出结果**

如果存在真正无法推断的关键歧义，输出：
```json
{{
  "needs_clarification": true,
  "clarification_question": "一句简洁的问题（30字以内）",
  "preliminary_enriched_query": "基于现有信息的初步优化版本"
}}
```

如果不需要提问（绝大多数情况），输出：
```json
{{
  "needs_clarification": false,
  "enriched_query": "高质量的研究提示词"
}}
```

**enriched_query 写作要求：**
- 明确研究主题和对象
- 补充合理的时间范围（如：截至{year}年的最新数据）
- 明确研究深度（深度分析/全面梳理/系统性研究）
- 列出2-4个核心分析维度
- 保留用户原始意图的所有要点
- 100-300字，语言简洁专业"""

        messages = [
            {"role": "system", "content": _ANALYZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.llm.chat(messages=messages)
        content = response["choices"][0]["message"].get("content", "")
        logger.debug(f"[IntentClarifier] LLM analyze raw: {content[:300]}")

        data = _parse_json(content)
        if data is None:
            logger.warning("[IntentClarifier] Failed to parse analyze response, using passthrough")
            return ClarificationResult(complete=True, original_query=query, enriched_query=query)

        if data.get("needs_clarification"):
            question = str(data.get("clarification_question", "")).strip()
            preliminary = str(data.get("preliminary_enriched_query", query)).strip()
            if not question:
                return ClarificationResult(
                    complete=True,
                    original_query=query,
                    enriched_query=preliminary or query,
                )
            return ClarificationResult(
                complete=False,
                original_query=query,
                enriched_query=preliminary,
                clarification_question=question,
            )
        else:
            enriched = str(data.get("enriched_query", "")).strip()
            return ClarificationResult(
                complete=True,
                original_query=query,
                enriched_query=enriched or query,
            )

    # ------------------------------------------------------------------
    # Internal: incorporate_response
    # ------------------------------------------------------------------

    async def _incorporate_with_retry(
        self,
        original_query: str,
        clarification_question: str,
        user_response: str,
    ) -> ClarificationResult:
        import asyncio
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_LLM_RETRIES + 1):
            try:
                result = await self._llm_incorporate(
                    original_query, clarification_question, user_response
                )
                if result is not None:
                    return result
            except Exception as e:
                last_error = e
                logger.warning(f"[IntentClarifier] incorporate attempt {attempt+1} failed: {e}")
                if attempt < self.MAX_LLM_RETRIES:
                    await asyncio.sleep(2 ** attempt)

        logger.error(f"[IntentClarifier] incorporate failed: {last_error}. Fallback concatenation.")
        return ClarificationResult(
            complete=True,
            original_query=original_query,
            enriched_query=f"{original_query}\n\n【用户补充】{user_response}",
            rounds_completed=1,
        )

    async def _llm_incorporate(
        self,
        original_query: str,
        clarification_question: str,
        user_response: str,
    ) -> Optional[ClarificationResult]:
        today = datetime.now().strftime("%Y年%m月%d日")
        year = datetime.now().year

        question_line = f"\n系统向用户提出的澄清问题：\n{clarification_question}\n" if clarification_question else ""

        user_prompt = f"""【当前日期】{today}

用户的原始研究请求：
{original_query}
{question_line}
用户的回答：
{user_response}

请将用户的回答融入原始请求，生成一个高质量的研究提示词。

要求：
1. 完整保留原始请求的所有意图
2. 将用户的补充信息自然融入（不要显式标注"用户回答了XXX"）
3. 补充合理的时间范围（如没有指定，使用{year}年）
4. 明确研究深度和分析维度
5. 如果用户的回答是"随便""都行""默认"等，按最合理的方式处理
6. 只输出最终的研究提示词，不要解释或说明

直接输出研究提示词："""

        messages = [
            {"role": "system", "content": _INCORPORATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.llm.chat(messages=messages)
        content = response["choices"][0]["message"].get("content", "").strip()
        logger.debug(f"[IntentClarifier] LLM incorporate raw: {content[:200]}")

        if not content or len(content) < 5:
            return ClarificationResult(
                complete=True,
                original_query=original_query,
                enriched_query=f"{original_query}\n\n【用户补充】{user_response}",
                rounds_completed=1,
            )

        enriched = content.strip('"').strip("'")
        return ClarificationResult(
            complete=True,
            original_query=original_query,
            enriched_query=enriched,
            rounds_completed=1,
        )


def _parse_json(content: str) -> Optional[dict]:
    """Extract and parse JSON from LLM response."""
    try:
        return json.loads(extract_json_from_markdown(content).lstrip("\ufeff"))
    except (json.JSONDecodeError, IndexError, ValueError) as e:
        logger.warning(f"[IntentClarifier] JSON parse failed: {e}, content={content[:200]}")
        return None
