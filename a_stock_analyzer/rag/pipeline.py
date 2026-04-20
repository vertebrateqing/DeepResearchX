"""Complete RAG pipeline for financial report QA."""

import logging
from typing import Any, Optional

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.rag.document_loader import Document, PDFDocumentLoader
from a_stock_analyzer.rag.embedding import EmbeddingService
from a_stock_analyzer.rag.hybrid_retriever import HybridRetriever
from a_stock_analyzer.rag.reranker import CrossEncoderReranker
from a_stock_analyzer.rag.text_splitter import RecursiveTextSplitter

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.retriever = retriever or HybridRetriever()
        self.embedding_service = embedding_service or EmbeddingService()
        self.text_splitter = text_splitter or RecursiveTextSplitter()
        self.reranker = reranker or CrossEncoderReranker()
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
        """Ingest a PDF file.

        Args:
            file_path: Path to PDF file
            extra_metadata: Additional metadata

        Returns:
            List of chunk IDs
        """
        loader = PDFDocumentLoader()
        documents = loader.load(file_path)
        return await self.ingest_documents(documents, extra_metadata)

    async def query(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_dict: Optional[dict[str, Any]] = None,
        use_rerank: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Query the RAG system.

        Args:
            query: User query
            top_k: Number of results to return
            filter_dict: Metadata filter
            use_rerank: Whether to use reranking

        Returns:
            Dict with retrieved documents and metadata
        """
        top_k = top_k or self.settings.top_k_final
        use_rerank = use_rerank if use_rerank is not None else self.settings.rerank

        # Generate query embedding
        query_embedding = await self.embedding_service.embed_query(query)

        # Retrieve documents
        results = await self.retriever.retrieve(
            query=query,
            query_embedding=query_embedding,
            filter_dict=filter_dict,
        )

        logger.info(f"Retrieved {len(results)} documents for query: {query[:50]}...")

        # Rerank if enabled
        if use_rerank and results:
            results = await self.reranker.rerank(
                query=query,
                documents=results,
                top_k=self.settings.rerank_top_k,
            )

        return {
            "query": query,
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

        # Build context from documents
        context_parts = []
        for i, doc in enumerate(context_documents):
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            source = metadata.get("source", "unknown")
            context_parts.append(f"[Document {i+1}] Source: {source}\n{content}")

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
