"""Multimodal processing for PDF/HTML documents with charts and images."""

from financial_agent.rag.multimodal.vlm_processor import VLMProcessor
from financial_agent.rag.multimodal.pdf_extractor import MultimodalPDFExtractor
from financial_agent.rag.multimodal.unified_document import (
    UnifiedDocument,
    DocumentChunk,
    ChunkType,
)

__all__ = [
    "VLMProcessor",
    "MultimodalPDFExtractor",
    "UnifiedDocument",
    "DocumentChunk",
    "ChunkType",
]
