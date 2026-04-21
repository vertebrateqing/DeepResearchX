"""Embedding generation tool."""

from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.base import BaseTool


class EmbeddingTool(BaseTool):
    """Tool for generating text embeddings."""

    name = "embedding"
    description = "将文本转换为向量表示，用于语义检索和相似度计算。"
    parameters = {
        "texts": {
            "type": "array",
            "description": "需要生成embedding的文本列表",
            "items": {"type": "string"},
        },
        "model": {
            "type": "string",
            "description": "模型名称（可选，默认使用配置中的模型）",
            "default": "",
        },
    }

    def __init__(self) -> None:
        self.settings = get_settings().embedding
        self._local_model: Optional[Any] = None
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = getattr(self.settings, "timeout", 60)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    async def execute(
        self,
        texts: list[str],
        model: str = "",
    ) -> dict[str, Any]:
        """Generate embeddings for texts."""
        if self.settings.provider == "openai":
            embeddings = await self._embed_openai(texts, model or self.settings.model)
        elif self.settings.provider == "local":
            embeddings = await self._embed_local(texts)
        else:
            raise ValueError(f"Unknown embedding provider: {self.settings.provider}")

        return {
            "embeddings": embeddings,
            "count": len(embeddings),
            "dimensions": len(embeddings[0]) if embeddings else 0,
            "provider": self.settings.provider,
            "model": model or self.settings.model,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _embed_openai(self, texts: list[str], model: str) -> list[list[float]]:
        """Generate embeddings using OpenAI API."""
        url = self.settings.base_url or "https://api.openai.com/v1/embeddings"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        all_embeddings = []
        batch_size = self.settings.batch_size
        total_batches = (len(texts) + batch_size - 1) // batch_size

        logger.info(f"[Embedding] Requesting {len(texts)} texts in {total_batches} batch(es), model={model}, url={url}")

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            payload = {
                "model": model,
                "input": batch,
            }

            logger.debug(f"[Embedding] Batch {i // batch_size + 1}/{total_batches}: {len(batch)} texts")
            response = await self.client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            batch_embeddings = [item["embedding"] for item in result["data"]]
            all_embeddings.extend(batch_embeddings)
            logger.info(f"[Embedding] Batch {i // batch_size + 1}/{total_batches} ok: got {len(batch_embeddings)} embeddings, dim={len(batch_embeddings[0]) if batch_embeddings else 0}")

        logger.info(f"[Embedding] Total embeddings generated: {len(all_embeddings)}")
        return all_embeddings

    async def _embed_local(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using local model."""
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer

            model_path = self.settings.local_model_path or "BAAI/bge-large-zh-v1.5"
            device = self.settings.device
            if device == "auto":
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"

            self._local_model = SentenceTransformer(model_path, device=device)

        embeddings = self._local_model.encode(
            texts,
            batch_size=self.settings.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
