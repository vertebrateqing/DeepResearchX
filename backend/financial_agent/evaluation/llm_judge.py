"""LLM-as-Judge for evaluating agent outputs."""

import json
import logging
from typing import Any

from financial_agent.core.agent import LLMClient

logger = logging.getLogger(__name__)


class LLMJudge:
    """Use LLM to judge the quality of agent outputs."""

    def __init__(self, model: str = "gpt-4o") -> None:
        self.model = model
        self.llm = LLMClient()

    async def evaluate_answer(
        self,
        question: str,
        answer: str,
        reference: str = "",
        criteria: list[str] | None = None,
    ) -> dict[str, Any]:
        """Evaluate an answer against reference using LLM judge.

        Args:
            question: The question asked
            answer: The agent's answer
            reference: Reference/gold standard answer
            criteria: Evaluation criteria

        Returns:
            Evaluation scores and reasoning
        """
        default_criteria = [
            "准确性 (Accuracy): 回答内容是否正确",
            "完整性 (Completeness): 是否涵盖了问题的各个方面",
            "相关性 (Relevance): 回答是否与问题相关",
            "清晰度 (Clarity): 回答是否清晰易懂",
            "深度 (Depth): 分析是否有深度",
        ]

        criteria_text = "\n".join(criteria or default_criteria)

        prompt = f"""你是一位严格的评估专家。请评估以下AI回答的质量。

## 问题
{question}

## AI回答
{answer}

## 参考答案（如有）
{reference if reference else "无参考答案"}

## 评估标准
{criteria_text}

请对每个标准给出1-5分的评分，并提供简要理由。
以JSON格式返回：
{{
    "scores": {{
        "accuracy": 分数,
        "completeness": 分数,
        "relevance": 分数,
        "clarity": 分数,
        "depth": 分数
    }},
    "reasoning": "评价理由",
    "overall_score": 总分,
    "overall_comment": "总体评价"
}}"""

        try:
            messages = [
                {"role": "system", "content": "你是一位专业的评估专家，严格、公正地评估AI回答质量。"},
                {"role": "user", "content": prompt},
            ]

            response = await self.llm.chat(messages=messages, model=self.model)
            content = response["choices"][0]["message"].get("content", "")

            # Extract JSON from response
            try:
                # Try to find JSON block
                if "```json" in content:
                    json_str = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    json_str = content.split("```")[1].split("```")[0]
                else:
                    json_str = content

                result = json.loads(json_str.strip())
            except json.JSONDecodeError:
                result = {
                    "raw_evaluation": content,
                    "overall_score": 3,
                }

            return result
        except Exception as e:
            logger.error(f"LLM judge evaluation failed: {e}")
            return {
                "error": str(e),
                "overall_score": 0,
            }

    async def compare_answers(
        self,
        question: str,
        answer_a: str,
        answer_b: str,
        criteria: str = "",
    ) -> dict[str, Any]:
        """Compare two answers and determine which is better."""
        prompt = f"""请比较以下两个回答，判断哪个更好。

## 问题
{question}

## 回答A
{answer_a}

## 回答B
{answer_b}

{criteria}

请判断哪个回答更好（A/B/平局），并给出理由。
以JSON格式返回：
{{
    "winner": "A/B/tie",
    "reasoning": "比较理由",
    "a_strengths": ["A的优势"],
    "b_strengths": ["B的优势"]
}}"""

        try:
            messages = [
                {"role": "system", "content": "你是一位公正的评估专家。"},
                {"role": "user", "content": prompt},
            ]

            response = await self.llm.chat(messages=messages, model=self.model)
            content = response["choices"][0]["message"].get("content", "")

            try:
                if "```json" in content:
                    json_str = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    json_str = content.split("```")[1].split("```")[0]
                else:
                    json_str = content

                result = json.loads(json_str.strip())
            except json.JSONDecodeError:
                result = {"raw_comparison": content}

            return result
        except Exception as e:
            logger.error(f"Comparison failed: {e}")
            return {"error": str(e)}
