"""Embedding service for RAG."""

from typing import Any, Optional

from financial_agent.tools.embedding_call import EmbeddingTool


class EmbeddingService:
    """High-level embedding service for RAG pipeline."""

    def __init__(self) -> None:
        self._tool: Optional[EmbeddingTool] = None

    @property
    def tool(self) -> EmbeddingTool:
        if self._tool is None:
            self._tool = EmbeddingTool()
        return self._tool

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts."""
        result = await self.tool.execute(texts=texts)
        return result["embeddings"]

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single query."""
        embeddings = await self.embed_texts([query])
        return embeddings[0]

    async def close(self) -> None:
        await self.tool.close()
