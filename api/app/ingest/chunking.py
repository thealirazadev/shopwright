import hashlib
import re
from html.parser import HTMLParser

from app.connectors.shopify.client import ProductDoc

# About 400 tokens of English per chunk.
MAX_CHARS = 1600

_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "table",
}
_SKIP_TAGS = {"script", "style"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skipping += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skipping:
            self._skipping -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in "".join(extractor.parts).split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def split_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Pack paragraphs into chunks of at most max_chars, splitting long paragraphs on spaces."""
    chunks: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        while len(paragraph) > max_chars:
            cut = paragraph.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if current and len(current) + 2 + len(paragraph) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def product_text(doc: ProductDoc) -> str:
    """Searchable text for a product. Stock is left out: it changes often and is read live."""
    if doc.price_min is None:
        price = ""
    elif doc.price_min == doc.price_max:
        price = f"Price: {doc.price_min}"
    else:
        price = f"Price: {doc.price_min} to {doc.price_max}"
    parts = [doc.title, price, html_to_text(doc.description_html)]
    return "\n\n".join(part for part in parts if part)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
