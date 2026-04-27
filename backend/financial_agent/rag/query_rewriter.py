"""Query rewriter for expanding a single query into multiple semantic variants.

Used before vector retrieval and web search to improve recall by covering
different query angles and keyword variations.
"""

import json
import logging
from typing import Any

from financial_agent.core.agent import LLMClient

logger = logging.getLogger(__name__)

DEFAULT_REWRITE_PROMPT = """你是一个专业的查询改写专家。请将以下用户查询改写为多个语义等价但表达方式不同的查询变体，以提高信息检索的召回率。

原始查询：{query}

要求：
1. 生成 {n_variants} 个查询变体
2. 每个变体应从不同角度切入（如：财务指标角度、行业趋势角度、公司基本面角度、市场情绪角度）
3. 可以使用不同的关键词表达同一概念
4. 可以适当补充相关关键词，但不要添加原始查询中没有的假设信息
5. 保持查询的核心意图不变

请以JSON数组格式返回，每个元素是一个改写后的查询字符串：
["改写查询1", "改写查询2", ...]

只返回JSON数组，不要解释。"""


class QueryRewriter:
    """Rewrites a query into multiple variants for better retrieval coverage."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def rewrite(
        self,
        query: str,
        n_variants: int = 3,
        custom_prompt: str | None = None,
    ) -> list[str]:
        """Rewrite query into N semantic variants.

        Args:
            query: Original user query
            n_variants: Number of variants to generate
            custom_prompt: Optional custom prompt template

        Returns:
            List of query variants (original query is always first)
        """
        prompt = (custom_prompt or DEFAULT_REWRITE_PROMPT).format(
            query=query,
            n_variants=n_variants,
        )

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": "你是一个查询改写专家，擅长从不同角度改写查询以提高信息检索效果。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=512,
            )
            content = response["choices"][0]["message"].get("content", "")
            variants = self._parse_variants(content)

            # Always include the original query as the first variant
            if query not in variants:
                variants.insert(0, query)
            else:
                # Move original to first position if present
                variants.remove(query)
                variants.insert(0, query)

            logger.info(
                f"[QueryRewriter] Generated {len(variants)} variants for query: {query[:60]}..."
            )
            for i, v in enumerate(variants):
                logger.info(f"[QueryRewriter] Variant {i}: {v[:80]}...")

            return variants

        except Exception as e:
            logger.warning(f"[QueryRewriter] Failed to rewrite query: {e}, using original only")
            return [query]

    def _parse_variants(self, content: str) -> list[str]:
        """Parse LLM response into list of query variants."""
        content = content.strip()

        # Try to extract JSON array
        try:
            # Find JSON array in response
            start = content.find("[")
            end = content.rfind("]")
            if start != -1 and end != -1 and end > start:
                json_str = content[start : end + 1]
                variants = json.loads(json_str)
                if isinstance(variants, list):
                    return [str(v).strip() for v in variants if str(v).strip()]
        except json.JSONDecodeError:
            pass

        # Fallback: try line-by-line parsing (numbered list or plain lines)
        variants = []
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Remove common prefixes like "1. ", "- ", "* "
            for prefix in ("1.", "2.", "3.", "4.", "5.", "-", "*"):
                if line.startswith(prefix):
                    line = line[len(prefix) :].strip()
                    break
            # Remove quotes
            line = line.strip('"').strip("'")
            if line and len(line) > 3:
                variants.append(line)

        return variants
