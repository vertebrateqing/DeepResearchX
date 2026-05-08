"""RAG package: document loading, chunking, embedding, retrieval."""

# Keep this empty to avoid circular imports triggered by tests importing
# submodules directly (e.g. deep_research.rag.text_splitter). Heavy
# dependencies (EmbeddingService, ChromaVectorStore, RAGPipeline) pull in
# deep_research.core.base via embedding_call and should be imported from
# their own submodules rather than through this package __init__.
