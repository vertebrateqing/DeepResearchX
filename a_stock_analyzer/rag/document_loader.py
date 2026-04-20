"""Document loaders for financial reports and other documents."""

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Document:
    """Represents a loaded document."""

    def __init__(
        self,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        source: Optional[str] = None,
    ) -> None:
        self.content = content
        self.metadata = metadata or {}
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "metadata": self.metadata,
            "source": self.source,
        }


class PDFDocumentLoader:
    """Load PDF documents, optimized for financial reports."""

    def __init__(self, extract_tables: bool = True) -> None:
        self.extract_tables = extract_tables

    def load(self, file_path: str | Path) -> list[Document]:
        """Load a PDF file and return documents."""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Loading PDF: {file_path}")

        try:
            return self._load_with_pdfplumber(file_path)
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}, trying PyPDF2")
            return self._load_with_pypdf2(file_path)

    def _load_with_pdfplumber(self, file_path: Path) -> list[Document]:
        """Load PDF using pdfplumber (better table support)."""
        import pdfplumber

        documents = []
        full_text = []

        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if text.strip():
                    full_text.append(text)

                # Extract tables if enabled
                if self.extract_tables:
                    tables = page.extract_tables()
                    for j, table in enumerate(tables):
                        table_text = self._format_table(table)
                        if table_text:
                            documents.append(Document(
                                content=table_text,
                                metadata={
                                    "page": i + 1,
                                    "table_index": j,
                                    "source": str(file_path),
                                    "doc_type": "table",
                                },
                                source=str(file_path),
                            ))

        # Add full text document
        if full_text:
            documents.insert(0, Document(
                content="\n\n".join(full_text),
                metadata={
                    "source": str(file_path),
                    "doc_type": "text",
                    "total_pages": len(full_text),
                },
                source=str(file_path),
            ))

        logger.info(f"Loaded {len(documents)} documents from {file_path}")
        return documents

    def _load_with_pypdf2(self, file_path: Path) -> list[Document]:
        """Load PDF using PyPDF2 (fallback)."""
        from PyPDF2 import PdfReader

        reader = PdfReader(str(file_path))
        full_text = []

        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                full_text.append(text)

        if full_text:
            return [Document(
                content="\n\n".join(full_text),
                metadata={
                    "source": str(file_path),
                    "doc_type": "text",
                    "total_pages": len(full_text),
                },
                source=str(file_path),
            )]

        return []

    def _format_table(self, table: list[list[Any]]) -> str:
        """Format a table as text."""
        if not table or not table[0]:
            return ""

        rows = []
        for row in table:
            row_text = " | ".join(str(cell or "") for cell in row)
            rows.append(row_text)

        return "\n".join(rows)


class TextDocumentLoader:
    """Load plain text documents."""

    def load(self, file_path: str | Path, encoding: str = "utf-8") -> list[Document]:
        """Load a text file."""
        file_path = Path(file_path)
        with open(file_path, "r", encoding=encoding) as f:
            content = f.read()

        return [Document(
            content=content,
            metadata={
                "source": str(file_path),
                "doc_type": "text",
            },
            source=str(file_path),
        )]
