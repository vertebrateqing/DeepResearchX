"""Multimodal processing for PDF/HTML documents with charts and images."""

from a_stock_analyzer.rag.multimodal.vlm_processor import VLMProcessor
from a_stock_analyzer.rag.multimodal.pdf_extractor import MultimodalPDFExtractor
from a_stock_analyzer.rag.multimodal.unified_document import (
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
