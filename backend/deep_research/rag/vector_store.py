from __future__ import annotations
"""ChromaDB vector store wrapper."""

import logging
import os
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from deep_research.config.settings import get_settings

logger = logging.getLogger(__name__)


class ChromaVectorStore:
    """ChromaDB vector store for document embeddings."""

    def __init__(
        self,
        collection_name: Optional[str] = None,
        persist_directory: Optional[str] = None,
        distance_fn: Optional[str] = None,
    ) -> None:
        settings = get_settings().rag.vector_db
        self.collection_name = collection_name or settings.collection_name
        self.persist_directory = persist_directory or settings.path
        self.distance_fn = distance_fn or settings.distance_fn

        self._client: Optional[Any] = None
        self._collection: Optional[Any] = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import chromadb

            Path(self.persist_directory).parent.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_directory)
        return self._client

    @property
    def collection(self) -> Any:
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": self.distance_fn},
            )
        return self._collection

    def add_documents(
        self,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: Optional[list[dict[str, Any]]] = None,
        ids: Optional[list[str]] = None,
    ) -> list[str]:
        """Add documents with embeddings to the store."""
        if ids is None:
            ids = [str(uuid4()) for _ in documents]

        if metadatas is None:
            metadatas = [{} for _ in documents]

        batch_size = 100
        for i in range(0, len(documents), batch_size):
            batch_docs = documents[i : i + batch_size]
            batch_embeddings = embeddings[i : i + batch_size]
            batch_metadatas = metadatas[i : i + batch_size]
            batch_ids = ids[i : i + batch_size]

            self.collection.add(
                documents=batch_docs,
                embeddings=batch_embeddings,
                metadatas=batch_metadatas,
                ids=batch_ids,
            )

        logger.info(f"Added {len(documents)} documents to vector store")
        return ids

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_dict: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Search for similar documents."""
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=filter_dict,
            include=["documents", "metadatas", "distances"],
        )

        documents = []
        for i in range(len(results["ids"][0])):
            doc = {
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "score": float(results["distances"][0][i]),
            }
            documents.append(doc)

        return documents

    def delete(self, ids: Optional[list[str]] = None, filter_dict: Optional[dict[str, Any]] = None) -> None:
        """Delete documents by IDs or filter."""
        if ids:
            self.collection.delete(ids=ids)
        elif filter_dict:
            self.collection.delete(where=filter_dict)

    def get_document(self, doc_id: str) -> Optional[dict[str, Any]]:
        """Get a document by ID."""
        result = self.collection.get(ids=[doc_id], include=["documents", "metadatas"])
        if result["ids"]:
            return {
                "id": result["ids"][0],
                "content": result["documents"][0],
                "metadata": result["metadatas"][0] if result["metadatas"] else {},
            }
        return None

    def count(self) -> int:
        """Get total document count."""
        return self.collection.count()

    def clear(self) -> None:
        """Clear all documents from the collection."""
        self.client.delete_collection(self.collection_name)
        self._collection = None
