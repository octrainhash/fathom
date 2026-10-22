# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Spreadsheets and structured data: CSV, TSV, Excel (.xlsx), JSON, JSON Lines, XML, YAML, TOML, INI, HTML tables, SQL, Markdown tables."""
from __future__ import annotations

import csv
import html as htmllib
import io
import json
import re
from pathlib import Path
from typing import Any, Iterator

from app.convert.core import ConvertError, Ctx, Edge, Engine, Opts, safe_stem

csv.field_size_limit(2**31 - 1)

TABLE_SRC = {"csv", "tsv", "xlsx", "xlsm", "xltx", "jsonl"}
TREE_SRC = {"json", "yaml", "xml"}
ONLY_TREE_SRC = {"toml", "ini"}
TABLE_DST = {"csv", "tsv", "xlsx", "jsonl", "html", "md", "sql"}
TREE_DST = {"json", "yaml", "xml", "toml", "ini"}


def _have(mod: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def infer(v: Any) -> Any:
    """'12' -> 12, '1.5' -> 1.5; everything else (including '007') stays text."""
    if not isinstance(v, str):
        return v
    if re.fullmatch(r"-?(0|[1-9]\d{0,17})", v):
        return int(v)
    if re.fullmatch(r"-?(0|[1-9]\d*)\.\d+", v) and len(v) < 18:
        return float(v)
    return v


def text_of(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


# ---------------------------------------------------------------- reading
class Table:
    """A header plus an iterator of rows (so very large files are streamed, never loaded whole)."""

    def __init__(self, header: list[str], rows: Iterator[list], sheets: list[tuple[str, "Table"]] | None = None):
        self.header, self.rows, self.sheets = header, rows, sheets


def _enc(path: Path) -> str:
    from app.extract import detect_encoding

    return detect_encoding(path)


def read_csv(path: Path, delim: str | None) -> Table:
    enc = _enc(path)
    fh = open(path, "r", encoding=enc, errors="replace", newline="")
    sample = fh.read(65536)
    fh.seek(0)
    if delim is None:
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    reader = csv.reader(fh, delimiter=delim)
    try:
        header = next(reader)
    except StopIteration:
        fh.close()
        raise ConvertError("This table is empty.")

    def gen() -> Iterator[list]:
        try:
            for row in reader:
                if row:
                    yield row
        finally:
            fh.close()

    return Table([h.strip() or f"column{i + 1}" for i, h in enumerate(header)], gen())


def read_jsonl(path: Path) -> Table:
    enc = _enc(path)
    keys: list[str] = []
    seen: set[str] = set()
    objs: list[dict] = []
    # the header needs every key, so the (usually small) file is scanned once
    with open(path, "r", encoding=enc, errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                raise ConvertError("A line of this file is not valid JSON.")
            if isinstance(obj, dict):
                for k in obj:
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
    def gen() -> Iterator[list]:
        with open(path, "r", encoding=enc, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    yield [obj.get(k) if isinstance(obj, dict) else obj for k in keys]
    return Table(keys, gen())


def read_xlsx(path: Path) -> Table:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    sheets: list[tuple[str, Table]] = []
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)

        def gen(it=it) -> Iterator[list]:
            for row in it:
                yield list(row)

        first = None
        rows = gen()
        for first in rows:
            if any(c is not None and c != "" for c in first):
                break
        else:
            continue
        header = [text_of(c).strip() or f"column{i + 1}" for i, c in enumerate(first)]
        sheets.append((ws.title, Table(header, rows)))
    if not sheets:
        raise ConvertError("This workbook has no data in it.")
    t = sheets[0][1]
    t.sheets = sheets
    return t


def rows_from_objects(objs: list) -> Table:
    if not objs:
        raise ConvertError("There are no rows in this file.")
    if all(isinstance(o, dict) for o in objs):
        keys: list[str] = []
        seen: set[str] = set()
        for o in objs:
            for k in o:
                if k not in seen:
                    seen.add(k)
                    keys.append(str(k))
        return Table([k[1:] if k.startswith("@") and k[1:] not in keys else k for k in keys], iter([[o.get(k) for k in keys] for o in objs]))
    if all(isinstance(o, list) for o in objs):
        width = max(len(o) for o in objs)
        head = [text_of(c) or f"column{i + 1}" for i, c in enumerate(objs[0])] + [f"column{i + 1}" for i in range(len(objs[0]), width)]
        return Table(head, iter([list(o) + [None] * (width - len(o)) for o in objs[1:]]))
    return Table(["value"], iter([[o] for o in objs]))


def _find_records(obj: Any, depth: int = 0) -> Any:
    """Digs through wrappers like {"data": {"items": [...]}} or <rows><row/>..</rows> to the list of records."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and depth < 4:
        if len(obj) == 1:
            return _find_records(next(iter(obj.values())), depth + 1)
        lists = [v for v in obj.values() if isinstance(v, list) and v and isinstance(v[0], (dict, list))]
        if len(lists) == 1 and all(not isinstance(v, (dict, list)) or v is lists[0] for v in obj.values()):
            return lists[0]
    return obj


def table_from_tree(obj: Any) -> Table:
    obj = _find_records(obj)
    if isinstance(obj, dict):
        lists = [(k, v) for k, v in obj.items() if isinstance(v, list)]
        if len(lists) == 1 and len(obj) == 1:
            obj = lists[0][1]
        elif lists and all(isinstance(v, (list)) for v in obj.values()):
            sheets = [(str(k), rows_from_objects(v)) for k, v in lists if v]
            if sheets:
                t = sheets[0][1]
                t.sheets = sheets
                return t
        else:
            obj = [obj]
    if not isinstance(obj, list):
        raise ConvertError("This file is not a list of rows, so it cannot become a table.")
    return rows_from_objects(obj)


class _HtmlTable(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.depth = 0
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag == "table":
            self.depth += 1
        elif tag == "tr" and self.depth == 1:
            self._row = []
        elif tag in ("td", "th") and self._row is not None and self.depth == 1:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if self.done:
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self.depth == 1:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self.depth -= 1
            if self.depth == 0 and self.rows:
                self.done = True

    def handle_data(self, data):
        if self._cell is not None and not self.done:
            self._cell.append(data)


def read_html_table(path: Path) -> Table:
    p = _HtmlTable()
    p.feed(path.read_text(encoding=_enc(path), errors="replace"))
    if not p.rows:
        raise ConvertError("There is no table in this web page.")
    width = max(len(r) for r in p.rows)
    head = [(c or f"column{i + 1}") for i, c in enumerate(p.rows[0])] + [f"column{i + 1}" for i in range(len(p.rows[0]), width)]
    return Table(head, iter([r + [""] * (width - len(r)) for r in p.rows[1:]]))


# ---- generic trees
def xml_to_obj(el) -> Any:
    out: dict = {}
    for k, v in el.attrib.items():
        out["@" + k] = v
    kids = list(el)
    for ch in kids:
        tag = re.sub(r"^\{.*?\}", "", ch.tag)
        val = xml_to_obj(ch)
        if tag in out:
            if not isinstance(out[tag], list):
                out[tag] = [out[tag]]
            out[tag].append(val)
        else:
            out[tag] = val
    text = (el.text or "").strip()
    if not kids and not el.attrib:
        return text
    if text:
        out["#text"] = text
    return out


def load_tree(path: Path, s: str) -> Any:
    enc = _enc(path)
    if s == "json":
        txt = path.read_text(encoding=enc, errors="replace")
        try:
            return json.loads(txt)
        except ValueError as exc:
            if txt.lstrip().startswith(("{", "[")) is False and "\n" in txt:   # maybe JSON Lines
                try:
                    return [json.loads(l) for l in txt.splitlines() if l.strip()]
                except ValueError:
                    pass
            raise ConvertError(f"This is not valid JSON ({exc}).")
    if s == "yaml":
        import yaml

        try:
            docs = list(yaml.safe_load_all(path.read_text(encoding=enc, errors="replace")))
        except yaml.YAMLError as exc:
            raise ConvertError(f"This is not valid YAML ({str(exc).splitlines()[0]}).")
        return docs[0] if len(docs) == 1 else docs
    if s == "toml":
        import tomllib

        try:
            return tomllib.loads(path.read_text(encoding=enc, errors="replace"))
        except tomllib.TOMLDecodeError as exc:
            raise ConvertError(f"This is not valid TOML ({exc}).")
    if s == "ini":
        import configparser

        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str  # type: ignore[assignment]
        cp.read_string(path.read_text(encoding=enc, errors="replace"))
        return {sec: dict(cp.items(sec)) for sec in cp.sections()}
    if s == "xml":
        import xml.etree.ElementTree as ET

        try:
            root = ET.parse(str(path)).getroot()
        except ET.ParseError as exc:
            raise ConvertError(f"This is not valid XML ({exc}).")
        return {re.sub(r"^\{.*?\}", "", root.tag): xml_to_obj(root)}
    raise ConvertError("Unsupported data file.")


def xml_name(k: str) -> str:
    k = re.sub(r"[^\w.-]", "_", str(k)) or "item"
    return k if re.match(r"[A-Za-z_]", k) else "_" + k


def obj_to_xml(parent, key: str, val: Any, ET) -> None:
    if isinstance(val, list):
        for v in val:
            obj_to_xml(parent, key, v, ET)
        return
    el = ET.SubElement(parent, xml_name(key))
    if isinstance(val, dict):
        for k, v in val.items():
            if k.startswith("@"):
                el.set(xml_name(k[1:]), text_of(v))
            elif k == "#text":
                el.text = text_of(v)
            else:
                obj_to_xml(el, k, v, ET)
    else:
        el.text = text_of(val)


def write_tree(obj: Any, dst: Path, t: str) -> None:
    if t == "json":
        dst.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    elif t == "yaml":
        import yaml

        dst.write_text(yaml.safe_dump(json.loads(json.dumps(obj, default=str)), allow_unicode=True, sort_keys=False), encoding="utf-8")
    elif t == "toml":
        import tomli_w  # type: ignore

        if not isinstance(obj, dict):
            obj = {"items": obj}
        dst.write_text(tomli_w.dumps(json.loads(json.dumps(obj, default=str))), encoding="utf-8")
    elif t == "ini":
        import configparser

        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str  # type: ignore[assignment]
        if not isinstance(obj, dict) or not all(isinstance(v, dict) for v in obj.values()):
            raise ConvertError("INI files need sections of settings, and this data is not shaped like that.")
        for sec, kv in obj.items():
            cp[str(sec)] = {str(k): text_of(v) for k, v in kv.items()}
        with open(dst, "w", encoding="utf-8") as fh:
            cp.write(fh)
    elif t == "xml":
        import xml.etree.ElementTree as ET

        if isinstance(obj, dict) and len(obj) == 1 and not isinstance(next(iter(obj.values())), list):
            (k, v), = obj.items()
            root = ET.Element(xml_name(k))
            if isinstance(v, dict):
                for kk, vv in v.items():
                    if kk.startswith("@"):
                        root.set(xml_name(kk[1:]), text_of(vv))
                    elif kk == "#text":
                        root.text = text_of(vv)
                    else:
                        obj_to_xml(root, kk, vv, ET)
            else:
                root.text = text_of(v)
        else:
            root = ET.Element("root")
            if isinstance(obj, dict):
                for k, v in obj.items():
                    obj_to_xml(root, k, v, ET)
            else:
                obj_to_xml(root, "item", obj, ET)
        ET.indent(root)
        ET.ElementTree(root).write(str(dst), encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- writing tables (streamed)
def write_table(tab: Table, dst: Path, t: str, name: str, ctx: Ctx, all_sheets: bool = False) -> list[Path]:
    hdr = tab.header
    if t in ("csv", "tsv"):
        with open(dst, "w", encoding="utf-8-sig" if t == "csv" else "utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="," if t == "csv" else "\t")
            w.writerow(hdr)
            for i, r in enumerate(tab.rows):
                w.writerow([text_of(c) for c in r])
                if i % 5000 == 0:
                    ctx.check()
    elif t == "jsonl":
        with open(dst, "w", encoding="utf-8") as fh:
            for i, r in enumerate(tab.rows):
                fh.write(json.dumps({h: infer(c) for h, c in zip(hdr, r)}, ensure_ascii=False, default=str) + "\n")
                if i % 5000 == 0:
                    ctx.check()
    elif t == "json":
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write("[")
            for i, r in enumerate(tab.rows):
                fh.write(("\n  " if i == 0 else ",\n  ") + json.dumps({h: infer(c) for h, c in zip(hdr, r)}, ensure_ascii=False, default=str))
                if i % 5000 == 0:
                    ctx.check()
            fh.write("\n]\n")
    elif t == "html":
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write("<!DOCTYPE html><html><head><meta charset='utf-8'><title>%s</title><style>table{border-collapse:collapse;font-family:sans-serif}"
                     "th,td{border:1px solid #999;padding:4px 8px}th{background:#eee}</style></head><body><table>\n<tr>" % htmllib.escape(name))
            fh.write("".join(f"<th>{htmllib.escape(h)}</th>" for h in hdr) + "</tr>\n")
            for i, r in enumerate(tab.rows):
                fh.write("<tr>" + "".join(f"<td>{htmllib.escape(text_of(c))}</td>" for c in r) + "</tr>\n")
                if i % 5000 == 0:
                    ctx.check()
            fh.write("</table></body></html>\n")
    elif t == "md":
        def cell(c: Any) -> str:
            return text_of(c).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")

        with open(dst, "w", encoding="utf-8") as fh:
            fh.write("| " + " | ".join(cell(h) for h in hdr) + " |\n| " + " | ".join("---" for _ in hdr) + " |\n")
            for i, r in enumerate(tab.rows):
                fh.write("| " + " | ".join(cell(c) for c in r) + " |\n")
                if i % 5000 == 0:
                    ctx.check()
    elif t == "sql":
        tbl = re.sub(r"\W+", "_", name).strip("_") or "data"

        def q(c: Any) -> str:
            if c is None or c == "":
                return "NULL"
            v = infer(c) if isinstance(c, str) else c
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return str(v)
            return "'" + text_of(c).replace("'", "''") + "'"

        cols = ", ".join('"%s"' % h.replace('"', '""') for h in hdr)
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(f'CREATE TABLE "{tbl}" ({", ".join(chr(34) + h.replace(chr(34), chr(34) * 2) + chr(34) + " TEXT" for h in hdr)});\n')
            batch: list[str] = []
            for i, r in enumerate(tab.rows):
                batch.append("(" + ", ".join(q(c) for c in r) + ")")
                if len(batch) >= 500:
                    fh.write(f'INSERT INTO "{tbl}" ({cols}) VALUES\n' + ",\n".join(batch) + ";\n")
                    batch = []
                    ctx.check()
            if batch:
                fh.write(f'INSERT INTO "{tbl}" ({cols}) VALUES\n' + ",\n".join(batch) + ";\n")
    elif t == "xlsx":
        import openpyxl
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import Font

        wb = openpyxl.Workbook(write_only=True)
        sheets = tab.sheets if (all_sheets and tab.sheets) else [(name, tab)]
        used: set[str] = set()
        bold = Font(bold=True)
        for sname, st in sheets:
            base = re.sub(r"[\[\]\\*?:/]", "_", sname)[:31] or "Sheet"
            part = 1
            ws = None
            count = 0
            for i, r in enumerate(st.rows):
                if ws is None or count >= 1048575:
                    nm = base if part == 1 else f"{base[:27]}_{part}"
                    while nm in used:
                        nm += "_"
                    used.add(nm)
                    ws = wb.create_sheet(nm)
                    ws.freeze_panes = "A2"
                    cells = []
                    for h in st.header:
                        c = WriteOnlyCell(ws, value=h)
                        c.font = bold
                        cells.append(c)
                    ws.append(cells)
                    part += 1
                    count = 0
                ws.append([_xl(c) for c in r])
                count += 1
                if i % 5000 == 0:
                    ctx.check()
            if ws is None:
                ws = wb.create_sheet(base)
                ws.append(st.header)
        wb.save(str(dst))
    else:
        raise ConvertError(f"Cannot write {t}.")
    return [dst]


def _xl(c: Any) -> Any:
    if isinstance(c, (dict, list, tuple, set)):
        return json.dumps(c, ensure_ascii=False, default=str)
    if c is not None and not isinstance(c, (str, int, float, bool)):
        try:
            import datetime

            if isinstance(c, (datetime.datetime, datetime.date, datetime.time, datetime.timedelta)):
                return c
        except Exception:
            pass
        return str(c)
    if isinstance(c, str):
        v = infer(c)
        if isinstance(v, str):
            return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v)   # characters Excel cannot store
        return v
    return c


class DataEngine(Engine):
    name = "data"
    label = "Spreadsheets and data files"
    cost = 1.0

    def reads(self) -> set[str]:
        return TABLE_SRC | TREE_SRC | ONLY_TREE_SRC | {"html"}

    def writes(self) -> set[str]:
        w = TABLE_DST | (TREE_DST - {"toml", "ini"})
        if _have("tomli_w"):
            w.add("toml")
        return w

    def can(self, s: str, t: str) -> Edge | None:
        if s == t or s not in self.reads() or t not in self.writes():
            return None
        if s in ONLY_TREE_SRC and t not in TREE_DST:
            return None
        if s == "ini" and t == "toml" or s == "toml" and t == "ini":
            pass
        if s == "html":
            if t in ("csv", "tsv", "xlsx", "json", "jsonl", "md", "sql"):
                return Edge(s, t, self, 1.8, "The first table in the page is used.", multi=False)
            return None
        if s in TABLE_SRC and t == "ini":
            return None
        if s in TABLE_SRC and t == "toml":
            return None
        note = ""
        multi = False
        if s in ("xlsx", "xlsm", "xltx"):
            if t in ("csv", "tsv"):
                note, multi = "Every sheet is saved as its own file.", True
            elif t in ("json", "yaml", "xlsx", "md", "sql", "html"):
                note = ""
            else:
                note = "Only the first sheet is used."
        if s in ("json", "yaml", "xml") and t in TABLE_DST:
            note = "Works when the file is a list of records."
        if s in ("xlsx", "xlsm", "xltx") and t in ("json",):
            pass
        return Edge(s, t, self, 1.0, note, multi)

    def load(self, src: Path, s: str) -> Table | Any:
        if s in ("csv", "tsv"):
            return read_csv(src, "\t" if s == "tsv" else None if s == "csv" else None)
        if s == "jsonl":
            return read_jsonl(src)
        if s in ("xlsx", "xlsm", "xltx"):
            return read_xlsx(src)
        if s == "html":
            return read_html_table(src)
        return load_tree(src, s)

    def convert(self, src: Path, out_dir: Path, s: str, t: str, o: Opts, ctx: Ctx) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_stem(src)
        data = self.load(src, s)
        dst = out_dir / f"{stem}.{t}"
        multi_sheet = isinstance(data, Table) and bool(data.sheets) and len(data.sheets) > 1
        if isinstance(data, Table) and (t in ("yaml", "xml", "toml", "ini") or (t == "json" and multi_sheet)):
            if multi_sheet and t in ("json", "yaml"):
                obj: Any = {n: [dict(zip(tb.header, [infer(c) if isinstance(c, str) else c for c in r])) for r in tb.rows] for n, tb in data.sheets}
            else:
                obj = [dict(zip(data.header, [infer(c) if isinstance(c, str) else c for c in r])) for r in data.rows]
                if t == "xml":
                    obj = {"rows": {"row": obj}}
            write_tree(obj, dst, t)
            return [dst]
        if not isinstance(data, Table):
            if t in TREE_DST:
                write_tree(data, dst, t)
                return [dst]
            data = table_from_tree(data)
        if t in ("csv", "tsv") and data.sheets and len(data.sheets) > 1:
            outs = []
            for n, (sn, tb) in enumerate(data.sheets, 1):
                d = out_dir / f"{stem}_{re.sub(r'[^A-Za-z0-9._ -]', '_', sn)[:40]}.{t}"
                outs += write_table(tb, d, t, sn, ctx)
                ctx.progress(n / len(data.sheets))
            return outs
        if t in ("md", "sql", "html") and data.sheets and len(data.sheets) > 1:       # one workbook, several sheets: all of them go into the one file
            parts = []
            for n, (sn, tb) in enumerate(data.sheets, 1):
                tmp = ctx.scratch("." + t)
                write_table(tb, tmp, t, re.sub(r"[^A-Za-z0-9_]", "_", sn) or f"sheet{n}", ctx)
                txt = tmp.read_text(encoding="utf-8", errors="replace")
                if t == "md":
                    txt = f"## {sn}\n\n{txt}"
                elif t == "html":
                    m = re.search(r"<body[^>]*>(.*)</body>", txt, re.S | re.I)
                    txt = f"<h2>{htmllib.escape(sn)}</h2>\n" + (m.group(1) if m else txt)
                parts.append(txt)
                ctx.progress(n / len(data.sheets))
            if t == "html":
                parts = ["<!doctype html><html><head><meta charset=\"utf-8\"><title>%s</title></head><body>" % htmllib.escape(stem)] + parts + ["</body></html>"]
            dst.write_text("\n\n".join(parts), encoding="utf-8")
            return [dst]
        return write_table(data, dst, t, stem, ctx, all_sheets=(t == "xlsx"))
