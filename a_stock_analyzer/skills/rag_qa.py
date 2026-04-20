"""RAG QA skill for financial report analysis."""

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from a_stock_analyzer.core.base import BaseSkill, SkillContext
from a_stock_analyzer.rag.pipeline import RAGPipeline

logger = logging.getLogger(__name__)


class RAGQAInput(BaseModel):
    query: str = Field(..., description="用户问题")
    company: Optional[str] = Field(default=None, description="公司名称或代码（可选，用于过滤）")
    top_k: int = Field(default=5, description="检索文档数量")


class RAGQAOutput(BaseModel):
    answer: str = Field(default="", description="回答")
    sources: list[str] = Field(default_factory=list, description="信息来源")
    confidence: str = Field(default="medium", description="置信度: high/medium/low")


class RAGQASkill(BaseSkill):
    """Answer questions using RAG on financial reports."""

    name = "rag_qa"
    description = "基于财报RAG系统回答用户关于具体公司的问题"
    input_schema = RAGQAInput
    output_schema = RAGQAOutput

    def __init__(self) -> None:
        self.pipeline = RAGPipeline()

    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        """Execute RAG QA."""
        parsed = RAGQAInput(**inputs)

        # Build filter if company specified
        filter_dict = None
        if parsed.company:
            filter_dict = {
                "$or": [
                    {"company": {"$eq": parsed.company}},
                    {"symbol": {"$eq": parsed.company}},
                ]
            }

        try:
            result = await self.pipeline.query_and_answer(
                query=parsed.query,
                top_k=parsed.top_k,
                filter_dict=filter_dict,
            )

            # Determine confidence based on result quality
            confidence = "medium"
            if result["documents"]:
                top_score = result["documents"][0].get("rerank_score", 0)
                if top_score > 0.8:
                    confidence = "high"
                elif top_score < 0.5:
                    confidence = "low"

            output = RAGQAOutput(
                answer=result["answer"],
                sources=result["sources"],
                confidence=confidence,
            )
            return output.model_dump()
        except Exception as e:
            logger.error(f"RAG QA failed: {e}")
            return RAGQAOutput(
                answer=f"查询失败: {str(e)}",
                confidence="low",
            ).model_dump()
