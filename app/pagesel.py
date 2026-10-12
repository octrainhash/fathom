"""One way to say "which pages" everywhere in Fathom.

Words and numbers, separated by commas:  all  odd  even  first  last  5  5-8  end  end-2  -3 (first three)  7- (from 7 on)  every 3  !4 (not page 4)
Examples:  1,3,5-8,end      odd,!1      all,!2-3      every 5
"""
from __future__ import annotations

import re

from app.service import UserError

_WORDS = {"all", "odd", "even", "first", "last", "end"}


def _num(tok: str, total: int) -> int:
    tok = tok.strip().lower()
    if tok in ("end", "last"):
        return total
    m = re.fullmatch(r"(?:end|last)\s*-\s*(\d+)", tok)
    if m:
        return total - int(m.group(1))
    if tok.isdigit():
        return int(tok)
    raise UserError(f"'{tok}' is not a page number. Use something like 1,3,5-8,end.")


def parse(spec: str | None, total: int, sizes: list[tuple[float, float]] | None = None, orient: str = "any") -> list[int]:
    """0-based page numbers, in order, no repeats. An empty spec means every page."""
    spec = (spec or "").strip().lower()
    chosen: list[int] = []
    removed: set[int] = set()
    if not spec:
        chosen = list(range(total))
    for part in re.split(r"[,;]+", spec) if spec else []:
        part = part.strip()
        if not part:
            continue
        neg = part.startswith("!") or part.startswith("not ")
        if neg:
            part = part.lstrip("!").removeprefix("not ").strip()
        pages: list[int] = []
        if part in ("all", "*"):
            pages = list(range(total))
        elif part == "odd":
            pages = list(range(0, total, 2))
        elif part == "even":
            pages = list(range(1, total, 2))
        elif part == "first":
            pages = [0]
        elif part == "last":
            pages = [total - 1]
        elif (m := re.fullmatch(r"(?:every|each)\s*(\d+)(?:\s*(?:st|nd|rd|th))?", part)):
            k = max(1, int(m.group(1)))
            pages = list(range(k - 1, total, k))
        elif (m := re.fullmatch(r"(.*?)\s*-\s*(.*)", part)) and (m.group(1) or m.group(2)) and not re.fullmatch(r"(?:end|last)\s*-\s*\d+", part):
            a = 1 if not m.group(1) else _num(m.group(1), total)
            b = total if not m.group(2) else _num(m.group(2), total)
            if m.group(1) == "" and m.group(2):
                a = 1
            pages = list(range(a - 1, b)) if a <= b else list(range(a - 1, b - 2, -1))
        else:
            pages = [_num(part, total) - 1]
        pages = [p for p in pages if 0 <= p < total]
        if neg:
            removed.update(pages)
        else:
            chosen += pages
    if spec and not chosen and removed:       # only "!x" given: everything except those
        chosen = list(range(total))
    seen: set[int] = set()
    out = [p for p in chosen if p not in removed and not (p in seen or seen.add(p))]
    if sizes and orient in ("portrait", "landscape"):
        out = [p for p in out if p < len(sizes) and ((sizes[p][1] >= sizes[p][0]) == (orient == "portrait"))]
    return out


def need(spec: str | None, total: int, sizes=None, orient: str = "any") -> list[int]:
    """like parse() but says so when nothing is left"""
    out = parse(spec, total, sizes, orient)
    if not out:
        raise UserError(f"None of the pages you chose exist in this file (it has {total} page{'s' if total != 1 else ''}"
                        + (f", and none of them are {orient}" if orient in ("portrait", "landscape") else "") + ").")
    return out


def compact(pages: list[int]) -> str:
    """[0,1,2,5,7,8] -> '1-3,6,8-9'"""
    out, i = [], 0
    ps = sorted(set(pages))
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[j] + 1:
            j += 1
        out.append(str(ps[i] + 1) if i == j else f"{ps[i] + 1}-{ps[j] + 1}")
        i = j + 1
    return ",".join(out)
