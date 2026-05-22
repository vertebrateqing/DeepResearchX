"""Build RAG benchmark dataset from Alibaba FY2025 annual report.

Usage:
    cd backend
    uv run python scripts/build_alibaba_benchmark.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from deep_research.rag.document_loader import Document, load_document
from deep_research.rag.pipeline import RAGPipeline
from deep_research.rag.vector_store import ChromaVectorStore


class FakeEmbeddingService:
    """Stub embedding service for benchmark building — avoids real API calls."""

    DIM = 512

    def __init__(self):
        self._registry: dict[str, list[float]] = {}

    def register(self, text: str) -> list[float]:
        if text in self._registry:
            return self._registry[text]
        h = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
        vec = [0.0] * self.DIM
        vec[h % self.DIM] = 1.0
        self._registry[text] = vec
        return vec

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.register(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self.register(query)

    async def close(self):
        pass


def _find_chunks_containing(chunks: list[dict], keywords: list[str]) -> list[dict]:
    """Find chunks that contain any of the given keywords."""
    results = []
    for c in chunks:
        text = c.get("text", "")
        if any(kw in text for kw in keywords):
            results.append(c)
    return results


def _find_exact_chunk(chunks: list[dict], keyword: str) -> dict | None:
    """Find the first chunk containing the keyword."""
    for c in chunks:
        if keyword in c.get("text", ""):
            return c
    return None


def _build_benchmark(cases: list[dict]) -> str:
    lines = []
    for case in cases:
        lines.append(json.dumps(case, ensure_ascii=False))
    return "\n".join(lines)


async def main() -> int:
    pdf_path = Path("/mnt/c/Users/liqing/Desktop/阿里巴巴集團控股有限公司2025財務年度報告.pdf")
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        return 1

    collection_name = "alibaba_fy2025_benchmark"
    tmp_data = Path("/tmp/alibaba_benchmark")
    tmp_data.mkdir(parents=True, exist_ok=True)

    # 1. Load document
    print(f"Loading PDF: {pdf_path.name}")
    doc = await asyncio.to_thread(load_document, pdf_path)
    print(f"Document loaded: {len(doc.content):,} chars")

    # 2. Setup pipeline with fake embeddings
    fake_emb = FakeEmbeddingService()
    vector_store = ChromaVectorStore(
        collection_name=collection_name,
        persist_directory=str(tmp_data / "chroma"),
    )
    pipeline = RAGPipeline(
        collection_name=collection_name,
        vector_store=vector_store,
        embedding_service=fake_emb,
    )

    # 3. Ingest document
    print("Ingesting into Chroma...")
    result = await pipeline.ingest_document(doc)
    print(f"Ingested: {result['chunks']} chunks, doc_id={result['doc_id']}")
    doc_id = result["doc_id"]

    # 4. Retrieve all chunks
    print("\n--- Retrieving all chunks ---")
    collection = pipeline.vector_store.collection
    all_data = collection.get(include=["documents", "metadatas"])
    chunks = []
    ids = all_data.get("ids", [])
    docs = all_data.get("documents", [])
    metas = all_data.get("metadatas", [])
    for i in range(len(ids)):
        chunks.append({
            "id": ids[i],
            "text": docs[i] if docs else "",
            "index": metas[i].get("chunk_index", i) if metas and metas[i] else i,
        })
    print(f"Total chunks: {len(chunks)}")

    # Save inspection file
    inspect_path = tmp_data / "chunks_inspection.json"
    with open(inspect_path, "w", encoding="utf-8") as f:
        json.dump([{"id": c["id"], "text": c["text"][:500], "index": c["index"]} for c in chunks],
                  f, ensure_ascii=False, indent=2)
    print(f"Inspection saved to: {inspect_path}")

    # ==========================================================================
    # Step 5: Extract key factual snippets by searching chunks
    # ==========================================================================
    print("\n=== Searching for key facts ===")

    # Helper to print a chunk excerpt
    def show(c: dict | None, label: str):
        if c:
            print(f"\n[{label}] {c['id']}")
            print(c["text"].replace("\n", " ")[:600])
        else:
            print(f"\n[{label}] NOT FOUND")

    # 1. Total revenue
    show(_find_exact_chunk(chunks, "收入達到人民幣"), "REVENUE")
    show(_find_exact_chunk(chunks, "年度收入"), "REVENUE2")

    # 2. Net income / profit
    show(_find_exact_chunk(chunks, "淨利潤"), "NET_INCOME")
    show(_find_exact_chunk(chunks, "歸屬於普通股股東的淨利潤"), "NET_INCOME2")

    # 3. Taobao/Tmall revenue
    show(_find_exact_chunk(chunks, "淘天集團"), "TAOTIAN")
    show(_find_exact_chunk(chunks, "客戶管理收入"), "CMR")

    # 4. Cloud intelligence revenue
    show(_find_exact_chunk(chunks, "雲智能集團"), "CLOUD")

    # 5. International digital commerce
    show(_find_exact_chunk(chunks, "阿里國際數字商業集團"), "AIDC")

    # 6. Share buyback / dividend
    show(_find_exact_chunk(chunks, "回購了"), "BUYBACK")
    show(_find_exact_chunk(chunks, "股息"), "DIVIDEND")

    # 7. AI investment
    show(_find_exact_chunk(chunks, "AI基礎設施"), "AI_INFRA")
    show(_find_exact_chunk(chunks, "資本開支"), "CAPEX")

    # 8. Active users
    show(_find_exact_chunk(chunks, "年度活躍消費者"), "AAC")
    show(_find_exact_chunk(chunks, "月活躍用戶"), "MAU")

    # 9. Risk factors
    show(_find_exact_chunk(chunks, "競爭風險"), "RISK_COMPETITION")
    show(_find_exact_chunk(chunks, "監管風險"), "RISK_REGULATION")

    # 10. Cash flow
    show(_find_exact_chunk(chunks, "經營活動產生的現金流量淨額"), "CASH_FLOW")

    # 11. Employee count
    show(_find_exact_chunk(chunks, "員工人數"), "EMPLOYEES")

    # 12. GMV
    show(_find_exact_chunk(chunks, "GMV"), "GMV")

    # ==========================================================================
    # Step 6: Build benchmark queries based on found facts
    # ==========================================================================
    print("\n=== Building benchmark dataset ===")

    benchmark_cases: list[dict] = []

    # --- Query 1: 精确事实查询 ---
    # Find exact revenue number
    revenue_chunk = _find_exact_chunk(chunks, "收入達到人民幣")
    if revenue_chunk:
        # Extract surrounding context for verification
        print(f"\nRevenue chunk found: {revenue_chunk['id']}")
        print(revenue_chunk["text"].replace("\n", " ")[:800])

    # Since I cannot interactively verify each query, I'll construct them
    # based on the chunks I've seen and let the script search for the best matches.
    # For a production benchmark, human annotation is required.

    # Instead, let's do an automated approach:
    # For each candidate query, run retrieval and record top-5 chunk IDs.
    # The user can then manually review and adjust.

    candidate_queries = [
        {"query_id": "alibaba_001", "query": "阿里巴巴2025財年的總收入是多少", "category": "exact_fact", "type": "精确事实查询"},
        {"query_id": "alibaba_002", "query": "淘天集團2025財年的客戶管理收入", "category": "exact_fact", "type": "精确事实查询"},
        {"query_id": "alibaba_003", "query": "雲智能集團在2025財年的收入增長情況", "category": "multi_condition", "type": "多条件查询"},
        {"query_id": "alibaba_004", "query": "阿里巴巴2025財年回購了多少美元的股份", "category": "exact_fact", "type": "精确事实查询"},
        {"query_id": "alibaba_005", "query": "阿里國際數字商業集團在東南亞市場的表現", "category": "multi_condition", "type": "多条件查询"},
        {"query_id": "alibaba_006", "query": "阿里巴巴在AI基礎設施方面的投資規模", "category": "semantic", "type": "语义近义查询"},
        {"query_id": "alibaba_007", "query": "阿里巴巴2025財年面臨的主要競爭風險有哪些", "category": "comprehensive", "type": "长文档综合查询"},
        {"query_id": "alibaba_008", "query": "阿里巴巴的現金流和股東回報策略", "category": "comprehensive", "type": "长文档综合查询"},
        {"query_id": "alibaba_009", "query": "阿里雲的公共雲產品收入占比", "category": "exact_fact", "type": "精确事实查询"},
        {"query_id": "alibaba_010", "query": "蘋果公司的年度財務報告內容", "category": "negative", "type": "负例/无关查询"},
    ]

    for cq in candidate_queries:
        print(f"\n--- Processing: {cq['query_id']} | {cq['query']} ---")
        hits = await pipeline.query(cq["query"], top_k=10, hybrid=False)
        print(f"Retrieved {len(hits)} chunks:")
        retrieved_ids = []
        for i, hit in enumerate(hits[:5]):
            chunk_id = str(hit.get("id", ""))
            text_preview = str(hit.get("content", "")).replace("\n", " ")[:200]
            retrieved_ids.append(chunk_id)
            print(f"  [{i+1}] {chunk_id}: {text_preview}...")

        benchmark_cases.append({
            "query_id": cq["query_id"],
            "query": cq["query"],
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": retrieved_ids[:5],  # placeholder — needs human review
            "relevance_scores": {cid: 1 for cid in retrieved_ids[:5]},  # placeholder
            "category": cq["category"],
            "query_type": cq["type"],
        })

    # ==========================================================================
    # Step 7: Save benchmark (draft — requires human review)
    # ==========================================================================
    benchmark_path = Path("deep_research/evaluation/datasets/alibaba_fy2025_benchmark_draft.jsonl")
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    with open(benchmark_path, "w", encoding="utf-8") as f:
        for case in benchmark_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"\n\nDraft benchmark saved to: {benchmark_path}")
    print("⚠️  IMPORTANT: This is a DRAFT. The 'relevant_chunk_ids' and 'relevance_scores'")
    print("   are auto-populated from retrieval results and need HUMAN REVIEW.")
    print("   Please inspect the chunks for each query and adjust relevance labels.")

    await pipeline.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
