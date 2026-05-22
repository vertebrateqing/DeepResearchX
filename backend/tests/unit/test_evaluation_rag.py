"""End-to-end tests for RAG evaluator."""

import json
from pathlib import Path

import pytest

from deep_research.evaluation.models import RAGTestCase
from deep_research.evaluation.rag_evaluator import RAGEvaluator
from deep_research.rag.document_loader import Document
from deep_research.rag.pipeline import RAGPipeline
from deep_research.rag.vector_store import ChromaVectorStore


class FakeEmbeddingService:
    """Deterministic embedding service for tests.

    Each registered text gets a unique one-hot vector so cosine distance
    between distinct texts is exactly 1.0 (orthogonal) and between identical
    texts is 0.0.
    """

    DIM = 50

    def __init__(self):
        self._registry: dict[str, list[float]] = {}
        self._next_idx = 0

    def register(self, text: str) -> list[float]:
        if text in self._registry:
            return self._registry[text]
        vec = [0.0] * self.DIM
        vec[self._next_idx] = 1.0
        self._registry[text] = vec
        self._next_idx += 1
        return vec

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._registry.get(t, [0.0] * self.DIM) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._registry.get(query, [0.0] * self.DIM)

    async def close(self):
        pass


@pytest.fixture
def fake_emb():
    return FakeEmbeddingService()


@pytest.fixture
def pipeline(tmp_path, fake_emb):
    """RAGPipeline seeded with 2 docs, each having 1 chunk."""
    vector_store = ChromaVectorStore(
        collection_name="test_eval",
        persist_directory=str(tmp_path / "chroma"),
    )

    # Register texts and add to vector store directly
    chunk_texts = [
        "比亚迪2024年销量达到350万辆，蝉联全球新能源汽车销量冠军。",
        "特斯拉2024年全球交付约180万辆，Model Y为最畅销车型。",
    ]
    embeddings = [fake_emb.register(t) for t in chunk_texts]
    vector_store.add_documents(
        documents=chunk_texts,
        embeddings=embeddings,
        metadatas=[
            {"doc_id": "doc1", "filename": "byd_report.txt"},
            {"doc_id": "doc2", "filename": "tesla_report.txt"},
        ],
        ids=["doc1__chunk__0", "doc2__chunk__0"],
    )

    return RAGPipeline(
        collection_name="test_eval",
        vector_store=vector_store,
        embedding_service=fake_emb,
    )


@pytest.fixture
def benchmark_path(tmp_path, fake_emb):
    """Write a small benchmark dataset to disk.

    Queries use the same embedding as their target chunk by registering
    the query text with the same vector.
    """
    # Query 1 targets doc1 chunk
    fake_emb._registry["比亚迪销量"] = fake_emb._registry[
        "比亚迪2024年销量达到350万辆，蝉联全球新能源汽车销量冠军。"
    ]
    # Query 2 targets doc2 chunk
    fake_emb._registry["特斯拉交付量"] = fake_emb._registry[
        "特斯拉2024年全球交付约180万辆，Model Y为最畅销车型。"
    ]

    cases = [
        RAGTestCase(
            query_id="q1",
            query="比亚迪销量",
            relevant_chunk_ids=["doc1__chunk__0"],
            category="industry_data",
        ),
        RAGTestCase(
            query_id="q2",
            query="特斯拉交付量",
            relevant_chunk_ids=["doc2__chunk__0"],
            category="industry_data",
        ),
    ]

    path = tmp_path / "benchmark.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for case in cases:
            f.write(case.model_dump_json() + "\n")
    return path


class TestRAGEvaluator:
    @pytest.mark.asyncio
    async def test_evaluate_query_perfect_match(self, pipeline, benchmark_path, fake_emb):
        evaluator = RAGEvaluator(pipeline=pipeline, benchmark_path=benchmark_path)
        result = await evaluator.evaluate_query(evaluator.cases[0], top_k=5, hybrid=False)

        assert result.query_id == "q1"
        assert result.precision_at_k[1] == 1.0
        assert result.recall_at_k[1] == 1.0
        assert result.mrr == 1.0
        assert result.retrieved_count >= 1

    @pytest.mark.asyncio
    async def test_run_aggregates_correctly(self, pipeline, benchmark_path):
        evaluator = RAGEvaluator(pipeline=pipeline, benchmark_path=benchmark_path)
        report = await evaluator.run(top_k=5, ks=[1, 3], hybrid=False)

        assert report.total_queries == 2
        assert report.avg_mrr == 1.0
        assert report.avg_recall_at_k[1] == 1.0
        assert report.avg_precision_at_k[1] == 1.0
        assert len(report.failures) == 0
        assert report.per_category["industry_data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_zero_recall_reported_as_failure(self, pipeline, benchmark_path, fake_emb):
        # Add a query with no matching embedding → should get zero recall
        fake_emb._registry["完全不相关的查询"] = [0.0] * fake_emb.DIM

        extra_case = RAGTestCase(
            query_id="q3",
            query="完全不相关的查询",
            relevant_chunk_ids=["nonexistent__chunk__0"],
            category="test",
        )
        path = benchmark_path.parent / "benchmark_with_fail.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for case in RAGEvaluator._load_benchmark(benchmark_path):
                f.write(case.model_dump_json() + "\n")
            f.write(extra_case.model_dump_json() + "\n")

        evaluator = RAGEvaluator(pipeline=pipeline, benchmark_path=path)
        report = await evaluator.run(top_k=5, ks=[1], hybrid=False)

        assert report.total_queries == 3
        assert len(report.failures) == 1
        assert report.failures[0]["query_id"] == "q3"
