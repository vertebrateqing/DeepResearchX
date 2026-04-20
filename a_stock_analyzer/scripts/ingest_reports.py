"""Script to ingest financial reports into RAG system."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from a_stock_analyzer.rag.document_loader import PDFDocumentLoader
from a_stock_analyzer.rag.pipeline import RAGPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def ingest_pdf(file_path: str, company: str = "", symbol: str = "") -> None:
    """Ingest a single PDF file."""
    pipeline = RAGPipeline()

    metadata = {}
    if company:
        metadata["company"] = company
    if symbol:
        metadata["symbol"] = symbol

    logger.info(f"Ingesting {file_path}...")
    doc_ids = await pipeline.ingest_pdf(file_path, extra_metadata=metadata)
    logger.info(f"Ingested {len(doc_ids)} chunks from {file_path}")


async def ingest_directory(directory: str, pattern: str = "*.pdf") -> None:
    """Ingest all PDFs in a directory."""
    dir_path = Path(directory)
    pdf_files = list(dir_path.glob(pattern))

    logger.info(f"Found {len(pdf_files)} PDF files in {directory}")

    for pdf_file in pdf_files:
        # Try to extract company info from filename
        # Expected format: COMPANY_SYMBOL_YYYY_report.pdf
        parts = pdf_file.stem.split("_")
        company = parts[0] if len(parts) > 0 else ""
        symbol = parts[1] if len(parts) > 1 else ""

        await ingest_pdf(str(pdf_file), company, symbol)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest financial reports into RAG")
    parser.add_argument("--file", help="Single PDF file to ingest")
    parser.add_argument("--dir", help="Directory of PDFs to ingest")
    parser.add_argument("--company", help="Company name")
    parser.add_argument("--symbol", help="Stock symbol")
    parser.add_argument("--pattern", default="*.pdf", help="File pattern")

    args = parser.parse_args()

    if args.file:
        asyncio.run(ingest_pdf(args.file, args.company, args.symbol))
    elif args.dir:
        asyncio.run(ingest_directory(args.dir, args.pattern))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
