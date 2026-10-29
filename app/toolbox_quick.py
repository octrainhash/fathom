# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Quick helpers that work on text, with no file needed: JSON, Base64, web addresses, unique ids, passwords, dates, hashes and HMAC,
Markdown, reading level, text clean-up, number bases, colours, lorem ipsum. Everything runs on this computer."""
from __future__ import annotations

import base64
import binascii
import colorsys
import hashlib
import hmac
import html
import json
import math
import random
import re
import secrets
import string
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, quote_plus, unquote, unquote_plus, urlsplit

from app.service import UserError


def _int(v, d: int, lo: int, hi: int) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        n = d
    return max(lo, min(hi, n))


def _res(result: str, info: list | None = None, note: str = "", ok: bool = True) -> dict:
    return {"result": result, "info": info or [], "note": note, "ok": ok}


# ---------------------------------------------------------------- JSON
def _relax_json(text: str) -> str:
    """Removes // and /* */ comments and trailing commas, and turns 'single quoted' strings into "double quoted" ones (outside strings)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            q = c
            j = i + 1
            buf = []
            while j < n and text[j] != q:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            body = "".join(buf)
            if q == "'":
                body = body.replace('\\"', '"').replace('"', '\\"').replace("\\'", "'")
            out.append('"' + body + '"')
            i = j + 1
        elif c == "/" and text[i:i + 2] == "//":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and text[i:i + 2] == "/*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    s = "".join(out)
    prev = None
    while prev != s:                       # trailing commas before } or ]
        prev = s
        s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s


def _sort_obj(o):
    if isinstance(o, dict):
        return {k: _sort_obj(o[k]) for k in sorted(o)}
    if isinstance(o, list):
        return [_sort_obj(x) for x in o]
    return o


def _json_stats(o) -> list:
    counts = Counter()
    depth = [0]

    def walk(x, d):
        depth[0] = max(depth[0], d)
        counts[type(x).__name__] += 1
        if isinstance(x, dict):
            for v in x.values():
                walk(v, d + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, d + 1)
    walk(o, 1)
    names = {"dict": "objects", "list": "lists", "str": "text values", "int": "whole numbers", "float": "decimal numbers", "bool": "true/false", "NoneType": "null"}
    return [["Deepest level", depth[0]]] + [[names.get(k, k), v] for k, v in counts.most_common()]


def t_json(text: str, o: dict) -> dict:
    mode = o.get("mode", "pretty")
    if not text.strip():
        raise UserError("Paste some JSON first.")
    src = _relax_json(text) if o.get("lenient") else text
    try:
        data = json.loads(src)
    except json.JSONDecodeError as e:
        lines = text.splitlines()
        line = lines[e.lineno - 1] if 0 < e.lineno <= len(lines) else ""
        caret = " " * max(0, e.colno - 1) + "^"
        return _res("", [["Problem", e.msg], ["Line", e.lineno], ["Column", e.colno]], f"This is not valid JSON.\n\n{line}\n{caret}\n\nTip: tick 'Forgive small mistakes' to allow comments, trailing commas and 'single quotes'.", ok=False)
    if o.get("sort"):
        data = _sort_obj(data)
    ind = o.get("indent", "2")
    ascii_only = bool(o.get("ascii"))
    if mode == "minify":
        out = json.dumps(data, ensure_ascii=ascii_only, separators=(",", ":"))
    elif mode == "validate":
        out = text
    else:
        indent = "\t" if ind == "tab" else _int(ind, 2, 1, 8)
        out = json.dumps(data, ensure_ascii=ascii_only, indent=indent)
    return _res(out, _json_stats(data), "Valid JSON." if mode == "validate" else "")


# ---------------------------------------------------------------- Base64
def t_base64(text: str, o: dict) -> dict:
    enc = o.get("charset", "utf-8")
    urlsafe = bool(o.get("urlsafe"))
    if o.get("mode", "encode") == "encode":
        data = text.encode(enc, "replace")
        out = (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(data).decode("ascii")
        if o.get("nopad"):
            out = out.rstrip("=")
        wrap = _int(o.get("wrap"), 0, 0, 1000)
        if wrap:
            out = "\n".join(out[i:i + wrap] for i in range(0, len(out), wrap))
        return _res(out, [["Input bytes", len(data)], ["Output characters", len(out.replace("\n", ""))]])
    raw = re.sub(r"\s+", "", text)
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    raw = raw.replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as e:
        return _res("", [], f"This is not valid Base64 ({e}).", ok=False)
    try:
        out = data.decode(enc)
        note = ""
    except UnicodeDecodeError:
        out = data.decode(enc, "replace")
        note = "The bytes are not all valid text in this character set, so some characters were replaced. It may be a picture or other binary data."
    return _res(out, [["Decoded bytes", len(data)]], note)


# ---------------------------------------------------------------- web addresses
def t_url(text: str, o: dict) -> dict:
    mode = o.get("mode", "encode")
    if mode == "parse":
        u = urlsplit(text.strip())
        info = [["Scheme", u.scheme], ["Host", u.hostname or ""], ["Port", u.port or ""], ["User", u.username or ""], ["Path", unquote(u.path)], ["Query", u.query], ["Fragment", u.fragment]]
        info += [[f"Parameter: {k}", v] for k, v in parse_qsl(u.query, keep_blank_values=True)]
        return _res(json.dumps({"scheme": u.scheme, "host": u.hostname, "port": u.port, "path": u.path, "params": parse_qsl(u.query, keep_blank_values=True), "fragment": u.fragment}, indent=2), info)
    if mode == "decode":
        return _res(unquote_plus(text) if o.get("plus") else unquote(text))
    scope = o.get("scope", "component")
    if scope == "full":
        out = quote(text, safe=":/?#[]@!$&'()*+,;=%")
    elif scope == "form":
        out = quote_plus(text)
    else:
        out = quote(text, safe="")
    return _res(out)


# ---------------------------------------------------------------- unique ids
def _uuid7() -> uuid.UUID:
    ms = int(time.time() * 1000)
    rand = secrets.randbits(74)
    v = (ms & ((1 << 48) - 1)) << 80 | (0x7 << 76) | ((rand >> 62) << 64) | (0x2 << 62) | (rand & ((1 << 62) - 1))
    return uuid.UUID(int=v)


NS = {"dns": uuid.NAMESPACE_DNS, "url": uuid.NAMESPACE_URL, "oid": uuid.NAMESPACE_OID, "x500": uuid.NAMESPACE_X500}


def t_uuid(text: str, o: dict) -> dict:
    ver = o.get("version", "4")
    n = _int(o.get("count"), 5, 1, 1000)
    out = []
    for _ in range(n):
        if ver == "7":
            u = _uuid7()
        elif ver == "1":
            u = uuid.uuid1()
        elif ver in ("3", "5"):
            name = text.strip() or o.get("name", "")
            if not name:
                raise UserError("Type a name in the box to make a version 3 or 5 id.")
            ns = NS.get(o.get("ns", "dns"), uuid.NAMESPACE_DNS)
            u = uuid.uuid3(ns, name) if ver == "3" else uuid.uuid5(ns, name)
        elif ver == "nil":
            u = uuid.UUID(int=0)
        else:
            u = uuid.uuid4()
        s = str(u)
        if o.get("nohyphen"):
            s = s.replace("-", "")
        if o.get("upper"):
            s = s.upper()
        if o.get("braces"):
            s = "{" + s + "}"
        out.append(s)
        if ver in ("3", "5", "nil"):
            break
    return _res("\n".join(out), [["How many", len(out)]])


# ---------------------------------------------------------------- passwords
WORDS = """able acid also arch area army atom aunt auto away baby back bake ball band bank barn base bath bean bear beat bell belt bike bird blow blue boat body bold bolt bone book boot born boss bowl brick bring brook brush buck bulb bull bump burn bush busy cafe cake calm camp cane card care cart case cash cast cave cell chain chair chalk chef chess chip city clay clip clock cloud club coal coat code coin cold comb cone cook cool copy cord corn cost couch crab craft crane crew crisp crop crow cube cup curl dance dark dash dawn deal deep deer desk dice dish dive dock dog door dove down draw dream drift drum duck dune dust eagle earth east easy echo edge egg elk elm ember end engine epic evening fair fall farm fast fawn feast fern field film find fire fish flag flame flash flax float flock floor flow foam fog fold food ford forest fork form fort fox frame frog frost fruit fuel gain game gate gear gem gift glad glass globe glow goat gold golf grain grape grass gray green grid grove gull gust hall hand harp hawk hay heart hedge hill hive home honey hood hook hope horn horse hose hour house hut ice idea inch iron isle ivory jade jam jar jazz jet joy jump kale keen kelp kettle key kind king kite knee knot lake lamp land lane lark lava leaf lens lily lime line lion list lock loft log loop lord lotus luck lunar lynx magic maid mail main maple mare mark mask mast meal mesh mild mill mind mine mint mist moat mole moon moss moth mount mouse mud nest net night noble north note nut oak oar oasis ocean olive onion opal orbit otter oven owl pace page paint palm pan park path pawn peach pear pearl pebble pen pier pine pipe plain plan plum pocket pole pond pony pool port post pride pulse pump quail quartz queen quick quiet quill rabbit race rail rain ranch raven reed reef ridge ring river road robin rock roof root rope rose rush sage sail salt sand sea seed shade shell shore silk silver sky slate sleep snow soap song soup south spark spice spoon spring star steam stone storm stream sugar summer sun swan swift table tail tale tea thorn tide tiger tile toad tower trail tree trout tulip turtle twig vale vase vine violet wagon wall wave west wheat wheel willow wind wing winter wolf wood wool yard yarn zebra zinc""".split()
AMBIG = set("Il1O0o|`'\".,;:")


def _strength(bits: float) -> str:
    return "very weak" if bits < 28 else "weak" if bits < 40 else "fair" if bits < 60 else "strong" if bits < 80 else "very strong" if bits < 120 else "excellent"


def t_password(text: str, o: dict) -> dict:
    n = _int(o.get("count"), 5, 1, 200)
    mode = o.get("mode", "chars")
    rng = secrets.SystemRandom()
    out, bits = [], 0.0
    if mode == "words":
        k = _int(o.get("words"), 5, 2, 20)
        sep = o.get("sep", "-")
        for _ in range(n):
            ws = [rng.choice(WORDS) for _ in range(k)]
            if o.get("capital"):
                ws = [w.capitalize() for w in ws]
            s = sep.join(ws)
            if o.get("digit"):
                s += sep + str(rng.randrange(10, 100))
            out.append(s)
        bits = k * math.log2(len(WORDS)) + (math.log2(90) if o.get("digit") else 0)
    elif mode == "pin":
        k = _int(o.get("length"), 6, 3, 40)
        out = ["".join(rng.choice(string.digits) for _ in range(k)) for _ in range(n)]
        bits = k * math.log2(10)
    else:
        k = _int(o.get("length"), 20, 4, 256)
        sets = []
        if o.get("lower", True):
            sets.append(string.ascii_lowercase)
        if o.get("upper", True):
            sets.append(string.ascii_uppercase)
        if o.get("digits", True):
            sets.append(string.digits)
        if o.get("symbols", True):
            sets.append(o.get("symbol_set") or "!@#$%^&*()-_=+[]{};:,.?/")
        if o.get("custom"):
            sets.append(o["custom"])
        if o.get("noambig"):
            sets = ["".join(c for c in s if c not in AMBIG) for s in sets]
        sets = [s for s in sets if s]
        if not sets:
            raise UserError("Pick at least one kind of character.")
        pool = "".join(sorted(set("".join(sets))))
        if k < len(sets) and o.get("each", True):
            raise UserError("The password is too short to hold one of every kind. Make it longer or untick 'Use every kind'.")
        for _ in range(n):
            while True:
                pw = [rng.choice(pool) for _ in range(k)]
                if not o.get("each", True) or all(any(c in s for c in pw) for s in sets):
                    break
            out.append("".join(pw))
        bits = k * math.log2(len(pool))
    return _res("\n".join(out), [["Strength", f"{_strength(bits)} (about {bits:.0f} bits)"], ["Made with", "the computer's secure random generator"]], "Passwords are made here and never sent anywhere.")


# ---------------------------------------------------------------- dates and times
def _parse_when(text: str, tz) -> datetime:
    t = text.strip()
    if not t or t.lower() == "now":
        return datetime.now(timezone.utc)
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        v = float(t)
        a = abs(v)
        if a >= 1e17:
            v /= 1e9
        elif a >= 1e14:
            v /= 1e6
        elif a >= 1e11:
            v /= 1e3
        return datetime.fromtimestamp(v, timezone.utc)
    s = t.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = None
        for fmt in ("%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y %H:%M:%S", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%a, %d %b %Y %H:%M:%S %z", "%a %b %d %H:%M:%S %Y"):
            try:
                d = datetime.strptime(t, fmt)
                break
            except ValueError:
                pass
        if d is None:
            raise UserError("Fathom could not read this date. Try 2026-10-29 14:30, an epoch number such as 1793222873, or the word now.")
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz)
    return d.astimezone(timezone.utc)


def _ago(secs: float) -> str:
    fut = secs < 0
    s = abs(int(secs))
    for unit, size in (("year", 31557600), ("month", 2629800), ("week", 604800), ("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        if s >= size:
            n = s // size
            return f"in {n} {unit}{'s' if n != 1 else ''}" if fut else f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "right now"


def t_time(text: str, o: dict) -> dict:
    from zoneinfo import ZoneInfo, available_timezones
    try:
        tz_in = ZoneInfo(o.get("tz_in") or "UTC")
    except Exception:
        tz_in = timezone.utc
    d = _parse_when(text, tz_in)
    delta = _int(o.get("add"), 0, -10**9, 10**9)
    unit = o.get("unit", "days")
    if delta:
        d += timedelta(**{unit: delta})
    zones = [z for z in (o.get("zones") or "UTC,local").split(",") if z.strip()]
    info = []
    ts = d.timestamp()
    info += [["Epoch seconds", int(ts)], ["Epoch milliseconds", int(ts * 1000)], ["ISO 8601 (UTC)", d.strftime("%Y-%m-%dT%H:%M:%SZ")],
             ["RFC 2822", d.strftime("%a, %d %b %Y %H:%M:%S +0000")], ["Day of the week", d.strftime("%A")], ["Week of the year", d.isocalendar()[1]],
             ["Day of the year", d.timetuple().tm_yday], ["Julian day", round(ts / 86400 + 2440587.5, 5)], ["Relative", _ago(time.time() - ts)]]
    for z in zones:
        z = z.strip()
        try:
            loc = d.astimezone() if z.lower() == "local" else d.astimezone(ZoneInfo(z))
        except Exception:
            info.append([z, "unknown time zone"])
            continue
        info.append([f"{'This computer' if z.lower() == 'local' else z}", loc.strftime("%Y-%m-%d %H:%M:%S %Z (UTC%z)")])
    return _res(d.strftime("%Y-%m-%d %H:%M:%S UTC"), info, f"{len(available_timezones())} time zone names are known, such as Asia/Karachi or America/New_York.")


# ---------------------------------------------------------------- hashes and HMAC
ALGOS = ["md5", "sha1", "sha224", "sha256", "sha384", "sha512", "sha3_224", "sha3_256", "sha3_384", "sha3_512", "blake2b", "blake2s"]


def t_hash(text: str, o: dict) -> dict:
    enc = o.get("charset", "utf-8")
    data = text.encode(enc, "replace")
    key = (o.get("key") or "").encode(enc, "replace")
    algos = [a for a in (o.get("algos") or ["sha256"]) if a in ALGOS] or ["sha256"]
    form = o.get("form", "hex")
    expect = re.sub(r"\s+", "", o.get("expect", "")).lower()
    rows, hit = [], None
    for a in algos:
        d = hmac.new(key, data, a).digest() if key else hashlib.new(a, data).digest()
        s = base64.b64encode(d).decode() if form == "base64" else d.hex()
        if form == "upper":
            s = s.upper()
        rows.append([a.upper().replace("_", "-") + (" (HMAC)" if key else ""), s])
        if expect and expect in (s.lower(), d.hex()):
            hit = a
    note = ""
    if expect:
        note = f"MATCHES the {hit.upper()} you entered." if hit else "Does NOT match the value you entered."
    return _res(rows[0][1] if len(rows) == 1 else "", rows, note, ok=not expect or bool(hit))


# ---------------------------------------------------------------- Markdown to a web page
def _inline(s: str, raw_html: bool) -> str:
    codes: list[str] = []

    def stash(m):
        codes.append("<code>" + html.escape(m.group(1)) + "</code>")
        return f"\x00{len(codes) - 1}\x00"
    s = re.sub(r"`([^`\n]+)`", stash, s)
    if not raw_html:
        s = html.escape(s, quote=False)
    s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;([^)]*)&quot;|\s+\"([^\"]*)\")?\)", lambda m: f'<img src="{html.escape(m.group(2), quote=True)}" alt="{html.escape(m.group(1), quote=True)}">', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\)", lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>' if not m.group(2).lower().startswith(("javascript:", "data:", "vbscript:")) else m.group(1), s)
    s = re.sub(r"(?<![\"'>=(])\bhttps?://[^\s<)]+", lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', s)
    s = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", s)
    s = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", lambda m: f"<em>{m.group(1) or m.group(2)}</em>", s)
    s = re.sub(r"~~(.+?)~~", r"<del>\1</del>", s)
    s = re.sub(r"  \n", "<br>\n", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def _slug(t: str) -> str:
    return re.sub(r"[^\w\- ]", "", t.lower()).strip().replace(" ", "-")


def markdown_to_html(src: str, raw_html: bool = False, toc: bool = False, page: bool = False, title: str = "Document", anchors: bool = True) -> tuple[str, dict]:
    lines = src.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    heads: list[tuple[int, str, str]] = []
    i, n = 0, len(lines)
    para: list[str] = []

    def flush():
        if para:
            out.append("<p>" + _inline("\n".join(para), raw_html) + "</p>")
            para.clear()

    def split_row(row: str) -> list[str]:
        row = row.strip().strip("|")
        return [c.strip() for c in re.split(r"(?<!\\)\|", row)]

    while i < n:
        ln = lines[i]
        if re.match(r"^\s*(```|~~~)", ln):
            flush()
            fence = re.match(r"^\s*(```|~~~)\s*([\w+-]*)", ln)
            lang = fence.group(2)
            i += 1
            buf = []
            while i < n and not lines[i].lstrip().startswith(fence.group(1)):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(f'<pre><code{f" class=language-{lang}" if lang else ""}>' + html.escape("\n".join(buf)) + "</code></pre>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", ln)
        if m:
            flush()
            lvl, txt = len(m.group(1)), m.group(2)
            sid = _slug(re.sub(r"[`*_]", "", txt))
            heads.append((lvl, re.sub(r"[`*_]", "", txt), sid))
            out.append(f'<h{lvl} id="{sid}">{_inline(txt, raw_html)}</h{lvl}>')
            i += 1
            continue
        if i + 1 < n and ln.strip() and re.match(r"^=+\s*$", lines[i + 1]):
            flush(); heads.append((1, ln.strip(), _slug(ln))); out.append(f'<h1 id="{_slug(ln)}">{_inline(ln.strip(), raw_html)}</h1>'); i += 2; continue
        if i + 1 < n and ln.strip() and re.match(r"^-{2,}\s*$", lines[i + 1]) and not re.match(r"^\s*[-*+]\s", ln):
            flush(); heads.append((2, ln.strip(), _slug(ln))); out.append(f'<h2 id="{_slug(ln)}">{_inline(ln.strip(), raw_html)}</h2>'); i += 2; continue
        if re.match(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$", ln):
            flush(); out.append("<hr>"); i += 1; continue
        if ln.startswith(">"):
            flush()
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>\n" + markdown_to_html("\n".join(buf), raw_html)[0] + "\n</blockquote>")
            continue
        if "|" in ln and i + 1 < n and re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", lines[i + 1]):
            flush()
            head = split_row(ln)
            aligns = []
            for c in split_row(lines[i + 1]):
                aligns.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "left" if c.startswith(":") else "")
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1

            def cell(tag, txt, k):
                a = f' style="text-align:{aligns[k]}"' if k < len(aligns) and aligns[k] else ""
                return f"<{tag}{a}>{_inline(txt, raw_html)}</{tag}>"
            t = ["<table>", "<thead><tr>" + "".join(cell("th", c, k) for k, c in enumerate(head)) + "</tr></thead>", "<tbody>"]
            for r in rows:
                t.append("<tr>" + "".join(cell("td", c, k) for k, c in enumerate(r)) + "</tr>")
            t += ["</tbody>", "</table>"]
            out.append("\n".join(t))
            continue
        lm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", ln)
        if lm:
            flush()
            ordered = lm.group(2)[0].isdigit()
            base_indent = len(lm.group(1))
            items: list[list[str]] = []
            while i < n:
                m2 = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", lines[i])
                if m2 and len(m2.group(1)) <= base_indent + 1:
                    items.append([m2.group(3)])
                    i += 1
                elif m2 and len(m2.group(1)) > base_indent + 1 and items:
                    items[-1].append(lines[i][base_indent + 2:] if lines[i].startswith(" " * (base_indent + 2)) else lines[i].strip())
                    i += 1
                elif lines[i].startswith("  ") and lines[i].strip() and items:
                    items[-1].append(lines[i].strip())
                    i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            li = []
            for it in items:
                head_line = it[0]
                task = re.match(r"^\[( |x|X)\]\s+(.*)$", head_line)
                box = ""
                if task:
                    box = '<input type="checkbox" disabled' + (" checked" if task.group(1) != " " else "") + "> "
                    head_line = task.group(2)
                sub = it[1:]
                body = _inline(head_line, raw_html)
                if sub:
                    body += "\n" + markdown_to_html("\n".join(sub), raw_html)[0]
                li.append(f"<li>{box}{body}</li>")
            out.append(f"<{tag}>\n" + "\n".join(li) + f"\n</{tag}>")
            continue
        if not ln.strip():
            flush(); i += 1; continue
        para.append(ln)
        i += 1
    flush()
    body = "\n".join(out)
    stats = {"headings": len(heads), "words": len(re.findall(r"\w+", src)), "links": len(re.findall(r"<a ", body)), "images": len(re.findall(r"<img ", body)), "tables": body.count("<table>"), "code blocks": body.count("<pre>")}
    if toc and heads:
        t = ["<nav class=toc>", "<ul>"]
        for lvl, txt, sid in heads:
            t.append(f'<li style="margin-left:{(lvl - 1) * 1.2:.1f}em"><a href="#{sid}">{html.escape(txt)}</a></li>')
        t += ["</ul>", "</nav>"]
        body = "\n".join(t) + "\n" + body
    if page:
        css = "body{font:16px/1.6 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1c1f2a}pre{background:#f3f4f8;padding:12px;border-radius:8px;overflow:auto}code{background:#f3f4f8;padding:1px 5px;border-radius:4px}table{border-collapse:collapse}td,th{border:1px solid #ccd;padding:4px 10px}blockquote{border-left:4px solid #ccd;margin:0;padding-left:1rem;color:#555}img{max-width:100%}"
        body = f"<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n<title>{html.escape(title)}</title>\n<style>{css}</style>\n</head>\n<body>\n{body}\n</body>\n</html>"
    return body, stats


def t_markdown(text: str, o: dict) -> dict:
    body, stats = markdown_to_html(text, bool(o.get("raw")), bool(o.get("toc")), bool(o.get("page")), o.get("title") or "Document")
    return _res(body, [[k.capitalize(), v] for k, v in stats.items()])


# ---------------------------------------------------------------- reading level
def _syll(w: str) -> int:
    w = re.sub(r"[^a-z]", "", w.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def t_readability(text: str, o: dict) -> dict:
    words = re.findall(r"[A-Za-z0-9’'-]+", text)
    if len(words) < 3:
        raise UserError("Paste a few sentences first.")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip()) if re.search(r"\w", s)]
    ns = max(1, len(sentences))
    nw = len(words)
    sy = sum(_syll(w) for w in words)
    chars = sum(len(re.sub(r"\W", "", w)) for w in words)
    complex_w = sum(1 for w in words if _syll(w) >= 3)
    fre = 206.835 - 1.015 * (nw / ns) - 84.6 * (sy / nw)
    fk = 0.39 * (nw / ns) + 11.8 * (sy / nw) - 15.59
    fog = 0.4 * ((nw / ns) + 100 * (complex_w / nw))
    smog = 1.043 * math.sqrt(complex_w * (30 / ns)) + 3.1291
    cli = 0.0588 * (chars / nw * 100) - 0.296 * (ns / nw * 100) - 15.8
    ari = 4.71 * (chars / nw) + 0.5 * (nw / ns) - 21.43
    level = "very easy (5th grade)" if fre >= 90 else "easy (6th grade)" if fre >= 80 else "fairly easy (7th grade)" if fre >= 70 else "plain English (8th-9th grade)" if fre >= 60 else "fairly difficult (10th-12th grade)" if fre >= 50 else "difficult (college)" if fre >= 30 else "very difficult (graduate)"
    stop = set("the a an and or but of to in on at for with as by is are was were be been it its this that from not no".split())
    top = Counter(w.lower() for w in words if len(w) > 3 and w.lower() not in stop).most_common(8)
    longest = max(sentences, key=lambda s: len(s.split()))
    info = [["Flesch Reading Ease", f"{fre:.1f}  ({level})"], ["Flesch-Kincaid grade", f"{fk:.1f}"], ["Gunning Fog", f"{fog:.1f}"], ["SMOG", f"{smog:.1f}"], ["Coleman-Liau", f"{cli:.1f}"], ["Automated Readability", f"{ari:.1f}"],
            ["Words", nw], ["Sentences", ns], ["Syllables", sy], ["Characters (letters and digits)", chars], ["Average words per sentence", f"{nw / ns:.1f}"], ["Long words (3+ syllables)", f"{complex_w} ({100 * complex_w / nw:.0f}%)"],
            ["Reading time", f"{nw / 220:.1f} min (220 words per minute)"], ["Speaking time", f"{nw / 130:.1f} min (130 words per minute)"], ["Longest sentence", f"{len(longest.split())} words"],
            ["Most used words", ", ".join(f"{w} ({c})" for w, c in top)]]
    return _res(f"Reading level: {level}", info)


# ---------------------------------------------------------------- text clean-up
def _words(s: str) -> list[str]:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    return [w for w in re.split(r"[^A-Za-z0-9]+", s) if w]


def t_text(text: str, o: dict) -> dict:
    op = o.get("op", "case")
    if op == "case":
        c = o.get("case", "upper")
        ws = _words(text)
        res = {"upper": text.upper(), "lower": text.lower(), "title": text.title(), "sentence": re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text.lower()),
               "swap": text.swapcase(), "camel": (ws[0].lower() + "".join(w.capitalize() for w in ws[1:])) if ws else "", "pascal": "".join(w.capitalize() for w in ws),
               "snake": "_".join(w.lower() for w in ws), "kebab": "-".join(w.lower() for w in ws), "constant": "_".join(w.upper() for w in ws), "dot": ".".join(w.lower() for w in ws)}
        return _res(res.get(c, text))
    lines = text.splitlines()
    if op == "sort":
        key = (lambda s: s.lower()) if o.get("ignorecase") else None
        if o.get("numeric"):
            def key(s):  # noqa: F811
                m = re.search(r"-?\d+(\.\d+)?", s)
                return (float(m.group()) if m else float("inf"), s)
        lines = sorted(lines, key=key, reverse=bool(o.get("reverse")))
        if o.get("unique"):
            seen, u = set(), []
            for s in lines:
                k = s.lower() if o.get("ignorecase") else s
                if k not in seen:
                    seen.add(k); u.append(s)
            lines = u
        return _res("\n".join(lines), [["Lines", len(lines)]])
    if op == "dedupe":
        seen, u = set(), []
        for s in lines:
            k = s.strip().lower() if o.get("ignorecase") else s.strip() if o.get("trim") else s
            if k not in seen:
                seen.add(k); u.append(s)
        return _res("\n".join(u), [["Lines before", len(lines)], ["Lines after", len(u)], ["Removed", len(lines) - len(u)]])
    if op == "clean":
        s = text
        if o.get("trim", True):
            s = "\n".join(l.rstrip() for l in s.split("\n"))
        if o.get("spaces", True):
            s = re.sub(r"[ \t]{2,}", " ", s)
        if o.get("blank", True):
            s = re.sub(r"\n{3,}", "\n\n", s)
        if o.get("quotes"):
            s = s.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-", 0x2026: "..."})
        if o.get("nonascii"):
            import unicodedata
            s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        if o.get("tabs"):
            s = s.replace("\t", "    ")
        return _res(s.strip("\n") + ("\n" if text.endswith("\n") else ""))
    if op == "number":
        start = _int(o.get("start"), 1, -10**6, 10**6)
        return _res("\n".join(f"{start + k}{o.get('sep', '. ')}{l}" for k, l in enumerate(lines)))
    if op == "reverse":
        mode = o.get("rmode", "lines")
        return _res("\n".join(reversed(lines)) if mode == "lines" else "\n".join(l[::-1] for l in lines) if mode == "chars" else "\n".join(" ".join(reversed(l.split())) for l in lines))
    if op == "count":
        w = re.findall(r"\w+", text)
        return _res("", [["Characters", len(text)], ["Characters without spaces", len(re.sub(r"\s", "", text))], ["Words", len(w)], ["Lines", len(lines)], ["Unique words", len({x.lower() for x in w})],
                         ["Paragraphs", len([p for p in re.split(r"\n\s*\n", text) if p.strip()])], ["Bytes (UTF-8)", len(text.encode("utf-8"))]])
    if op == "replace":
        find = o.get("find", "")
        if not find:
            raise UserError("Type what to find.")
        flags = 0 if o.get("case") else re.I
        try:
            pat = re.compile(find if o.get("regex") else re.escape(find), flags)
        except re.error as e:
            raise UserError(f"That pattern is not valid: {e}")
        res, k = pat.subn(o.get("repl", "").replace("\\n", "\n") if o.get("regex") else (lambda _m: o.get("repl", "")), text)
        return _res(res, [["Replacements", k]])
    if op == "slug":
        import unicodedata
        s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        return _res("\n".join(re.sub(r"[^a-z0-9]+", "-", l).strip("-") for l in s.splitlines()))
    if op == "extract":
        kind = o.get("kind", "email")
        pats = {"email": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "url": r"https?://[^\s<>\"')]+", "number": r"-?\d+(?:[.,]\d+)?", "hashtag": r"#\w+", "ip": r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "date": r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b"}
        found = re.findall(pats.get(kind, pats["email"]), text)
        if o.get("unique", True):
            found = list(dict.fromkeys(found))
        return _res("\n".join(found), [["Found", len(found)]])
    raise UserError("Unknown text tool.")


# ---------------------------------------------------------------- number bases and colours
def t_base(text: str, o: dict) -> dict:
    t = text.strip().replace("_", "").replace(" ", "").lower()
    if not t:
        raise UserError("Type a number.")
    src = o.get("from", "auto")
    try:
        if src == "auto":
            v = int(t, 0) if t.startswith(("0x", "0b", "0o")) or t.lstrip("-").isdigit() else int(t, 16)
        else:
            v = int(re.sub(r"^0[xbo]", "", t), {"bin": 2, "oct": 8, "dec": 10, "hex": 16}[src])
    except ValueError:
        raise UserError("That is not a number in the chosen base.")
    sign = "-" if v < 0 else ""
    a = abs(v)
    info = [["Decimal", str(v)], ["Hexadecimal", f"{sign}0x{a:X}"], ["Binary", f"{sign}0b{a:b}"], ["Octal", f"{sign}0o{a:o}"], ["Bits needed", a.bit_length() or 1],
            ["Bytes (big-endian)", " ".join(f"{b:02X}" for b in a.to_bytes(max(1, (a.bit_length() + 7) // 8), "big"))]]
    if 0 < a < 0x110000:
        info.append(["As a character", chr(a)])
    return _res(str(v), info)


def _norm_hex(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def t_color(text: str, o: dict) -> dict:
    t = text.strip().lower()
    try:
        if t.startswith("rgb"):
            r, g, b = [int(float(x)) for x in re.findall(r"[\d.]+", t)[:3]]
        elif t.startswith("hsl"):
            hh, ss, ll = [float(x) for x in re.findall(r"[\d.]+", t)[:3]]
            r, g, b = [round(x * 255) for x in colorsys.hls_to_rgb(hh / 360, ll / 100, ss / 100)]
        else:
            r, g, b = _norm_hex(t)
    except (ValueError, IndexError):
        raise UserError("Type a colour like #1b3a8c, rgb(27, 58, 140) or hsl(220, 68%, 32%).")
    r, g, b = [max(0, min(255, x)) for x in (r, g, b)]
    hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    hv, sv, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    cw, cb = 1.05 / (lum + 0.05), (lum + 0.05) / 0.05
    k = 1 - max(r, g, b) / 255
    cmyk = [0, 0, 0, 100] if k == 1 else [round(100 * (1 - x / 255 - k) / (1 - k)) for x in (r, g, b)] + [round(100 * k)]
    info = [["Hex", f"#{r:02x}{g:02x}{b:02x}"], ["RGB", f"rgb({r}, {g}, {b})"], ["HSL", f"hsl({hh * 360:.0f}, {ss * 100:.0f}%, {ll * 100:.0f}%)"], ["HSV", f"hsv({hv * 360:.0f}, {sv * 100:.0f}%, {vv * 100:.0f}%)"],
            ["CMYK", f"cmyk({cmyk[0]}%, {cmyk[1]}%, {cmyk[2]}%, {cmyk[3]}%)"], ["Contrast with white", f"{cw:.2f}:1  {'(passes AA for normal text)' if cw >= 4.5 else '(too low for small text)'}"],
            ["Contrast with black", f"{cb:.2f}:1  {'(passes AA for normal text)' if cb >= 4.5 else '(too low for small text)'}"], ["Best text colour", "black" if cb > cw else "white"]]
    return _res(f"#{r:02x}{g:02x}{b:02x}", info)


# ---------------------------------------------------------------- lorem ipsum
LOREM = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua enim ad minim veniam quis nostrud exercitation ullamco laboris nisi "
         "aliquip ex ea commodo consequat duis aute irure in reprehenderit voluptate velit esse cillum eu fugiat nulla pariatur excepteur sint occaecat cupidatat non proident sunt culpa qui officia "
         "deserunt mollit anim id est laborum curabitur pretium tincidunt lacus nunc mattis enim ut tellus elementum sagittis vitae et leo duis ut diam quam nulla porttitor massa id neque aliquam "
         "vestibulum morbi blandit cursus risus at ultrices mi tempus imperdiet nulla malesuada pellentesque elit eget gravida cum sociis natoque penatibus magnis dis parturient montes").split()


def t_lorem(text: str, o: dict) -> dict:
    n = _int(o.get("count"), 3, 1, 200)
    unit = o.get("unit", "paragraphs")
    rnd = random.Random(o.get("seed") or None)

    def sentence(first=False):
        k = rnd.randint(7, 16)
        ws = [rnd.choice(LOREM) for _ in range(k)]
        if first:
            ws[:2] = ["lorem", "ipsum"]
        s = " ".join(ws)
        if k > 9 and rnd.random() < 0.6:
            at = rnd.randint(3, k - 3)
            parts = s.split(" ")
            parts[at] += ","
            s = " ".join(parts)
        return s[0].upper() + s[1:] + "."
    start = o.get("start", True)
    if unit == "words":
        ws = [rnd.choice(LOREM) for _ in range(n)]
        if start and n >= 2:
            ws[:2] = ["lorem", "ipsum"]
        out = " ".join(ws)
    elif unit == "sentences":
        out = " ".join(sentence(start and i == 0) for i in range(n))
    else:
        paras = [" ".join(sentence(start and i == 0 and j == 0) for j in range(rnd.randint(3, 6))) for i in range(n)]
        out = "\n\n".join(f"<p>{p}</p>" for p in paras) if o.get("html") else "\n\n".join(paras)
    return _res(out, [["Words", len(out.split())]])


TOOLS = {"json": t_json, "base64": t_base64, "url": t_url, "uuid": t_uuid, "password": t_password, "time": t_time, "hash": t_hash, "markdown": t_markdown,
         "readability": t_readability, "text": t_text, "base": t_base, "color": t_color, "lorem": t_lorem}


def run(tool: str, text: str, options: dict) -> dict:
    fn = TOOLS.get(tool)
    if not fn:
        from app.toolbox_quick2 import TOOLS2
        fn = TOOLS2.get(tool)
    if not fn:
        raise UserError("Unknown helper.")
    if len(text) > 8_000_000:
        raise UserError("That is too much text for this helper (limit 8 million characters).")
    return fn(text or "", options or {})
