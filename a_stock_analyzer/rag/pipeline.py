"""Complete RAG pipeline for financial report QA."""

import asyncio
import logging
from typing import Any, Optional

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.rag.document_loader import Document, PDFDocumentLoader
from a_stock_analyzer.rag.embedding import EmbeddingService
from a_stock_analyzer.rag.hybrid_retriever import HybridRetriever
from a_stock_analyzer.rag.query_rewriter import QueryRewriter
from a_stock_analyzer.rag.reranker import CrossEncoderReranker
from a_stock_analyzer.rag.text_splitter import RecursiveTextSplitter

logger = logging.getLogger(__name__)


def _merge_retrieval_results(
    all_results: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Merge retrieval results from multiple query variants.

    Deduplicates by doc_id, keeps the highest score, sorts by score.
    """
    seen: dict[str, dict[str, Any]] = {}
    for results in all_results:
        for doc in results:
            doc_id = doc.get("id", "")
            if not doc_id:
                continue
            score = doc.get("score", 0)
            if doc_id in seen:
                # Keep the better score (lower distance = better for cosine/l2)
                if score < seen[doc_id]["score"]:
                    seen[doc_id] = doc
            else:
                seen[doc_id] = doc

    # Sort by score (lower distance = better for cosine/l2)
    merged = sorted(seen.values(), key=lambda d: d.get("score", float("inf")))
    return merged


class RAGPipeline:
    """End-to-end RAG pipeline for financial report analysis.

    Pipeline:
    1. Load documents (PDF/text)
    2. Split into chunks
    3. Generate embeddings
    4. Index into vector store + BM25
    5. Retrieve relevant chunks for a query
    6. Generate answer with LLM
    """

    def __init__(
        self,
        retriever: Optional[HybridRetriever] = None,
        embedding_service: Optional[EmbeddingService] = None,
        text_splitter: Optional[RecursiveTextSplitter] = None,
        reranker: Optional[CrossEncoderReranker] = None,
        query_rewriter: Optional[QueryRewriter] = None,
    ) -> None:
        self.retriever = retriever or HybridRetriever()
        self.embedding_service = embedding_service or EmbeddingService()
        self.text_splitter = text_splitter or RecursiveTextSplitter()
        self.reranker = reranker or CrossEncoderReranker()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.settings = get_settings().rag.retrieval

    async def ingest_documents(
        self,
        documents: list[Document],
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> list[str]:
        """Ingest documents into the retrieval system.

        Args:
            documents: List of Document objects
            extra_metadata: Additional metadata to add to all chunks

        Returns:
            List of chunk IDs
        """
        all_chunks = []
        all_metadatas = []

        for doc in documents:
            # Split document into chunks
            chunks = self.text_splitter.split_text(doc.content)

            for i, chunk in enumerate(chunks):
                metadata = {
                    **doc.metadata,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                }
                if extra_metadata:
                    metadata.update(extra_metadata)

                all_chunks.append(chunk)
                all_metadatas.append(metadata)

        if not all_chunks:
            logger.warning("No chunks generated from documents")
            return []

        logger.info(f"Generated {len(all_chunks)} chunks from {len(documents)} documents")

        # Generate embeddings
        embeddings = await self.embedding_service.embed_texts(all_chunks)

        # Index into both stores
        doc_ids = self.retriever.add_documents(
            documents=all_chunks,
            embeddings=embeddings,
            metadatas=all_metadatas,
        )

        logger.info(f"Indexed {len(doc_ids)} chunks")
        return doc_ids

    async def ingest_pdf(self, file_path: str, extra_metadata: Optional[dict[str, Any]] = None) -> list[str]:
        """Ingest a PDF file (legacy text-only mode).

        Args:
            file_path: Path to PDF file
            extra_metadata: Additional metadata

        Returns:
            List of chunk IDs
        """
        loader = PDFDocumentLoader()
        documents = loader.load(file_path)
        return await self.ingest_documents(documents, extra_metadata)

    async def ingest_multimodal_pdf(
        self,
        file_path: str,
        extra_metadata: Optional[dict[str, Any]] = None,
        use_vlm: bool = True,
    ) -> list[str]:
        """Ingest a PDF file with multimodal support (text, tables, charts).

        Args:
            file_path: Path to PDF file
            extra_metadata: Additional metadata
            use_vlm: Whether to use VLM for chart understanding

        Returns:
            List of chunk IDs
        """
        from a_stock_analyzer.rag.multimodal.pdf_extractor import MultimodalPDFExtractor

        extractor = MultimodalPDFExtractor()

        # Extract all content types
        doc = extractor.load(file_path)

        # Process images with VLM if enabled
        if use_vlm and doc.get_image_chunks():
            doc = await extractor.process_with_vlm(doc)

        # Convert chunks to embedding texts
        all_texts = doc.to_embedding_texts()
        all_chunks = doc.chunks

        if not all_texts:
            logger.warning("No content extracted from PDF")
            return []

        # Build metadata for each chunk
        all_metadatas = []
        for chunk in all_chunks:
            metadata = {
                **extra_metadata,
                "chunk_type": chunk.chunk_type.value,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "source": file_path,
            }
            if chunk.image_path:
                metadata["image_path"] = chunk.image_path
            if chunk.chart_data:
                metadata["chart_data"] = str(chunk.chart_data)
            all_metadatas.append(metadata)

        logger.info(
            f"Extracted {len(all_texts)} chunks from multimodal PDF: "
            f"{len(doc.get_text_chunks())} text, "
            f"{len(doc.get_table_chunks())} tables, "
            f"{len(doc.get_image_chunks())} images/charts"
        )

        # Generate embeddings
        embeddings = await self.embedding_service.embed_texts(all_texts)

        # Index into both stores
        doc_ids = self.retriever.add_documents(
            documents=all_texts,
            embeddings=embeddings,
            metadatas=all_metadatas,
        )

        logger.info(f"Indexed {len(doc_ids)} multimodal chunks")
        return doc_ids

    async def query(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_dict: Optional[dict[str, Any]] = None,
        use_rerank: Optional[bool] = None,
        rewrite: bool = True,
    ) -> dict[str, Any]:
        """Query the RAG system.

        Args:
            query: User query
            top_k: Number of results to return
            filter_dict: Metadata filter
            use_rerank: Whether to use reranking
            rewrite: Whether to rewrite query into multiple variants

        Returns:
            Dict with retrieved documents and metadata
        """
        top_k = top_k or self.settings.top_k_final
        use_rerank = use_rerank if use_rerank is not None else self.settings.rerank

        # Query rewriting: expand into multiple variants
        queries = [query]
        if rewrite:
            queries = await self.query_rewriter.rewrite(query, n_variants=3)

        # Generate embeddings for all variants
        query_embeddings = await self.embedding_service.embed_texts(queries)

        # Retrieve documents for each variant in parallel
        retrieval_tasks = [
            self.retriever.retrieve(
                query=q,
                query_embedding=emb,
                filter_dict=filter_dict,
            )
            for q, emb in zip(queries, query_embeddings)
        ]
        all_results = await asyncio.gather(*retrieval_tasks)

        # Merge results from all variants
        results = _merge_retrieval_results(all_results)

        logger.info(
            f"[RAGPipeline] Query variants: {len(queries)}, "
            f"merged unique docs: {len(results)} for original query: {query[:50]}..."
        )

        # Rerank if enabled
        if use_rerank and results:
            results = await self.reranker.rerank(
                query=query,
                documents=results,
                top_k=self.settings.rerank_top_k,
            )

        return {
            "query": query,
            "queries_expanded": queries,
            "results": results,
            "total_results": len(results),
            "retriever_type": "hybrid",
        }

    async def generate_answer(
        self,
        query: str,
        context_documents: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate an answer using retrieved context.

        Args:
            query: User question
            context_documents: Retrieved documents
            system_prompt: Optional system prompt

        Returns:
            Generated answer
        """
        from a_stock_analyzer.core.agent import LLMClient

        # Build context from documents (handle multimodal content)
        context_parts = []
        for i, doc in enumerate(context_documents):
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            source = metadata.get("source", "unknown")
            chunk_type = metadata.get("chunk_type", "text")

            part = f"[Document {i+1}] Source: {source}"
            if chunk_type != "text":
                part += f" Type: {chunk_type}"

            # For chart/image chunks, include chart data if available
            if chunk_type in ("image", "chart") and metadata.get("chart_data"):
                chart_data = metadata["chart_data"]
                part += f"\n图表数据: {chart_data}"

            part += f"\n{content}"
            context_parts.append(part)

        context = "\n\n".join(context_parts)

        prompt = f"""基于以下财报信息，请回答用户的问题。如果信息不足以回答，请明确说明。

---

参考信息：

{context}

---

用户问题：{query}

请提供专业、准确的回答，并引用相关数据来源："""

        llm = LLMClient()

        default_system = (
            "你是一位专业的财务分析师，擅长阅读和分析上市公司财报。"
            "对于图表数据，请准确引用其中的数值和趋势。"
            "请基于提供的财报信息回答问题，确保回答准确、有理有据。"
        )

        messages = [
            {"role": "system", "content": system_prompt or default_system},
            {"role": "user", "content": prompt},
        ]

        response = await llm.chat(messages=messages)
        return response["choices"][0]["message"].get("content", "")

    async def query_and_answer(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_dict: Optional[dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """Complete RAG pipeline: retrieve and generate answer.

        Args:
            query: User question
            top_k: Number of documents to retrieve
            filter_dict: Metadata filter
            system_prompt: Optional system prompt

        Returns:
            Dict with answer, sources, and metadata
        """
        # Retrieve relevant documents
        retrieval_result = await self.query(query, top_k, filter_dict)
        documents = retrieval_result["results"]

        if not documents:
            return {
                "query": query,
                "answer": "未能找到相关的财报信息来回答此问题。",
                "sources": [],
                "documents": [],
            }

        # Generate answer
        answer = await self.generate_answer(query, documents, system_prompt)

        # Extract sources
        sources = []
        for doc in documents:
            metadata = doc.get("metadata", {})
            source = metadata.get("source", "")
            if source and source not in sources:
                sources.append(source)

        return {
            "query": query,
            "answer": answer,
            "sources": sources,
            "documents": documents,
        }
