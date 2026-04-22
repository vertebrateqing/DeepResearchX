"""Web scraping tool for extracting content from search result URLs.

Supports:
- HTML pages (text extraction via BeautifulSoup)
- PDF files (text extraction via PyPDF2/pdfplumber)
- URL deduplication
- Configurable text chunking with overlap
- Vector similarity filtering against query
- Extensible image extraction interface (placeholder)
"""

import asyncio
import hashlib
import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from financial_agent.config.settings import get_settings
from financial_agent.core.base import BaseTool
from financial_agent.rag.embedding import EmbeddingService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ScrapedPage:
    """A single scraped webpage or document."""

    url: str
    title: str
    content: str  # extracted text
    content_type: str  # "html", "pdf", "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "content_type": self.content_type,
            "metadata": self.metadata,
        }


@dataclass
class TextChunk:
    """A chunk of text with source info."""

    text: str
    source_url: str
    source_title: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageItem:
    """Placeholder for future image extraction."""

    url: str
    alt_text: str = ""
    source_page: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# HTML text extractor
# ---------------------------------------------------------------------------


def extract_text_from_html(html: str, url: str = "") -> tuple[str, str]:
    """Extract main text and title from HTML.

    Returns:
        (title, text)
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Extract title
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Remove non-content tags
        for tag_name in ["script", "style", "nav", "footer", "header", "aside", "noscript"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Try to find main content area
        main_content = None
        for selector in ["main", "article", "[role='main']", ".content", "#content", ".post", ".entry"]:
            elem = soup.select_one(selector)
            if elem:
                main_content = elem
                break

        if main_content is None:
            main_content = soup.body or soup

        # Get text and clean whitespace
        text = main_content.get_text(separator="\n")
        text = _clean_text(text)

        return title, text

    except ImportError:
        logger.warning("BeautifulSoup not available, falling back to regex HTML extraction")
        return _extract_text_from_html_regex(html)


def _extract_text_from_html_regex(html: str) -> tuple[str, str]:
    """Fallback HTML text extraction using regex."""
    # Try to extract title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""

    # Remove script and style tags
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Extract text from body
    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    body = body_match.group(1) if body_match else html

    # Convert tags to newlines
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"</p>", "\n\n", body, flags=re.IGNORECASE)
    body = re.sub(r"</div>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"</li>", "\n", body, flags=re.IGNORECASE)

    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", body)
    text = _clean_text(text)

    return title, text


def _clean_text(text: str) -> str:
    """Clean up whitespace in extracted text."""
    # Normalize newlines
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\r", "\n", text)
    # Collapse multiple newlines to at most 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text)
    # Strip lines
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    return text.strip()


# ---------------------------------------------------------------------------
# PDF text extractor
# ---------------------------------------------------------------------------

# Check library availability once at module load time
_has_pdfplumber = False
_has_pypdf2 = False

try:
    import pdfplumber
    _has_pdfplumber = True
except ImportError:
    pass

try:
    from PyPDF2 import PdfReader
    _has_pypdf2 = True
except ImportError:
    pass

if not _has_pdfplumber and not _has_pypdf2:
    logger.warning(
        "Neither pdfplumber nor PyPDF2 is installed. "
        "PDF scraping will return empty text. "
        "Install with: pip install pdfplumber PyPDF2"
    )


def extract_text_from_pdf(file_path: str | Path) -> str:
    """Extract text from a PDF file."""
    file_path = Path(file_path)

    # Try pdfplumber first (better quality)
    if _has_pdfplumber:
        try:
            import pdfplumber

            texts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    if text.strip():
                        texts.append(text.strip())

            if texts:
                return "\n\n".join(texts)
        except Exception as e:
            logger.debug(f"pdfplumber extraction failed: {e}")
    else:
        logger.debug("pdfplumber not available, skipping")

    # Fallback to PyPDF2
    if _has_pypdf2:
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(str(file_path))
            texts = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    texts.append(text.strip())

            return "\n\n".join(texts) if texts else ""
        except Exception as e:
            logger.warning(f"PyPDF2 extraction failed for {file_path}: {e}")
            return ""
    else:
        logger.debug("PyPDF2 not available, skipping")

    logger.warning(
        f"PDF extraction unavailable for {file_path}. "
        f"Install pdfplumber or PyPDF2 to enable PDF support."
    )
    return ""


# ---------------------------------------------------------------------------
# Text chunker
# ---------------------------------------------------------------------------


def split_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    separators: list[str] | None = None,
) -> list[str]:
    """Split text into overlapping chunks.

    Strategy: try separators in order, split on the first one that
    produces reasonable chunks, then merge small adjacent chunks.
    """
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    separators = separators or ["\n\n", "\n", "。", "；", "，", " ", ""]

    # Find the best separator
    best_chunks: list[str] = []
    for sep in separators:
        if sep == "":
            # Character-level split
            chunks = list(text)
        else:
            chunks = text.split(sep)

        # Rejoin with separator
        if sep != "":
            chunks = [c + sep for c in chunks[:-1]] + [chunks[-1]] if len(chunks) > 1 else chunks

        # Filter empty
        chunks = [c.strip() for c in chunks if c.strip()]

        if chunks:
            best_chunks = chunks
            # Prefer separators that give us chunks close to target size
            avg_len = sum(len(c) for c in chunks) / len(chunks)
            if avg_len <= chunk_size * 1.5:
                break

    if not best_chunks:
        best_chunks = [text]

    # Merge small chunks to stay close to chunk_size
    merged: list[str] = []
    current = ""
    for chunk in best_chunks:
        if len(current) + len(chunk) <= chunk_size:
            current += chunk
        else:
            if current:
                merged.append(current.strip())
            current = chunk
    if current:
        merged.append(current.strip())

    # Apply overlap
    if chunk_overlap > 0 and len(merged) > 1:
        result = []
        for i, chunk in enumerate(merged):
            if i == 0:
                result.append(chunk)
            else:
                overlap_start = max(0, len(chunk) - chunk_overlap)
                prev_overlap = chunk[:overlap_start]
                result.append(prev_overlap)
        # Actually the standard overlap approach is to prepend overlap from previous chunk
        result = []
        for i, chunk in enumerate(merged):
            if i == 0:
                result.append(chunk)
            else:
                prev = merged[i - 1]
                overlap_text = prev[-chunk_overlap:] if len(prev) > chunk_overlap else prev
                result.append(overlap_text + chunk)
        return result

    return merged


# ---------------------------------------------------------------------------
# Vector similarity
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Main scraper tool
# ---------------------------------------------------------------------------


class WebScraperTool(BaseTool):
    """Tool for scraping web content from URLs and filtering by relevance."""

    name = "web_scraper"
    description = "从网页URL抓取正文内容，支持HTML和PDF，按查询相关性过滤。"
    parameters = {
        "urls": {
            "type": "array",
            "description": "需要抓取的URL列表",
            "items": {"type": "string"},
        },
        "query": {
            "type": "string",
            "description": "用于相关性过滤的查询语句",
        },
        "top_k": {
            "type": "integer",
            "description": "返回最相关的top_k个文本片段",
            "default": 10,
        },
        "chunk_size": {
            "type": "integer",
            "description": "文本分块大小（字符数）",
            "default": 512,
        },
        "chunk_overlap": {
            "type": "integer",
            "description": "文本分块重叠大小（字符数）",
            "default": 64,
        },
    }

    def __init__(self) -> None:
        self.settings = get_settings().data_sources.web_scraper
        self._client: Optional[httpx.AsyncClient] = None
        self._embedding: Optional[EmbeddingService] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = getattr(self.settings, "timeout", 30)
            self._client = httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
        return self._client

    @property
    def embedding(self) -> EmbeddingService:
        if self._embedding is None:
            self._embedding = EmbeddingService()
        return self._embedding

    # --- Public API ---

    async def execute(
        self,
        urls: list[str],
        query: str,
        top_k: int = 10,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> dict[str, Any]:
        """Scrape URLs, extract text, chunk, and filter by query relevance."""
        total_t0 = time.perf_counter()
        # Deduplicate URLs
        unique_urls = self._dedup_urls(urls)
        logger.info(f"[WebScraper] Deduplicated {len(urls)} URLs to {len(unique_urls)} unique URLs")

        if not unique_urls:
            return {"chunks": [], "pages": [], "images": [], "total_chunks": 0}

        # Scrape all URLs concurrently
        pages = await self._scrape_urls(unique_urls)
        logger.info(f"[WebScraper] Successfully scraped {len(pages)} pages")

        # Chunk text from all pages
        all_chunks: list[TextChunk] = []
        for page in pages:
            if not page.content:
                continue
            chunks = split_text(
                page.content,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            for i, chunk_text in enumerate(chunks):
                all_chunks.append(TextChunk(
                    text=chunk_text,
                    source_url=page.url,
                    source_title=page.title,
                    chunk_index=i,
                ))

        logger.info(f"[WebScraper] Generated {len(all_chunks)} chunks from {len(pages)} pages")

        # Filter by vector similarity
        if all_chunks and query:
            filtered_chunks = await self._filter_by_similarity(all_chunks, query, top_k)
        else:
            filtered_chunks = all_chunks[:top_k]

        logger.info(f"[WebScraper] Returning {len(filtered_chunks)} top-k chunks for query relevance")
        total_latency = time.perf_counter() - total_t0
        logger.info(f"[WebScraper] Total execute time={total_latency:.2f}s (urls={len(unique_urls)}, chunks={len(all_chunks)}, top_k={len(filtered_chunks)})")

        return {
            "chunks": [
                {
                    "text": c.text,
                    "source_url": c.source_url,
                    "source_title": c.source_title,
                    "chunk_index": c.chunk_index,
                }
                for c in filtered_chunks
            ],
            "pages": [p.to_dict() for p in pages],
            "images": [],  # Placeholder for future image extraction
            "total_chunks": len(all_chunks),
        }

    # --- URL deduplication ---

    def _dedup_urls(self, urls: list[str]) -> list[str]:
        """Deduplicate URLs by normalized form.

        Normalization: remove fragments, strip trailing slashes,
        lowercase scheme and netloc.
        """
        seen: set[str] = set()
        result: list[str] = []

        for url in urls:
            try:
                parsed = urlparse(url)
                # Normalize
                scheme = parsed.scheme.lower()
                netloc = parsed.netloc.lower()
                path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
                # Remove fragment, keep query (may matter for some sites)
                normalized = f"{scheme}://{netloc}{path}"
                if parsed.query:
                    # Sort query params for stable dedup
                    q = "&".join(sorted(parsed.query.split("&")))
                    normalized = f"{normalized}?{q}"

                if normalized not in seen:
                    seen.add(normalized)
                    result.append(url)  # Keep original URL for fetching
            except Exception:
                # Malformed URL, keep as-is
                if url not in seen:
                    seen.add(url)
                    result.append(url)

        return result

    # --- Scraping ---

    async def _scrape_urls(self, urls: list[str]) -> list[ScrapedPage]:
        """Scrape multiple URLs concurrently."""
        t0 = time.perf_counter()
        semaphore = asyncio.Semaphore(getattr(self.settings, "concurrency", 5))

        async def _fetch_one(url: str) -> ScrapedPage | None:
            async with semaphore:
                try:
                    return await self._fetch_page(url)
                except Exception as e:
                    logger.warning(f"[WebScraper] Failed to fetch {url}: {e}")
                    return None

        tasks = [_fetch_one(url) for url in urls]
        results = await asyncio.gather(*tasks)
        pages = [r for r in results if r is not None]
        logger.info(f"[WebScraper] Scraped {len(pages)}/{len(urls)} URLs in {time.perf_counter() - t0:.2f}s")
        return pages

    async def _fetch_page(self, url: str) -> ScrapedPage:
        """Fetch and extract content from a single URL."""
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Detect content type by extension
        if path.endswith(".pdf"):
            return await self._fetch_pdf(url)

        # Default: fetch as HTML
        return await self._fetch_html(url)

    async def _fetch_html(self, url: str) -> ScrapedPage:
        """Fetch HTML page and extract text."""
        logger.debug(f"[WebScraper] Fetching HTML: {url}")
        t0 = time.perf_counter()
        response = await self.client.get(url)
        response.raise_for_status()

        html = response.text
        title, text = extract_text_from_html(html, url)

        # Basic metadata
        metadata = {
            "content_length": len(text),
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type", "unknown"),
        }

        latency = time.perf_counter() - t0
        logger.info(f"[WebScraper] HTML {url}: fetch+extract={latency:.2f}s, text_len={len(text)}")

        return ScrapedPage(
            url=url,
            title=title,
            content=text,
            content_type="html",
            metadata={**metadata, "latency_s": latency},
        )

    async def _fetch_pdf(self, url: str) -> ScrapedPage:
        """Fetch PDF and extract text."""
        logger.debug(f"[WebScraper] Fetching PDF: {url}")
        t0 = time.perf_counter()
        response = await self.client.get(url)
        response.raise_for_status()

        # Save to temp file
        suffix = Path(urlparse(url).path).suffix or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        try:
            text = extract_text_from_pdf(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        metadata = {
            "content_length": len(text),
            "http_status": response.status_code,
            "file_size": len(response.content),
        }

        latency = time.perf_counter() - t0
        logger.info(f"[WebScraper] PDF {url}: fetch+extract={latency:.2f}s, text_len={len(text)}")

        return ScrapedPage(
            url=url,
            title=f"PDF: {url.split('/')[-1]}",
            content=text,
            content_type="pdf",
            metadata={**metadata, "latency_s": latency},
            metadata=metadata,
        )

    # --- Similarity filtering ---

    async def _filter_by_similarity(
        self,
        chunks: list[TextChunk],
        query: str,
        top_k: int,
    ) -> list[TextChunk]:
        """Filter chunks by cosine similarity to query embedding."""
        if not chunks:
            return []

        t0 = time.perf_counter()
        # Embed query
        query_embedding = await self.embedding.embed_query(query)

        # Embed all chunks in batches
        chunk_texts = [c.text for c in chunks]
        batch_size = 32
        all_embeddings: list[list[float]] = []

        for i in range(0, len(chunk_texts), batch_size):
            batch = chunk_texts[i:i + batch_size]
            embeddings = await self.embedding.embed_texts(batch)
            all_embeddings.extend(embeddings)

        # Compute similarities and sort
        scored = []
        for chunk, emb in zip(chunks, all_embeddings):
            score = cosine_similarity(query_embedding, emb)
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        latency = time.perf_counter() - t0
        logger.info(
            f"[WebScraper] Similarity filter: embed+score {len(chunks)} chunks in {latency:.2f}s, "
            f"top_score={scored[0][0]:.3f}, median={scored[len(scored)//2][0]:.3f}"
        )

        return [chunk for _, chunk in scored[:top_k]]

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._embedding:
            await self._embedding.close()
            self._embedding = None

    # --- Image extraction interface (placeholder) ---

    async def extract_images(self, url: str) -> list[ImageItem]:
        """Extract images from a webpage. Placeholder for future extension."""
        # Future: implement image extraction with alt-text, OCR, etc.
        logger.info(f"[WebScraper] Image extraction not yet implemented for {url}")
        return []
