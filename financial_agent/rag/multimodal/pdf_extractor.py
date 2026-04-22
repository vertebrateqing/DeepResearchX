"""Multimodal PDF extractor that handles text, tables, and images/charts."""

import io
import logging
from pathlib import Path
from typing import Any

import pdfplumber

from financial_agent.rag.multimodal.unified_document import (
    ChunkType,
    DocumentChunk,
    UnifiedDocument,
)
from financial_agent.rag.multimodal.vlm_processor import VLMProcessor

logger = logging.getLogger(__name__)


class MultimodalPDFExtractor:
    """Extract text, tables, and images from PDFs.

    For financial reports, specifically handles:
    - Text paragraphs
    - Data tables
    - Charts and graphs (sent to VLM for understanding)
    """

    def __init__(
        self,
        vlm_processor: VLMProcessor | None = None,
        extract_images: bool = True,
        image_output_dir: str | Path | None = None,
    ) -> None:
        self.vlm = vlm_processor or VLMProcessor()
        self.extract_images = extract_images
        self.image_output_dir = Path(image_output_dir or "./financial_agent/data/processed/images")
        self.image_output_dir.mkdir(parents=True, exist_ok=True)

    def load(self, file_path: str | Path) -> UnifiedDocument:
        """Load a PDF and extract all content types.

        Args:
            file_path: Path to PDF file

        Returns:
            UnifiedDocument with text, table, and image chunks
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Loading multimodal PDF: {file_path}")

        doc = UnifiedDocument(
            source_path=str(file_path),
            doc_type="pdf",
            metadata={
                "filename": file_path.name,
                "file_size": file_path.stat().st_size,
            },
        )

        chunk_index = 0

        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # 1. Extract text
                text = page.extract_text() or ""
                if text.strip():
                    # Split text into paragraphs
                    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
                    for para in paragraphs:
                        doc.chunks.append(DocumentChunk(
                            chunk_type=ChunkType.TEXT,
                            content=para,
                            page_number=page_num,
                            chunk_index=chunk_index,
                            metadata={"page": page_num},
                        ))
                        chunk_index += 1

                # 2. Extract tables
                tables = page.extract_tables()
                for table_idx, table in enumerate(tables):
                    table_text = self._format_table(table)
                    if table_text:
                        doc.chunks.append(DocumentChunk(
                            chunk_type=ChunkType.TABLE,
                            content=table_text,
                            page_number=page_num,
                            chunk_index=chunk_index,
                            metadata={
                                "page": page_num,
                                "table_index": table_idx,
                            },
                        ))
                        chunk_index += 1

                # 3. Extract images (if enabled)
                if self.extract_images:
                    try:
                        images = page.images
                        for img_idx, img in enumerate(images):
                            # Extract image region
                            image_chunk = self._process_image(
                                page, img, page_num, img_idx, chunk_index, file_path
                            )
                            if image_chunk:
                                doc.chunks.append(image_chunk)
                                chunk_index += 1
                    except Exception as e:
                        logger.warning(f"Failed to extract images from page {page_num}: {e}")

        logger.info(
            f"Extracted {len(doc.chunks)} chunks from {file_path}: "
            f"{len(doc.get_text_chunks())} text, "
            f"{len(doc.get_table_chunks())} tables, "
            f"{len(doc.get_image_chunks())} images"
        )
        return doc

    async def process_with_vlm(self, doc: UnifiedDocument) -> UnifiedDocument:
        """Process image chunks with VLM to generate descriptions.

        Args:
            doc: Document with image chunks

        Returns:
            Document with VLM descriptions added to image chunks
        """
        image_chunks = doc.get_image_chunks()
        if not image_chunks:
            return doc

        logger.info(f"Processing {len(image_chunks)} images with VLM...")

        for chunk in image_chunks:
            if chunk.image_path and Path(chunk.image_path).exists():
                try:
                    # Generate description
                    description = await self.vlm.describe_image(chunk.image_path)
                    chunk.vlm_description = description

                    # Try to extract chart data if it's a chart
                    if self._looks_like_chart(chunk.image_path):
                        chunk.chunk_type = ChunkType.CHART
                        chart_data = await self.vlm.extract_chart_data(chunk.image_path)
                        chunk.chart_data = chart_data

                        # Enhance description with chart data
                        if "key_insights" in chart_data:
                            insights = chart_data["key_insights"]
                            if isinstance(insights, list):
                                chunk.vlm_description += "\n关键洞察: " + "; ".join(insights)

                except Exception as e:
                    logger.warning(f"VLM processing failed for {chunk.image_path}: {e}")
                    chunk.vlm_description = f"图片处理失败: {str(e)}"

        return doc

    def _format_table(self, table: list[list[Any]]) -> str:
        """Format a table as markdown."""
        if not table or not table[0]:
            return ""

        rows = []
        for i, row in enumerate(table):
            cells = [str(cell or "").replace("|", "\\|").strip() for cell in row]
            rows.append("| " + " | ".join(cells) + " |")

            # Add header separator after first row
            if i == 0:
                separators = ["---"] * len(cells)
                rows.append("| " + " | ".join(separators) + " |")

        return "\n".join(rows)

    def _process_image(
        self,
        page,
        img: dict,
        page_num: int,
        img_idx: int,
        chunk_index: int,
        pdf_path: Path,
    ) -> DocumentChunk | None:
        """Process a single image from a PDF page.

        Returns a DocumentChunk or None if extraction fails.
        """
        try:
            # Crop image region
            bbox = (img["x0"], img["top"], img["x1"], img["bottom"])
            cropped = page.within_bbox(bbox)
            image_obj = cropped.to_image()

            # Save image
            image_filename = f"{pdf_path.stem}_p{page_num}_img{img_idx}.png"
            image_path = self.image_output_dir / image_filename
            image_obj.save(image_path)

            # Try OCR for text in image
            ocr_text = ""
            try:
                import pytesseract
                from PIL import Image as PILImage

                pil_img = PILImage.open(image_path)
                ocr_text = pytesseract.image_to_string(pil_img, lang="chi_sim+eng")
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"OCR failed: {e}")

            # Determine if it looks like a chart
            is_chart = self._looks_like_chart(str(image_path))
            chunk_type = ChunkType.CHART if is_chart else ChunkType.IMAGE

            return DocumentChunk(
                chunk_type=chunk_type,
                content=f"[Image on page {page_num}]",
                page_number=page_num,
                chunk_index=chunk_index,
                image_path=str(image_path),
                caption=f"Page {page_num}, Image {img_idx}",
                ocr_text=ocr_text[:500],  # Truncate long OCR
                metadata={
                    "page": page_num,
                    "image_index": img_idx,
                    "bbox": bbox,
                    "is_chart": is_chart,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to process image on page {page_num}: {e}")
            return None

    def _looks_like_chart(self, image_path: str) -> bool:
        """Heuristic to determine if an image looks like a chart.

        Uses simple heuristics based on image content.
        """
        try:
            from PIL import Image

            img = Image.open(image_path)
            width, height = img.size

            # Charts tend to be wider than tall or square-ish
            aspect_ratio = width / height if height > 0 else 1
            if not (0.5 <= aspect_ratio <= 3):
                return False

            # Charts usually have reasonable size
            if width < 200 or height < 150:
                return False

            # Check for dominant colors (charts often have distinct colors)
            img_small = img.resize((100, 100))
            pixels = list(img_small.getdata())
            unique_colors = len(set(pixels))
            # Charts typically have moderate color variety
            if unique_colors < 50 or unique_colors > 5000:
                return False

            return True
        except Exception:
            return False

    async def close(self) -> None:
        await self.vlm.close()
