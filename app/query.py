from __future__ import annotations

import re
import unicodedata

MAX_SPANS_PER_TEXT = 2000


def compile_query(query: str, case_sensitive: bool = False, use_regex: bool = False, whole_word: bool = False) -> re.Pattern:
    flags = re.MULTILINE | (0 if case_sensitive else re.IGNORECASE)
    if use_regex:
        body = query
    else:
        parts = query.split()
        # "hello world" also matches "hello    world" and a line wrap between the words.
        body = r"\s+".join(re.escape(p) for p in parts) if parts else re.escape(query)
    if whole_word:
        body = rf"(?<!\w)(?:{body})(?!\w)"
    try:
        return re.compile(body, flags)
    except re.error as exc:
        raise ValueError(f"That regex isn't valid: {exc}") from exc


def find_spans(pattern: re.Pattern, text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in pattern.finditer(text):
        s, e = m.span()
        if e > s:
            spans.append((s, e))
            if len(spans) >= MAX_SPANS_PER_TEXT:
                break
    return spans


_VERY_NARROW = set("il|!.,:;'`")
_NARROW = set("jtfrI1()[]{}/\\-")
_WIDE = set("mwMW@%&")


def _weight(ch: str) -> float:
    if ch == " ":
        return 0.55
    if ch in _VERY_NARROW:
        return 0.45
    if ch in _NARROW:
        return 0.62
    if ch in _WIDE:
        return 1.5
    if ch.isupper():
        return 1.15
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2.0
    return 1.0


def span_to_box(text: str, s: int, e: int, bbox, vertical: bool = False):
    """Estimate where text[s:e] sits inside a recognised line box (OCR gives line boxes, not letters)."""
    x0, y0, x1, y1 = [float(v) for v in bbox]
    weights = [_weight(c) for c in text]
    total = sum(weights) or 1.0
    a = sum(weights[:s]) / total
    b = sum(weights[:e]) / total
    if vertical:
        pad = 2 + 0.01 * (y1 - y0)
        return (x0, max(y0, y0 + (y1 - y0) * a - pad), x1, min(y1, y0 + (y1 - y0) * b + pad))
    pad = 2 + 0.012 * (x1 - x0)
    return (max(x0, x0 + (x1 - x0) * a - pad), y0, min(x1, x0 + (x1 - x0) * b + pad), y1)


def make_snippet(text: str, s: int, e: int, before: int = 48, after: int = 72) -> list[str]:
    """[text before, the match, text after] so the UI can highlight the match."""
    pre = re.sub(r"\s+", " ", text[max(0, s - before):s]).lstrip()
    post = re.sub(r"\s+", " ", text[e:e + after]).rstrip()
    return [("…" if s - before > 0 else "") + pre, text[s:e], post + ("…" if e + after < len(text) else "")]
