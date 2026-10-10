"""Split a wiki page's Markdown into chunks for embedding (S6, given). How big and how much overlap is
decision 015, so both are arguments.

Sections follow the headings, so a chunk never spans two topics; within a section, paragraphs are packed
up to `max_tokens`, and each chunk after the first repeats the last `overlap_tokens` of the one before.
Every chunk starts with the page title and its heading, which is what makes a chunk like "It is $4.50"
findable at all. Token counts are estimates (words x 1.3, about right for English with these models'
tokenizers); the embedding model reads at most 2,048 tokens per chunk.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

TOKENS_PER_WORD = 1.3


@dataclass(frozen=True)
class Chunk:
    index: int
    heading: str
    text: str
    tokens: int

    def content_hash(self, page_id: str) -> str:
        """Stable id: the same text on the same page always gets the same hash, so it's embedded once."""
        return hashlib.sha256(f"{page_id}\n{self.text}".encode()).hexdigest()[:32]


def estimate_tokens(text: str) -> int:
    return round(len(text.split()) * TOKENS_PER_WORD)


def _sections(markdown: str) -> list[tuple[str, str]]:
    """(heading path, body) pairs; text before the first heading has an empty heading."""
    out, path, body = [], [], []  # path: (level, title) of the headings we're under
    for line in markdown.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            if "".join(body).strip():
                out.append((" > ".join(t for _, t in path), "\n".join(body).strip()))
            level = len(m.group(1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, m.group(2)))
            body = []
        else:
            body.append(line)
    if "".join(body).strip():
        out.append((" > ".join(t for _, t in path), "\n".join(body).strip()))
    return out


def _pieces(body: str, max_words: int) -> list[str]:
    """Paragraphs, with any paragraph longer than max_words split into word runs."""
    out = []
    for para in re.split(r"\n\s*\n", body):
        words = para.split()
        for i in range(0, len(words), max_words):
            out.append(" ".join(words[i : i + max_words]))
    return [p for p in out if p]


def chunk_markdown(title: str, markdown: str, max_tokens: int, overlap_tokens: int = 0) -> list[Chunk]:
    if max_tokens < 20 or not 0 <= overlap_tokens < max_tokens:
        raise ValueError("max_tokens must be at least 20 and overlap_tokens between 0 and max_tokens")
    max_words = max(1, int(max_tokens / TOKENS_PER_WORD))
    overlap_words = int(overlap_tokens / TOKENS_PER_WORD)
    chunks: list[Chunk] = []
    for heading, body in _sections(markdown):
        prefix = f"{title} > {heading}" if heading else title
        current: list[str] = []
        # Room for the overlap a chunk starts with, so no chunk goes over max_tokens (plus its prefix line).
        for piece in _pieces(body, max_words - overlap_words):
            if current and len(" ".join(current + [piece]).split()) > max_words:
                chunks.append(_chunk(len(chunks), heading, prefix, current))
                tail = " ".join(current).split()[-overlap_words:] if overlap_words else []
                current = [" ".join(tail)] if tail else []
            current.append(piece)
        if current:
            chunks.append(_chunk(len(chunks), heading, prefix, current))
    return chunks


def _chunk(index: int, heading: str, prefix: str, parts: list[str]) -> Chunk:
    text = f"{prefix}\n\n" + "\n\n".join(parts)
    return Chunk(index, heading, text, estimate_tokens(text))
