"""Unified document schema for multimodal content."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChunkType(str, Enum):
    """Type of document chunk."""

    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    CHART = "chart"  # Sub-type of image for charts/graphs
    MARKDOWN = "markdown"


@dataclass
class DocumentChunk:
    """A single chunk of a document."""

    chunk_type: ChunkType
    content: str  # Text content, table markdown, or image path/base64
    metadata: dict[str, Any] = field(default_factory=dict)
    page_number: int = 0
    chunk_index: int = 0

    # For image chunks
    image_path: str = ""  # Path to extracted image file
    caption: str = ""  # Detected or generated caption
    ocr_text: str = ""  # OCR-extracted text from image
    vlm_description: str = ""  # VLM-generated description
    chart_data: dict[str, Any] = field(default_factory=dict)  # Structured chart data

    def to_text_for_embedding(self) -> str:
        """Convert chunk to text suitable for embedding.

        For images/charts, combines OCR text + VLM description + caption.
        """
        if self.chunk_type == ChunkType.TEXT:
            return self.content
        elif self.chunk_type == ChunkType.TABLE:
            return f"表格: {self.content}"
        elif self.chunk_type in (ChunkType.IMAGE, ChunkType.CHART):
            parts = []
            if self.caption:
                parts.append(f"图片标题: {self.caption}")
            if self.vlm_description:
                parts.append(f"图片描述: {self.vlm_description}")
            if self.ocr_text:
                parts.append(f"图中文字: {self.ocr_text}")
            if self.chart_data:
                parts.append(f"图表数据: {self.chart_data}")
            return "\n".join(parts) if parts else self.content
        else:
            return self.content

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_type": self.chunk_type.value,
            "content": self.content,
            "metadata": self.metadata,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "image_path": self.image_path,
            "caption": self.caption,
            "ocr_text": self.ocr_text,
            "vlm_description": self.vlm_description,
            "chart_data": self.chart_data,
        }


@dataclass
class UnifiedDocument:
    """A document with all modalities unified."""

    source_path: str
    doc_type: str  # "pdf", "html", "text"
    chunks: list[DocumentChunk] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_text_chunks(self) -> list[DocumentChunk]:
        """Get text-only chunks."""
        return [c for c in self.chunks if c.chunk_type == ChunkType.TEXT]

    def get_table_chunks(self) -> list[DocumentChunk]:
        """Get table chunks."""
        return [c for c in self.chunks if c.chunk_type == ChunkType.TABLE]

    def get_image_chunks(self) -> list[DocumentChunk]:
        """Get image/chart chunks."""
        return [c for c in self.chunks if c.chunk_type in (ChunkType.IMAGE, ChunkType.CHART)]

    def get_chart_chunks(self) -> list[DocumentChunk]:
        """Get chart-specific chunks."""
        return [c for c in self.chunks if c.chunk_type == ChunkType.CHART]

    def to_embedding_texts(self) -> list[str]:
        """Convert all chunks to texts for embedding."""
        return [chunk.to_text_for_embedding() for chunk in self.chunks]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "doc_type": self.doc_type,
            "metadata": self.metadata,
            "chunks": [c.to_dict() for c in self.chunks],
        }
