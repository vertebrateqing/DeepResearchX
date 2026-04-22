"""Long-term memory storage using ChromaDB for semantic memory and JSON for preferences."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.memory.models import MemoryFinding, UserPreferences
from a_stock_analyzer.rag.embedding import EmbeddingService
from a_stock_analyzer.rag.vector_store import ChromaVectorStore

logger = logging.getLogger(__name__)

DEFAULT_PREFS_PATH = Path("./a_stock_analyzer/data/user_preferences.json")


class LongTermStore:
    """Long-term memory for user preferences and semantic findings.

    - Semantic memories (findings, conclusions) stored in ChromaDB
    - User preferences stored in JSON file
    """

    def __init__(
        self,
        user_id: str = "anonymous",
        vector_store: ChromaVectorStore | None = None,
    ) -> None:
        self.user_id = user_id
        self.vector_store = vector_store or ChromaVectorStore(
            collection_name=f"user_memory_{user_id}",
        )
        self.embedding_service = EmbeddingService()
        self.prefs_path = DEFAULT_PREFS_PATH.parent / f"{user_id}_preferences.json"
        self.prefs_path.parent.mkdir(parents=True, exist_ok=True)

    # --- User Preferences ---

    def load_preferences(self) -> UserPreferences:
        """Load user preferences from JSON."""
        if not self.prefs_path.exists():
            return UserPreferences()

        with open(self.prefs_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return UserPreferences.from_dict(data)

    def save_preferences(self, prefs: UserPreferences) -> None:
        """Save user preferences to JSON."""
        with open(self.prefs_path, "w", encoding="utf-8") as f:
            json.dump(prefs.to_dict(), f, ensure_ascii=False, indent=2)

    def update_preferences(self, **kwargs: Any) -> UserPreferences:
        """Update and save user preferences."""
        prefs = self.load_preferences()
        for key, value in kwargs.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        self.save_preferences(prefs)
        return prefs

    # --- Semantic Memory (Findings) ---

    async def add_finding(self, finding: MemoryFinding) -> str:
        """Add a finding to long-term semantic memory.

        Args:
            finding: The finding to store

        Returns:
            Document ID in vector store
        """
        _log = logging.getLogger(__name__)
        _log.info(f"[LongTermStore] Adding finding {finding.finding_id}, source={finding.source}, content_len={len(finding.content)}")
        # Generate embedding
        embedding = await self.embedding_service.embed_query(finding.content)
        _log.info(f"[LongTermStore] Embedding generated for {finding.finding_id}, dim={len(embedding)}")

        # Metadata
        metadata = {
            "finding_id": finding.finding_id,
            "source": finding.source,
            "source_ref": finding.source_ref,
            "confidence": finding.confidence,
            "related_entities": json.dumps(finding.related_entities, ensure_ascii=False),
            "extracted_at": finding.extracted_at.isoformat(),
            "user_id": self.user_id,
        }

        if finding.expires_at:
            metadata["expires_at"] = finding.expires_at.isoformat()

        doc_ids = self.vector_store.add_documents(
            documents=[finding.content],
            embeddings=[embedding],
            metadatas=[metadata],
            ids=[finding.finding_id],
        )

        _log.info(f"Added finding {finding.finding_id} to long-term memory")
        return doc_ids[0]

    async def search_findings(
        self,
        query: str,
        top_k: int = 10,
        min_confidence: float = 0.0,
        entity_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search relevant findings by semantic similarity.

        Args:
            query: Search query
            top_k: Number of results
            min_confidence: Minimum confidence threshold
            entity_filter: Filter by related entities

        Returns:
            List of findings with scores
        """
        query_embedding = await self.embedding_service.embed_query(query)

        # Build filter
        filter_dict = None
        if min_confidence > 0:
            filter_dict = {"confidence": {"$gte": min_confidence}}

        results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filter_dict=filter_dict,
        )

        # Post-filter by entity if specified
        if entity_filter:
            filtered = []
            for r in results:
                entities_str = r.get("metadata", {}).get("related_entities", "[]")
                try:
                    entities = json.loads(entities_str)
                except json.JSONDecodeError:
                    entities = []
                if any(e in entities for e in entity_filter):
                    filtered.append(r)
            results = filtered

        # Check expiration
        valid_results = []
        for r in results:
            expires_str = r.get("metadata", {}).get("expires_at")
            if expires_str:
                expires = datetime.fromisoformat(expires_str)
                if datetime.now() > expires:
                    continue  # Skip expired
            valid_results.append(r)

        return valid_results

    async def find_related(
        self,
        entity: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Find findings related to a specific entity."""
        return await self.search_findings(
            query=f"关于{entity}的信息",
            top_k=top_k,
            entity_filter=[entity],
        )

    def delete_finding(self, finding_id: str) -> None:
        """Delete a finding by ID."""
        self.vector_store.delete(ids=[finding_id])

    def clear_all_findings(self) -> None:
        """Clear all findings for this user."""
        self.vector_store.clear()
