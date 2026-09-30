"""
chunker.py — splits a raw Majles (Iranian Parliament) bill/طرح text into
hierarchical chunks that mirror its legal structure, instead of chunking
by a fixed character/token size.

A typical طرح/لایحه document has three top-level zones:
  1. Header zone   — registration number, session, referred commissions,
                      justification preamble (مقدمه توجیهی), signatories.
  2. Articles zone — the operative text (متن ماده واحده): a sequence of
                      numbered ماده, each optionally followed by its own
                      تبصره sub-notes, which stay attached to their parent
                      ماده rather than becoming separate chunks.
  3. Admin zone    — the internal legislative-office opinions (نظر اداره‌
                      کل تدوین قوانین / اسناد و تنقیح قوانین) that follow
                      the operative text.

Chunking this way (one chunk per ماده, not per N characters) means each
LLM call sees a complete, self-contained legal unit and never has an
article or a تبصره split across two chunks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Marks the start of the operative-text zone: the title line is always
# repeated immediately before the numbered ماده begin.
ARTICLES_ZONE_START = re.compile(r"عنوان\s*طرح\s*:")

# Marks the start of the administrative-opinions zone.
ADMIN_ZONE_START = re.compile(r"هیأت\s*رئیسه|هیات\s*رئیسه")

# A top-level ماده in these numbered drafts, as produced by pdftotext-style
# extraction, shows up as a bare 1-2 digit number at the start of a line,
# immediately followed by the article's text. We deliberately do NOT match
# "تبصره" markers here, since notes must stay nested inside their article.
ARTICLE_MARKER = re.compile(r"(?:^|\n)[ \t]*(\d{1,2})[ \t]+(?=\S)")


@dataclass
class Chunk:
    chunk_id: str
    chunk_type: str  # "header" | "article" | "admin"
    order: int
    text: str
    char_start: int
    char_end: int
    article_number: Optional[str] = None
    metadata: dict = field(default_factory=dict)


def _find_zone_bounds(text: str) -> Tuple[int, int]:
    """Return (articles_zone_start, admin_zone_start) character offsets."""
    m1 = ARTICLES_ZONE_START.search(text)
    if m1:
        nl = text.find("\n", m1.end())
        articles_start = nl + 1 if nl != -1 else m1.end()
    else:
        articles_start = 0

    m2 = ADMIN_ZONE_START.search(text, pos=articles_start)
    admin_start = m2.start() if m2 else len(text)
    return articles_start, admin_start


def chunk_legal_document(text: str, doc_id: str = "doc") -> List[Chunk]:
    """
    Split `text` into hierarchical chunks:
      - one 'header'  chunk  (registration info, preamble, signatories)
      - one 'article' chunk PER top-level ماده (تبصره notes stay inline)
      - one 'admin'   chunk  (legislative-office opinions + everything after)

    Falls back to treating the whole document as a single chunk if the
    expected anchors/markers aren't found, so unfamiliar input degrades
    gracefully instead of raising.
    """
    articles_start, admin_start = _find_zone_bounds(text)
    chunks: List[Chunk] = []
    order = 0

    header_text = text[:articles_start].strip()
    if header_text:
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}-header",
                chunk_type="header",
                order=order,
                text=header_text,
                char_start=0,
                char_end=articles_start,
            )
        )
        order += 1

    articles_text = text[articles_start:admin_start]
    if articles_text.strip():
        markers = list(ARTICLE_MARKER.finditer(articles_text))
        if markers:
            for i, m in enumerate(markers):
                start = m.start()
                end = markers[i + 1].start() if i + 1 < len(markers) else len(articles_text)
                piece = articles_text[start:end].strip()
                if not piece:
                    continue
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc_id}-article-{m.group(1)}",
                        chunk_type="article",
                        order=order,
                        text=piece,
                        char_start=articles_start + start,
                        char_end=articles_start + end,
                        article_number=m.group(1),
                    )
                )
                order += 1
        else:
            # No numbered markers found (e.g. a single-article/ماده واحده
            # bill) — keep the whole operative-text zone as one chunk
            # rather than silently dropping it.
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}-article-all",
                    chunk_type="article",
                    order=order,
                    text=articles_text.strip(),
                    char_start=articles_start,
                    char_end=admin_start,
                )
            )
            order += 1

    admin_text = text[admin_start:].strip()
    if admin_text:
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}-admin",
                chunk_type="admin",
                order=order,
                text=admin_text,
                char_start=admin_start,
                char_end=len(text),
            )
        )
        order += 1

    if not chunks:
        chunks.append(
            Chunk(chunk_id=f"{doc_id}-full", chunk_type="header", order=0, text=text, char_start=0, char_end=len(text))
        )

    return chunks