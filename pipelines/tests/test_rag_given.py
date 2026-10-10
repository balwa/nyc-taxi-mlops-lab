"""The S6 givens without the network: chunking, and the wiki client's ETags, 429s and 401s."""

import io
import json
import urllib.error

import pytest

from labpipes import wiki as wiki_mod
from labpipes.chunking import chunk_markdown, estimate_tokens

PAGE = """Intro line about the Harbor Line.

## Pricing

The Harbor Line surcharge is $4.50 for trips ending at Pier 76. It shows on receipts as HL-76.

Drivers see it on the trip summary.

## Hours

""" + " ".join(f"word{i}" for i in range(400)) + """

### Weekends

Weekend service starts at 09:00.
"""


def test_chunks_follow_headings_and_carry_title_and_heading():
    chunks = chunk_markdown("Harbor Line", PAGE, max_tokens=120, overlap_tokens=20)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].text.startswith("Harbor Line\n\nIntro line")
    pricing = [c for c in chunks if c.heading == "Pricing"]
    assert len(pricing) == 1 and "$4.50" in pricing[0].text and pricing[0].text.startswith("Harbor Line > Pricing")
    assert any(c.heading == "Hours > Weekends" and "09:00" in c.text for c in chunks)
    assert all(c.tokens <= 120 + 30 for c in chunks)  # the prefix line can push a little over


def test_long_sections_split_with_overlap_and_hashes_are_stable():
    chunks = [c for c in chunk_markdown("Harbor Line", PAGE, max_tokens=120, overlap_tokens=20) if c.heading == "Hours"]
    assert len(chunks) >= 4
    overlap_words = int(20 / 1.3)
    assert chunks[1].text.split("\n\n", 1)[1].split()[:overlap_words] == chunks[0].text.split()[-overlap_words:]  # repeats the tail
    again = chunk_markdown("Harbor Line", PAGE, max_tokens=120, overlap_tokens=20)
    assert [c.content_hash("harbor-line") for c in again if c.heading == "Hours"] == [c.content_hash("harbor-line") for c in chunks]
    assert chunks[0].content_hash("harbor-line") != chunks[0].content_hash("other-page")


def test_bad_sizes_are_refused():
    with pytest.raises(ValueError):
        chunk_markdown("t", PAGE, max_tokens=10)
    with pytest.raises(ValueError):
        chunk_markdown("t", PAGE, max_tokens=100, overlap_tokens=100)
    assert estimate_tokens("one two three") == 4


class FakeWiki:
    """urlopen stand-in: a scripted sequence of (status, body, headers) per path."""

    def __init__(self, script):
        self.script, self.seen = script, []

    def __call__(self, req, timeout=None):
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        self.seen.append(("/" + path, dict(req.header_items())))
        status, body, headers = self.script["/" + path].pop(0)
        if status >= 300:
            raise urllib.error.HTTPError(req.full_url, status, "x", headers, io.BytesIO(json.dumps(body).encode()))
        return _Resp(status, body, headers)


class _Resp(io.BytesIO):
    def __init__(self, status, body, headers):
        super().__init__(json.dumps(body).encode())
        self.status, self.headers = status, headers


def test_conditional_get_rate_limit_and_rotation(monkeypatch):
    sleeps = []
    monkeypatch.setattr(wiki_mod.time, "sleep", sleeps.append)
    fake = FakeWiki({
        "/pages": [(429, {}, {"Retry-After": "2"}), (200, [{"id": "a", "title": "A", "updated_at": "t", "etag": '"e1"'}], {})],
        "/pages/a": [(304, {}, {"ETag": '"e1"'}), (200, {"id": "a", "title": "A", "updated_at": "t2", "etag": '"e2"', "body": "x"}, {}),
                     (401, {}, {})],
    })
    monkeypatch.setattr(wiki_mod.urllib.request, "urlopen", fake)
    w = wiki_mod.Wiki("https://wiki.example", "tok")
    refs = w.pages()
    assert [r.id for r in refs] == ["a"] and sleeps == [2.0]
    assert w.page("a", '"e1"') is None
    assert w.page("a", '"e1"').etag == '"e2"'
    with pytest.raises(wiki_mod.WikiError, match="rotated"):
        w.page("a")
    assert fake.seen[2][1].get("If-none-match") == '"e1"' and fake.seen[0][1]["Authorization"] == "Bearer tok"


def test_psi_and_windows():
    from labpipes.defs.drift import months_between, psi

    same = {0: 500, 1: 300, 2: 200}
    assert psi(same, same) == 0
    shifted = {0: 200, 1: 300, 2: 500}
    assert 0.2 < psi(same, shifted) < 1.0  # a real shift by the rule of thumb
    assert psi(same, {0: 510, 1: 295, 2: 195}) < 0.01
    assert months_between("2024-11..2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]
