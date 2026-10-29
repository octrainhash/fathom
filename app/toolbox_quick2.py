# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""More quick helpers (all offline): data converter, JWT decoder, regex tester, text compare, unit converter, encoders, validators,
network calculator, cron explainer, numbers in words, calculator."""
from __future__ import annotations

import base64
import csv
import difflib
import html
import io
import ipaddress
import json
import math
import re
import unicodedata
from datetime import date, datetime

from app.service import UserError
from app.toolbox_quick import _int, _res


# ---------------------------------------------------------------- data converter
def _to_py(text: str, fmt: str, delim: str = ","):
    t = text.strip()
    if fmt == "json":
        return json.loads(t)
    if fmt == "yaml":
        import yaml
        return yaml.safe_load(t)
    if fmt == "toml":
        import tomllib
        return tomllib.loads(t)
    if fmt in ("csv", "tsv"):
        d = "\t" if fmt == "tsv" else (delim if delim != "auto" else csv.Sniffer().sniff(t[:4000]).delimiter)
        return list(csv.DictReader(io.StringIO(t), delimiter=d))
    if fmt == "xml":
        if re.search(r"<!(DOCTYPE|ENTITY)", t, re.I):
            raise UserError("XML with DOCTYPE or ENTITY is not accepted, for safety.")
        import xml.etree.ElementTree as ET

        def conv(e):
            kids = list(e)
            d = {("@" + k): v for k, v in e.attrib.items()}
            if not kids:
                tx = (e.text or "").strip()
                return tx if not d else {**d, "#text": tx}
            for k in kids:
                v = conv(k)
                if k.tag in d:
                    d[k.tag] = d[k.tag] if isinstance(d[k.tag], list) else [d[k.tag]]
                    d[k.tag].append(v)
                else:
                    d[k.tag] = v
            return d
        root = ET.fromstring(t)
        return {root.tag: conv(root)}
    if fmt == "ini":
        import configparser
        cp = configparser.ConfigParser()
        cp.read_string(t)
        return {s: dict(cp[s]) for s in cp.sections()}
    if fmt == "lines":
        return [l for l in t.splitlines() if l.strip()]
    raise UserError("Unknown input type.")


def _toml_dump(d: dict, prefix: str = "") -> str:
    def val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, list):
            return "[" + ", ".join(val(x) for x in v) + "]"
        return json.dumps("" if v is None else str(v), ensure_ascii=False)
    out, tables = [], []
    for k, v in d.items():
        key = k if re.fullmatch(r"[A-Za-z0-9_-]+", str(k)) else json.dumps(str(k))
        if isinstance(v, dict):
            tables.append((key, v))
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for item in v:
                tables.append(("[" + (prefix + key), item))
        else:
            out.append(f"{key} = {val(v)}")
    s = "\n".join(out)
    for key, v in tables:
        name = (prefix + key) if not key.startswith("[") else key[1:]
        head = f"[[{name}]]" if key.startswith("[") else f"[{name}]"
        s += ("\n\n" if s else "") + head + "\n" + _toml_dump(v, name + ".")
    return s


def _xml_dump(o, tag="root", ind=0) -> str:
    from xml.sax.saxutils import escape, quoteattr
    pad = "  " * ind
    if isinstance(o, dict):
        attrs = "".join(f" {k[1:]}={quoteattr(str(v))}" for k, v in o.items() if k.startswith("@"))
        kids = {k: v for k, v in o.items() if not k.startswith("@") and k != "#text"}
        if not kids:
            return f"{pad}<{tag}{attrs}>{escape(str(o.get('#text', '')))}</{tag}>"
        inner = "\n".join(_xml_dump(v, k, ind + 1) for k, v in kids.items())
        return f"{pad}<{tag}{attrs}>\n{inner}\n{pad}</{tag}>"
    if isinstance(o, list):
        return "\n".join(_xml_dump(x, tag, ind) for x in o)
    return f"{pad}<{tag}>{escape('' if o is None else str(o))}</{tag}>"


def _rows(o):
    if isinstance(o, dict) and len(o) == 1 and isinstance(next(iter(o.values())), list):
        o = next(iter(o.values()))
    if isinstance(o, dict):
        o = [o]
    if not isinstance(o, list):
        raise UserError("A table needs a list of records.")
    rows = [x if isinstance(x, dict) else {"value": x} for x in o]
    def flat(d, p=""):
        r = {}
        for k, v in d.items():
            if isinstance(v, dict):
                r.update(flat(v, f"{p}{k}."))
            else:
                r[p + str(k)] = json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v
        return r
    rows = [flat(r) for r in rows]
    cols = list(dict.fromkeys(c for r in rows for c in r))
    return cols, rows


def t_convertdata(text: str, o: dict) -> dict:
    src, dst = o.get("src", "json"), o.get("dst", "yaml")
    if not text.strip():
        raise UserError("Paste some data first.")
    try:
        data = _to_py(text, src, o.get("delim", ","))
    except UserError:
        raise
    except Exception as e:
        return _res("", [], f"Could not read this as {src.upper()}: {e}", ok=False)
    ind = _int(o.get("indent"), 2, 1, 8)
    if o.get("sort") and isinstance(data, (dict, list)):
        from app.toolbox_quick import _sort_obj
        data = _sort_obj(data)
    try:
        if dst == "json":
            out = json.dumps(data, ensure_ascii=False, indent=ind)
        elif dst == "jsonl":
            out = "\n".join(json.dumps(x, ensure_ascii=False) for x in (data if isinstance(data, list) else [data]))
        elif dst == "yaml":
            import yaml
            out = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, indent=ind)
        elif dst == "toml":
            out = _toml_dump(data if isinstance(data, dict) else {"items": data})
        elif dst == "xml":
            if isinstance(data, dict) and len(data) == 1 and isinstance(next(iter(data.values())), dict):
                out = '<?xml version="1.0" encoding="UTF-8"?>\n' + _xml_dump(next(iter(data.values())), next(iter(data)))
            else:
                out = '<?xml version="1.0" encoding="UTF-8"?>\n' + _xml_dump(data if isinstance(data, dict) else {"item": data}, "root")
        elif dst in ("csv", "tsv"):
            cols, rows = _rows(data)
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=cols, delimiter="\t" if dst == "tsv" else o.get("delim_out", ","), lineterminator="\n")
            w.writeheader(); w.writerows(rows)
            out = buf.getvalue()
        elif dst == "markdown":
            cols, rows = _rows(data)
            out = "| " + " | ".join(cols) + " |\n|" + "|".join("---" for _ in cols) + "|\n" + "\n".join("| " + " | ".join(str(r.get(c, "")).replace("|", "\\|") for c in cols) + " |" for r in rows)
        elif dst == "html":
            cols, rows = _rows(data)
            out = "<table>\n<thead><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cols) + "</tr></thead>\n<tbody>\n" + "\n".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>" for r in rows) + "\n</tbody>\n</table>"
        elif dst == "sql":
            cols, rows = _rows(data)
            tbl = re.sub(r"\W", "_", o.get("table") or "data")
            q = lambda v: "NULL" if v is None or v == "" else (str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else "'" + str(v).replace("'", "''") + "'")
            out = "\n".join(f"INSERT INTO {tbl} ({', '.join(cols)}) VALUES ({', '.join(q(r.get(c)) for c in cols)});" for r in rows)
        else:
            raise UserError("Unknown output type.")
    except UserError:
        raise
    except Exception as e:
        return _res("", [], f"Could not write {dst.upper()}: {e}", ok=False)
    n = len(data) if isinstance(data, (list, dict)) else 1
    return _res(out, [["Items at the top level", n]])


# ---------------------------------------------------------------- JWT
def t_jwt(text: str, o: dict) -> dict:
    parts = text.strip().replace("Bearer ", "").split(".")
    if len(parts) < 2:
        raise UserError("A token looks like three pieces separated by dots.")
    def dec(p):
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    try:
        head, body = dec(parts[0]), dec(parts[1])
    except Exception:
        return _res("", [], "This does not look like a JWT token.", ok=False)
    info = [["Algorithm", head.get("alg")], ["Type", head.get("typ")]]
    now = datetime.now().timestamp()
    for k, name in (("iat", "Issued"), ("nbf", "Not valid before"), ("exp", "Expires")):
        if isinstance(body.get(k), (int, float)):
            info.append([name, datetime.fromtimestamp(body[k]).strftime("%Y-%m-%d %H:%M:%S") + ("  (EXPIRED)" if k == "exp" and body[k] < now else "")])
    for k in ("iss", "sub", "aud", "jti"):
        if k in body:
            info.append([k, body[k]])
    note = "The signature was not checked (that needs the secret key). Never trust a token just because it decodes."
    if o.get("secret") and head.get("alg") in ("HS256", "HS384", "HS512") and len(parts) == 3:
        import hashlib, hmac
        h = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}[head["alg"]]
        sig = base64.urlsafe_b64encode(hmac.new(o["secret"].encode(), (parts[0] + "." + parts[1]).encode(), h).digest()).decode().rstrip("=")
        note = "Signature is VALID for this secret." if hmac.compare_digest(sig, parts[2]) else "Signature does NOT match this secret."
    return _res(json.dumps({"header": head, "payload": body}, indent=2, ensure_ascii=False), info, note)


# ---------------------------------------------------------------- regex tester
def t_regex(text: str, o: dict) -> dict:
    pat = o.get("pattern", "")
    if not pat:
        raise UserError("Type a pattern.")
    fl = (re.I if o.get("i") else 0) | (re.M if o.get("m") else 0) | (re.S if o.get("s") else 0) | (re.X if o.get("x") else 0)
    try:
        rx = re.compile(pat, fl)
    except re.error as e:
        return _res("", [], f"The pattern is not valid: {e}", ok=False)
    if o.get("repl_on"):
        res, n = rx.subn(o.get("repl", ""), text[:2_000_000])
        return _res(res, [["Replacements", n]])
    info, lines = [], []
    for k, m in enumerate(rx.finditer(text[:2_000_000])):
        if k >= 500:
            info.append(["", "(only the first 500 matches are shown)"]); break
        lines.append(f"{k + 1}. [{m.start()}-{m.end()}] {m.group(0)!r}" + ("".join(f"\n     group {i}: {g!r}" for i, g in enumerate(m.groups(), 1)) if m.groups() else "") + ("".join(f"\n     {n}: {v!r}" for n, v in m.groupdict().items())))
    return _res("\n".join(lines), [["Matches", len(lines)]] + info, "" if lines else "No match.")


# ---------------------------------------------------------------- text compare
def t_diff(text: str, o: dict) -> dict:
    a, b = text, o.get("other", "")
    if not b:
        raise UserError("Paste the second text in 'Compare with'.")
    if o.get("ignore_space"):
        a, b = re.sub(r"[ \t]+", " ", a), re.sub(r"[ \t]+", " ", b)
    if o.get("ignore_case"):
        a, b = a.lower(), b.lower()
    al, bl = a.splitlines(), b.splitlines()
    if o.get("mode") == "words":
        aw, bw = a.split(), b.split()
        sm = difflib.SequenceMatcher(None, aw, bw, autojunk=False)
        out = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                out.append(" ".join(aw[i1:i2]))
            else:
                if i2 > i1: out.append("[-" + " ".join(aw[i1:i2]) + "-]")
                if j2 > j1: out.append("{+" + " ".join(bw[j1:j2]) + "+}")
        return _res(" ".join(out), [["Similarity", f"{sm.ratio() * 100:.1f}%"], ["Words only in the first", sum(i2 - i1 for t, i1, i2, _, _ in sm.get_opcodes() if t != "equal")], ["Words only in the second", sum(j2 - j1 for t, _, _, j1, j2 in sm.get_opcodes() if t != "equal")]], "[-removed-]  {+added+}")
    out = list(difflib.unified_diff(al, bl, "first", "second", lineterm="", n=_int(o.get("context"), 3, 0, 20)))
    ratio = difflib.SequenceMatcher(None, al, bl, autojunk=False).ratio()
    return _res("\n".join(out) if out else "The two texts are the same.", [["Similarity (lines)", f"{ratio * 100:.1f}%"], ["Lines added", sum(1 for l in out if l.startswith("+") and not l.startswith("+++"))], ["Lines removed", sum(1 for l in out if l.startswith("-") and not l.startswith("---"))]])


# ---------------------------------------------------------------- units
UNITS = {
    "length": {"m": 1, "km": 1000, "cm": .01, "mm": .001, "um": 1e-6, "nm": 1e-9, "mile": 1609.344, "yard": .9144, "foot": .3048, "inch": .0254, "nautical mile": 1852, "light year": 9.4607304725808e15},
    "mass": {"kg": 1, "g": .001, "mg": 1e-6, "tonne": 1000, "lb": .45359237, "oz": .028349523125, "stone": 6.35029318, "carat": 2e-4, "tola": .01166},
    "volume": {"L": 1, "mL": .001, "m3": 1000, "US gallon": 3.785411784, "UK gallon": 4.54609, "US quart": .946352946, "US pint": .473176473, "US cup": .2365882365, "fl oz (US)": .0295735295625, "tbsp (US)": .01478676478, "tsp (US)": .00492892159},
    "area": {"m2": 1, "km2": 1e6, "cm2": 1e-4, "ha": 1e4, "acre": 4046.8564224, "sq mile": 2589988.110336, "sq foot": .09290304, "sq inch": 6.4516e-4, "marla": 25.2929538, "kanal": 505.857},
    "speed": {"m/s": 1, "km/h": 1 / 3.6, "mph": .44704, "knot": .514444, "ft/s": .3048, "Mach": 340.29},
    "time": {"s": 1, "ms": .001, "min": 60, "hour": 3600, "day": 86400, "week": 604800, "year (365 d)": 31536000, "month (30 d)": 2592000},
    "data": {"bit": .125, "byte": 1, "KB": 1000, "MB": 1e6, "GB": 1e9, "TB": 1e12, "PB": 1e15, "KiB": 1024, "MiB": 1048576, "GiB": 1073741824, "TiB": 1099511627776},
    "pressure": {"Pa": 1, "kPa": 1000, "bar": 1e5, "atm": 101325, "psi": 6894.757, "mmHg": 133.322, "inHg": 3386.389},
    "energy": {"J": 1, "kJ": 1000, "cal": 4.184, "kcal": 4184, "Wh": 3600, "kWh": 3.6e6, "BTU": 1055.056, "eV": 1.602176634e-19},
    "power": {"W": 1, "kW": 1000, "MW": 1e6, "hp": 745.7, "BTU/h": .29307107},
    "angle": {"degree": 1, "radian": 180 / math.pi, "gradian": .9, "turn": 360, "arcminute": 1 / 60, "arcsecond": 1 / 3600},
}


def unit_lists() -> dict:
    return {**{k: list(v) for k, v in UNITS.items()}, "temperature": ["C", "F", "K"]}


def t_units(text: str, o: dict) -> dict:
    kind = o.get("kind", "length")
    try:
        v = float(re.sub(r"[,\s]", "", text.strip() or str(o.get("value", ""))))
    except ValueError:
        raise UserError("Type a number.")
    a, b = o.get("from"), o.get("to")
    if kind == "temperature":
        c = {"C": v, "F": (v - 32) * 5 / 9, "K": v - 273.15}.get(a)
        if c is None:
            raise UserError("Choose C, F or K.")
        res = {"C": c, "F": c * 9 / 5 + 32, "K": c + 273.15}
        shown = {k: f"{x:.6g}" for k, x in res.items()}
        return _res(f"{res[b]:.10g}", [[f"{k}", shown[k]] for k in res])
    table = UNITS.get(kind)
    if not table or a not in table:
        raise UserError("Choose the units.")
    base = v * table[a]
    info = [[u, f"{base / f:.10g}"] for u, f in table.items()]
    return _res(f"{base / table[b]:.12g}" if b in table else "", info)


# ---------------------------------------------------------------- encoders
MORSE = {"A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
         "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
         ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--", "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...", ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-", '"': ".-..-.", "@": ".--.-."}


def t_encode(text: str, o: dict) -> dict:
    mode, d = o.get("mode", "hex"), o.get("dir", "encode") == "encode"
    enc = o.get("charset", "utf-8")
    try:
        if mode == "hex":
            if d: return _res(" ".join(f"{b:02x}" for b in text.encode(enc)))
            return _res(bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", text)).decode(enc, "replace"))
        if mode == "binary":
            if d: return _res(" ".join(f"{b:08b}" for b in text.encode(enc)))
            return _res(bytes(int(x, 2) for x in re.findall(r"[01]{8}", text)).decode(enc, "replace"))
        if mode == "octal":
            if d: return _res(" ".join(f"{b:03o}" for b in text.encode(enc)))
            return _res(bytes(int(x, 8) for x in text.split()).decode(enc, "replace"))
        if mode == "decimal":
            if d: return _res(" ".join(str(b) for b in text.encode(enc)))
            return _res(bytes(int(x) for x in text.split()).decode(enc, "replace"))
        if mode == "base32":
            return _res(base64.b32encode(text.encode(enc)).decode() if d else base64.b32decode(re.sub(r"\s", "", text).upper() + "=" * (-len(re.sub(r"\s", "", text)) % 8)).decode(enc, "replace"))
        if mode == "base58":
            A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
            if d:
                bts = text.encode(enc); n = int.from_bytes(bts, "big"); s = ""
                while n: n, r = divmod(n, 58); s = A[r] + s
                return _res("1" * (len(bts) - len(bts.lstrip(b"\0"))) + s)
            n = 0
            for ch in text.strip(): n = n * 58 + A.index(ch)
            raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
            return _res((b"\0" * (len(text.strip()) - len(text.strip().lstrip("1"))) + raw).decode(enc, "replace"))
        if mode == "ascii85":
            return _res(base64.a85encode(text.encode(enc)).decode() if d else base64.a85decode(text.strip()).decode(enc, "replace"))
        if mode == "morse":
            if d:
                return _res(" / ".join(" ".join(MORSE.get(c, "?") for c in w) for w in text.upper().split(" ")))
            inv = {v: k for k, v in MORSE.items()}
            return _res(" ".join("".join(inv.get(c, "?") for c in w.split()) for w in text.strip().split("/")))
        if mode == "rot13":
            return _res(text.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm")))
        if mode == "caesar":
            k = _int(o.get("shift"), 3, -25, 25) * (1 if d else -1)
            f = lambda c, base: chr((ord(c) - base + k) % 26 + base)
            return _res("".join(f(c, 65) if "A" <= c <= "Z" else f(c, 97) if "a" <= c <= "z" else c for c in text))
        if mode == "atbash":
            return _res("".join(chr(155 - ord(c)) if "A" <= c <= "Z" else chr(219 - ord(c)) if "a" <= c <= "z" else c for c in text))
        if mode == "html":
            return _res(html.escape(text, quote=True) if d else html.unescape(text))
        if mode == "unicode":
            if d: return _res("".join(c if ord(c) < 128 else (f"\\u{ord(c):04x}" if ord(c) < 0x10000 else f"\\U{ord(c):08x}") for c in text))
            return _res(re.sub(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})", lambda m: chr(int(m.group(1) or m.group(2), 16)), text))
        if mode == "punycode":
            if d: return _res(".".join(("xn--" + p.encode("punycode").decode()) if not p.isascii() else p for p in text.strip().split(".")))
            return _res(".".join(p[4:].encode().decode("punycode") if p.startswith("xn--") else p for p in text.strip().split(".")))
        if mode == "reverse":
            return _res(text[::-1])
        if mode == "upsidedown":
            return _res(text[::-1].translate(str.maketrans("abcdefghijklmnopqrstuvwxyz", "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz")))
        if mode == "nato":
            N = "Alfa Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett Kilo Lima Mike November Oscar Papa Quebec Romeo Sierra Tango Uniform Victor Whiskey Xray Yankee Zulu".split()
            return _res(" ".join(N[ord(c) - 65] if "A" <= c <= "Z" else ("/" if c == " " else c) for c in text.upper()))
    except Exception as e:
        return _res("", [], f"That could not be converted: {e}", ok=False)
    raise UserError("Unknown encoding.")


# ---------------------------------------------------------------- validators
def _luhn(num: str) -> bool:
    d = [int(c) for c in num[::-1]]
    return (sum(d[0::2]) + sum(sum(divmod(x * 2, 10)) for x in d[1::2])) % 10 == 0


def t_validate(text: str, o: dict) -> dict:
    kind = o.get("kind", "iban")
    t = text.strip()
    if kind == "iban":
        s = re.sub(r"\s", "", t).upper()
        ok = bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s)) and int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1
        return _res("valid" if ok else "not valid", [["Country", s[:2]], ["Check digits", s[2:4]], ["Length", len(s)], ["Spaced", " ".join(s[i:i + 4] for i in range(0, len(s), 4))]], "" if ok else "The check digits do not add up.", ok)
    if kind == "card":
        s = re.sub(r"[\s-]", "", t)
        if not s.isdigit():
            raise UserError("Digits only.")
        brand = "Visa" if s[0] == "4" else "Mastercard" if re.match(r"5[1-5]|2[2-7]", s) else "American Express" if re.match(r"3[47]", s) else "Discover" if s.startswith(("6011", "65")) else "UnionPay" if s.startswith("62") else "Other"
        ok = _luhn(s) and 12 <= len(s) <= 19
        return _res("passes the checksum" if ok else "fails the checksum", [["Looks like", brand], ["Digits", len(s)]], "This only checks the number's built-in checksum, not that a real account exists.", ok)
    if kind == "isbn":
        s = re.sub(r"[\s-]", "", t).upper()
        if len(s) == 10:
            ok = bool(re.fullmatch(r"\d{9}[\dX]", s)) and sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s)) % 11 == 0
        else:
            ok = bool(re.fullmatch(r"\d{13}", s)) and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s)) % 10 == 0
        return _res("valid" if ok else "not valid", [["Digits", len(s)]], "", ok)
    if kind == "email":
        ok = bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+", t))
        return _res("looks valid" if ok else "not valid", [], "Only the shape is checked; Fathom works offline and cannot tell whether the mailbox exists.", ok)
    if kind == "phone":
        digits = re.sub(r"\D", "", t)
        ok = t.startswith("+") and 8 <= len(digits) <= 15
        return _res("looks valid (international form)" if ok else "not in international form", [["Digits", len(digits)], ["E.164", "+" + digits]], "International numbers start with + and have 8 to 15 digits. Country rules are not checked.", ok)
    if kind == "ip":
        try:
            a = ipaddress.ip_address(t)
        except ValueError:
            return _res("not valid", [], "", False)
        return _res("valid", [["Version", a.version], ["Private", a.is_private], ["Loopback", a.is_loopback], ["Multicast", a.is_multicast], ["Reserved", a.is_reserved], ["Compressed", a.compressed], ["Expanded", a.exploded]])
    if kind == "uuid":
        import uuid
        try:
            u = uuid.UUID(t)
        except ValueError:
            return _res("not valid", [], "", False)
        return _res("valid", [["Version", u.version], ["Variant", u.variant], ["Plain", u.hex]])
    if kind == "json":
        try:
            json.loads(t); return _res("valid JSON")
        except ValueError as e:
            return _res("not valid", [], str(e), False)
    if kind == "url":
        from urllib.parse import urlsplit
        u = urlsplit(t)
        ok = u.scheme in ("http", "https", "ftp", "ftps", "file", "mailto") and bool(u.netloc or u.path)
        return _res("looks valid" if ok else "not valid", [["Scheme", u.scheme], ["Host", u.hostname or ""]], "", ok)
    if kind == "mac":
        s = re.sub(r"[^0-9A-Fa-f]", "", t)
        ok = len(s) == 12
        return _res("valid" if ok else "not valid", [["Colon form", ":".join(s[i:i + 2] for i in range(0, 12, 2)).upper() if ok else ""], ["Dash form", "-".join(s[i:i + 2] for i in range(0, 12, 2)).upper() if ok else ""], ["Dot form", ".".join(s[i:i + 4] for i in range(0, 12, 4)).lower() if ok else ""]], "", ok)
    raise UserError("Choose what to check.")


# ---------------------------------------------------------------- network calculator
def t_network(text: str, o: dict) -> dict:
    try:
        n = ipaddress.ip_network(text.strip(), strict=False)
    except ValueError:
        raise UserError("Type a network such as 192.168.1.0/24 or 10.0.0.5/255.255.255.0 or 2001:db8::/32.")
    info = [["Network", str(n)], ["Mask", str(n.netmask)], ["Prefix", f"/{n.prefixlen}"], ["Total addresses", f"{n.num_addresses:,}"]]
    if n.version == 4:
        hosts = max(0, n.num_addresses - 2) if n.prefixlen < 31 else n.num_addresses
        info += [["First address", str(n.network_address)], ["Last address", str(n.broadcast_address)], ["Usable hosts", f"{hosts:,}"], ["First host", str(n.network_address + 1) if n.prefixlen < 31 else str(n.network_address)],
                 ["Last host", str(n.broadcast_address - 1) if n.prefixlen < 31 else str(n.broadcast_address)], ["Wildcard", str(n.hostmask)], ["Private", n.is_private]]
    else:
        info += [["First address", str(n.network_address)], ["Last address", str(n.broadcast_address)]]
    out = ""
    split = _int(o.get("split"), 0, 0, 32 if n.version == 4 else 64)
    if split and split > n.prefixlen:
        subs = list(n.subnets(new_prefix=split))
        out = "\n".join(str(s) for s in subs[:1024]) + (f"\n… ({len(subs):,} subnets in all)" if len(subs) > 1024 else "")
    return _res(out, info)


# ---------------------------------------------------------------- cron
def t_cron(text: str, o: dict) -> dict:
    p = text.strip().split()
    if len(p) != 5:
        raise UserError("A cron line has five parts: minute hour day-of-month month day-of-week. Example: 30 8 * * 1-5")
    names = ["minute", "hour", "day of the month", "month", "day of the week"]
    MON = "January February March April May June July August September October November December".split()
    DOW = "Sunday Monday Tuesday Wednesday Thursday Friday Saturday".split()
    def part(s, i):
        if s == "*": return f"every {names[i]}"
        if s.startswith("*/"): return f"every {s[2:]} {names[i]}s"
        def one(x):
            if "-" in x and not x.startswith("-"):
                a, b = x.split("-", 1); return f"{one(a)} to {one(b)}"
            if not x.isdigit(): return x
            n = int(x)
            return MON[n - 1] if i == 3 and 1 <= n <= 12 else DOW[n % 7] if i == 4 else f"{n:02d}" if i < 2 else x
        return ", ".join(one(x) for x in s.split(","))
    desc = f"At {'minute ' + part(p[0], 0) if not p[0].isdigit() or not p[1].isdigit() else p[1].zfill(2) + ':' + p[0].zfill(2)}"
    if p[1].isdigit() and p[0].isdigit():
        pass
    else:
        desc += f", {part(p[1], 1)}"
    if p[2] != "*": desc += f", on day {part(p[2], 2)} of the month"
    if p[3] != "*": desc += f", in {part(p[3], 3)}"
    if p[4] != "*": desc += f", on {part(p[4], 4)}"
    return _res(desc, [[n.capitalize(), v] for n, v in zip(names, p)], "Standard five-field cron. Day names (MON) and @daily shortcuts are not decoded.")


# ---------------------------------------------------------------- numbers in words, roman numerals
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALE = ["", "thousand", "million", "billion", "trillion", "quadrillion"]


def _words(n: int) -> str:
    if n < 20: return ONES[n]
    if n < 100: return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    if n < 1000: return ONES[n // 100] + " hundred" + (" and " + _words(n % 100) if n % 100 else "")
    for i in range(len(SCALE) - 1, 0, -1):
        if n >= 1000 ** i:
            q, r = divmod(n, 1000 ** i)
            return _words(q) + " " + SCALE[i] + (" " + (("and " if r < 100 else "") + _words(r)) if r else "")
    return str(n)


def _roman(n: int) -> str:
    out = ""
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v: out += s; n -= v
    return out


def _unroman(s: str) -> int:
    v = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    t = 0
    for i, c in enumerate(s.upper()):
        if c not in v: raise UserError("Not a Roman numeral.")
        t += -v[c] if i + 1 < len(s) and v[s.upper()[i + 1]] > v[c] else v[c]
    return t


def t_numwords(text: str, o: dict) -> dict:
    t = text.strip().replace(",", "")
    if re.fullmatch(r"[IVXLCDMivxlcdm]+", t):
        n = _unroman(t); return _res(str(n), [["In words", _words(n)]])
    try:
        x = float(t)
    except ValueError:
        raise UserError("Type a number (or a Roman numeral).")
    neg = x < 0; x = abs(x)
    whole = int(x)
    if whole >= 1000 ** len(SCALE):
        raise UserError("That number is too big.")
    w = ("minus " if neg else "") + _words(whole)
    frac = ""
    if "." in t:
        frac = " point " + " ".join(ONES[int(c)] for c in t.split(".")[1] if c.isdigit())
    info = [["Ordinal", (_words(whole) + "th") if whole % 10 not in (1, 2, 3) or 10 < whole % 100 < 14 else {1: _words(whole)[:-3] + "first" if whole % 10 == 1 and whole < 20 else _words(whole) + " (first)"}.get(whole % 10, "")]]
    info = []
    if whole < 4000 and whole > 0 and not neg:
        info.append(["Roman numeral", _roman(whole)])
    info += [["Hexadecimal", hex(whole)], ["Binary", bin(whole)], ["Scientific", f"{x:.6e}"], ["With separators", f"{x:,.2f}" if "." in t else f"{whole:,}"]]
    return _res(w + frac, info)


# ---------------------------------------------------------------- calculator, date maths, percentages
import ast
import operator as op

_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow, ast.Mod: op.mod, ast.FloorDiv: op.floordiv, ast.USub: op.neg, ast.UAdd: op.pos}
_FN = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan, "ln": math.log, "log": math.log10, "log2": math.log2, "exp": math.exp, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil, "fact": math.factorial, "deg": math.degrees, "rad": math.radians}
_CONST = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        a, b = _eval(n.left), _eval(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 10000:
            raise UserError("That power is too large.")
        return _OPS[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_eval(n.operand))
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FN:
        return _FN[n.func.id](*[_eval(a) for a in n.args])
    raise UserError("Only numbers, + - * / ^ % ( ) and functions like sqrt, sin, ln, log, fact are allowed.")


def t_calc(text: str, o: dict) -> dict:
    lines, out = [l for l in text.splitlines() if l.strip()], []
    for l in lines:
        e = l.replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
        e = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", r"(\1/100*\2)", e)
        try:
            r = _eval(ast.parse(e.strip(), mode="eval").body)
            out.append(f"{l.strip()} = {r:.12g}" if isinstance(r, float) else f"{l.strip()} = {r}")
        except UserError as ex:
            out.append(f"{l.strip()} = ({ex})")
        except ZeroDivisionError:
            out.append(f"{l.strip()} = (cannot divide by zero)")
        except Exception:
            out.append(f"{l.strip()} = (not understood)")
    return _res("\n".join(out), [], "Examples: 12% of 250   (3+4)*5^2   sqrt(2)   sin(rad(30))   fact(10)")


def t_datecalc(text: str, o: dict) -> dict:
    def p(s):
        return datetime.fromisoformat(s.strip()).date()
    mode = o.get("mode", "between")
    try:
        if mode == "between":
            a, b = p(text), p(o.get("other", ""))
            d = abs((b - a).days)
            y = abs(b.year - a.year) - ((b.month, b.day) < (a.month, a.day) if b >= a else (a.month, a.day) < (b.month, b.day))
            wd = sum(1 for k in range(d) if (min(a, b).toordinal() + k) % 7 not in (0, 6)) if d < 400000 else 0
            return _res(f"{d} days", [["Weeks", f"{d // 7} weeks {d % 7} days"], ["Years (whole)", y], ["Working days (Mon-Fri)", wd], ["Hours", d * 24], ["Direction", "second is after the first" if b >= a else "second is before the first"]])
        a = p(text); n = _int(o.get("n"), 0, -10**6, 10**6); u = o.get("unit", "days")
        from datetime import timedelta
        if u == "months":
            m = a.month - 1 + n; y = a.year + m // 12; m = m % 12 + 1
            import calendar
            r = date(y, m, min(a.day, calendar.monthrange(y, m)[1]))
        elif u == "years":
            import calendar
            y = a.year + n; r = date(y, a.month, min(a.day, calendar.monthrange(y, a.month)[1]))
        elif u == "workdays":
            r, k = a, n; step = 1 if n >= 0 else -1; k = abs(n)
            while k:
                r += timedelta(days=step)
                if r.weekday() < 5: k -= 1
        else:
            r = a + timedelta(days=n * (7 if u == "weeks" else 1))
        return _res(r.isoformat(), [["Weekday", r.strftime("%A")], ["Week number", r.isocalendar()[1]], ["Day of the year", r.timetuple().tm_yday], ["Leap year", (r.year % 4 == 0 and r.year % 100 != 0) or r.year % 400 == 0]])
    except ValueError:
        raise UserError("Dates look like 2026-10-29.")


TOOLS2 = {"convertdata": t_convertdata, "jwt": t_jwt, "regex": t_regex, "diff": t_diff, "units": t_units, "encode": t_encode, "validate": t_validate,
          "network": t_network, "cron": t_cron, "numwords": t_numwords, "calc": t_calc, "datecalc": t_datecalc}
