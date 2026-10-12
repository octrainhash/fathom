"""Fathom's local web server. The window is a view of this; nothing leaves your PC."""
from __future__ import annotations

import logging
import os
import re
import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import sys
import json
from pathlib import Path
import time
from app import service
from app.paths import ROOT, VERSION, data_root, logs_dir, sessions_dir

STATIC = ROOT / "static"
TOKEN = os.environ.get("FATHOM_TOKEN") or secrets.token_urlsafe(18)
NO_TOKEN = os.environ.get("FATHOM_NO_TOKEN") == "1"
SERVE = os.environ.get("FATHOM_SERVE") == "1"     # server mode: other devices (phone, tablet, another computer) use Fathom in a browser

log = logging.getLogger("fathom")
if not log.handlers:
    handler = logging.FileHandler(logs_dir() / "fathom.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

_warm: dict = {"state": "starting"}


def _warmup() -> None:
    """Load the models in the background so the first search starts instantly."""
    try:
        if service._has("rapidocr_onnxruntime"):
            from app.ocr import get_engine

            get_engine()
        from app.detect import _load, models_ready

        if service._has("onnxruntime") and service._has("tokenizers") and models_ready():
            _load()
        _warm["state"] = "ready"
    except Exception as exc:
        log.exception("warm-up failed")
        _warm.update(state="error", error=str(exc))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_warmup, daemon=True, name="fathom-warmup").start()
    try:
        from app.ai import llm as _llm

        def _ollama_boot() -> None:
            # the free assistant needs Ollama: start it quietly (tray icon only) if it is not running, then load the model
            try:
                from app import ollama_keep
                if _llm.store.load().get("provider") == "ollama":
                    log.info("Ollama startup entry: %s", ollama_keep.drop_autostart())
                    ollama_keep.ensure_running()
            except Exception:
                log.exception("could not make sure Ollama is running")
            _llm.warm_up_ollama()
        threading.Thread(target=_ollama_boot, daemon=True, name="fathom-ollama-warmup").start()
    except Exception:
        pass
    yield


app = FastAPI(title="Fathom", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def _same(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8", "ignore"), b.encode("utf-8", "ignore"))


def guard(request: Request) -> None:
    if not SERVE:     # on the desktop only this computer may talk to the engine (also stops web pages guessing at it)
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        if host not in ("127.0.0.1", "localhost", "[::1]"):
            raise HTTPException(403, "Wrong host.")
    if not NO_TOKEN and not _same(request.headers.get("x-fathom-token") or "", TOKEN):
        raise HTTPException(403, "Open Fathom from its desktop shortcut." if not SERVE else "This link is missing its private key (the part after ?token=).")


@app.exception_handler(service.UserError)
async def _user_error(_request: Request, exc: service.UserError):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.exception_handler(Exception)
async def _unexpected(_request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


class SearchBody(BaseModel):
    query: str
    paths: list[str]
    options: dict = Field(default_factory=dict)


class PathBody(BaseModel):
    path: str


class PickBody(BaseModel):
    kind: str = "files"


def _static_stamp() -> str:
    try:
        newest = max(int(p.stat().st_mtime) for p in STATIC.iterdir() if p.is_file())
    except Exception:
        newest = 0
    return f"{VERSION}-{newest}"


@app.get("/", response_class=HTMLResponse)
def index(token: str = ""):
    if not NO_TOKEN and not _same(token, TOKEN):
        return HTMLResponse("<h3 style='font-family:sans-serif'>Open Fathom from its desktop shortcut or Fathom.bat" + (", or use the full link that fathom.sh / launch.py --serve printed (it ends with ?token=…)" if SERVE else "") + ".</h3>", status_code=403)
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
    # tag every script / style with this build, so an updated Fathom never shows a stale copy kept by the window
    stamp = _static_stamp()
    html = re.sub(r"""(/static/[A-Za-z0-9_.\-]+\.(?:js|css|png|webp|svg|ico|webmanifest|json))(?=["'])""", lambda m: m.group(1) + "?v=" + stamp, html)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION}


@app.get("/api/capabilities", dependencies=[Depends(guard)])
def capabilities():
    return {**service.capabilities(), "warm": _warm}


@app.post("/api/pick", dependencies=[Depends(guard)])
def pick(body: PickBody):
    from app.picker import pick as pick_paths

    try:
        return {"paths": pick_paths(body.kind)}
    except Exception as exc:
        raise service.UserError(f"Could not open the file picker: {exc}")


@app.post("/api/search", dependencies=[Depends(guard)])
def search(body: SearchBody):
    return service.create_search(body.query, body.paths, body.options)


@app.get("/api/jobs/{job_id}", dependencies=[Depends(guard)])
def job(job_id: str, since: int = 0):
    return service.job_status(job_id, since)


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(guard)])
def cancel(job_id: str):
    return service.cancel_job(job_id)


@app.post("/api/reveal", dependencies=[Depends(guard)])
def reveal(body: PathBody):
    return service.reveal(body.path)


@app.post("/api/open", dependencies=[Depends(guard)])
def open_file(body: PathBody):
    return service.open_path(body.path)


@app.get("/api/storage", dependencies=[Depends(guard)])
def storage():
    return service.storage()


@app.post("/api/storage/clear", dependencies=[Depends(guard)])
def clear_storage():
    return service.clear_results()


# ------------------------------------------------------------------ convert, resize and file tools
from app import filetools, filetools2, opsvc  # noqa: E402


class OpBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    recursive: bool = True
    mapping: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    spec: dict = Field(default_factory=dict)
    replace: bool = False
    # file tools
    kind: str = ""
    mode: str = ""
    value: str = ""
    text: str = ""
    text2: str = ""
    password: str = ""
    number: float = 0
    flag: bool = False
    rows: list[dict] = Field(default_factory=list)
    rules: dict = Field(default_factory=dict)
    algos: list[str] = Field(default_factory=list)
    job: str = ""
    remove: list[str] = Field(default_factory=list)


def _post(path: str):
    return app.post(path, dependencies=[Depends(guard)])


@_post("/api/sources/kinds")
def sources_kinds(b: OpBody):
    return opsvc.source_kinds(b.paths, b.recursive, bool(b.options.get("skip_junk", True)))


@_post("/api/convert/plan")
def convert_plan(b: OpBody):
    return opsvc.convert_plan(b.paths, b.recursive)


@_post("/api/convert/run")
def convert_run(b: OpBody):
    return opsvc.convert_start(b.paths, b.recursive, b.mapping, b.options, b.output)


@_post("/api/size/run")
def size_run(b: OpBody):
    return opsvc.size_start(b.paths, b.recursive, b.spec, b.output, b.replace)


@app.get("/api/ops/{job_id}", dependencies=[Depends(guard)])
def op_status(job_id: str, since: int = 0):
    return opsvc.op_status(job_id, since)


@_post("/api/ops/{job_id}/cancel")
def op_cancel(job_id: str):
    return opsvc.op_cancel(job_id)


@app.get("/api/formats", dependencies=[Depends(guard)])
def formats_info():
    return opsvc.formats_info()


@app.get("/api/formats/{fmt}", dependencies=[Depends(guard)])
def format_targets(fmt: str):
    from app.convert import engines, formats

    return {"id": fmt, "label": formats.label(fmt), "category": formats.category(fmt), "targets": engines.targets_for(fmt)}


@_post("/api/tools/merge")
def t_merge(b: OpBody):
    return filetools2.merge_start(b.paths, b.recursive, b.kind, b.output, b.options)


@_post("/api/tools/split")
def t_split(b: OpBody):
    return filetools2.split_start(b.paths, b.recursive, b.mode, b.value, b.output, b.options)


@_post("/api/tools/join")
def t_join(b: OpBody):
    return filetools2.join_parts_start(b.paths, b.output)


@_post("/api/tools/trim")
def t_trim(b: OpBody):
    return filetools2.trim_start(b.paths, b.recursive, b.text, b.text2, b.flag, b.output)


@_post("/api/tools/rotate")
def t_rotate(b: OpBody):
    return filetools2.rotate_start(b.paths, b.recursive, int(b.number), b.mode, b.output, str(b.options.get("pages") or ""), str(b.options.get("orient") or "any"))


@_post("/api/tools/extract")
def t_extract(b: OpBody):
    return filetools2.extract_start(b.paths, b.recursive, b.mode, b.number or 1, b.value or "jpg", b.output, str(b.options.get("pages") or ""))


@_post("/api/tools/lock")
def t_lock(b: OpBody):
    return filetools2.encrypt_start(b.paths, b.recursive, b.password, b.flag, b.output, b.mode or "aes")


@_post("/api/tools/pdflock")
def t_pdflock(b: OpBody):
    return filetools2.pdf_lock_start(b.paths, b.recursive, b.password, b.flag, b.output)


@_post("/api/tools/pack")
def t_pack(b: OpBody):
    return filetools2.pack_start(b.paths, b.value or "zip", b.text, b.password, int(b.number or 9), b.output, b.options)


@_post("/api/tools/hash")
def t_hash(b: OpBody):
    return filetools.hash_start(b.paths, b.recursive, b.algos or ["sha256"], b.text)


@_post("/api/tools/dups")
def t_dups(b: OpBody):
    return filetools.dups_start(b.paths, b.recursive, int(b.number or 1))


@_post("/api/tools/dups/apply")
def t_dups_apply(b: OpBody):
    return filetools.dups_apply(b.job, b.mode, b.remove, b.value)


@_post("/api/tools/info")
def t_info(b: OpBody):
    return {"files": filetools.file_info(b.paths)}


@_post("/api/tools/fixext")
def t_fixext(b: OpBody):
    return filetools.fix_extensions(b.paths)


@_post("/api/tools/meta")
def t_meta(b: OpBody):
    return {"files": filetools.meta_view(b.paths)}


@_post("/api/tools/meta/strip")
def t_meta_strip(b: OpBody):
    return filetools.meta_strip_start(b.paths, b.recursive, b.output)


@_post("/api/tools/rename/preview")
def t_rename_preview(b: OpBody):
    return filetools.rename_preview(b.paths, b.recursive, b.rules)


@_post("/api/tools/rename/apply")
def t_rename_apply(b: OpBody):
    return filetools.rename_apply(b.rows)


@_post("/api/tools/organize/preview")
def t_org_preview(b: OpBody):
    return filetools.organize_preview(b.paths, b.recursive, b.mode, b.value, b.flag)


@_post("/api/tools/organize/apply")
def t_org_apply(b: OpBody):
    return filetools.organize_apply(b.rows, b.flag)


@_post("/api/tools/emptyfolders")
def t_empty(b: OpBody):
    return {"folders": filetools.empty_folders(b.paths)}


@_post("/api/tools/emptyfolders/remove")
def t_empty_rm(b: OpBody):
    return filetools.remove_folders(b.remove)


@app.get("/api/tools/undo", dependencies=[Depends(guard)])
def t_undo_state():
    return filetools.undo_available()


@_post("/api/tools/undo")
def t_undo():
    return filetools.undo_last()


@_post("/api/pick/folder-out")
def pick_out():
    from app.picker import pick as pick_paths

    return {"paths": pick_paths("folder")}


# ------------------------------------------------------------------ drives
from app import drives  # noqa: E402


class DriveBody(BaseModel):
    letter: str = ""
    kind: str = ""
    params: dict = Field(default_factory=dict)
    path: str = ""
    paths: list[str] = Field(default_factory=list)
    fs: str = ""
    flag: bool = False
    text: str = ""
    keys: list[str] = Field(default_factory=list)
    uses: list[str] = Field(default_factory=list)
    number: float = 0
    job: str = ""


@app.get("/api/drives", dependencies=[Depends(guard)])
def drives_list():
    return drives.list_drives()


@app.get("/api/drives/health", dependencies=[Depends(guard)])
def drives_health():
    return drives.health()


@app.get("/api/drives/tune", dependencies=[Depends(guard)])
def drives_tune_state():
    return drives.tune_state()


@_post("/api/drives/tune")
def drives_tune(b: DriveBody):
    return drives.tune_apply(b.keys)


@_post("/api/drives/action")
def drives_action(b: DriveBody):
    return drives.drive_job(b.kind, b.letter, b.params)


@_post("/api/drives/compress")
def drives_compress(b: DriveBody):
    return drives.compress_folder(b.path, b.flag, b.text or "balanced")


@_post("/api/drives/image")
def drives_image(b: DriveBody):
    return drives.image_action(b.path, b.flag)


@_post("/api/drives/space")
def drives_space(b: DriveBody):
    return drives.space_scan(b.path)


@_post("/api/drives/compat")
def drives_compat(b: DriveBody):
    return drives.compat_check(b.paths, b.fs)


@_post("/api/drives/compat/fix")
def drives_compat_fix(b: DriveBody):
    return drives.compat_fix(b.job)


@_post("/api/drives/advise")
def drives_advise(b: DriveBody):
    return drives.advise(b.uses, b.number, b.flag)


# ------------------------------------------------------------------ scanner, data finder, shredder, encodings, permissions, dates
from app import filetools3  # noqa: E402


@app.get("/api/tools/meta-info", dependencies=[Depends(guard)])
def tools_meta_info():
    return {"patterns": {k: v[0] for k, v in filetools3.PATTERNS.items()}, "shred": {k: v[0] for k, v in filetools3.METHODS.items()},
            "encodings": list(filetools3.TEXT_ENC), "codecs": {k: v[0] for k, v in filetools3.CODECS.items()}}


@_post("/api/tools/scan")
def t_scan(b: OpBody):
    return filetools3.scan_start(b.paths, b.recursive, b.mode or "magic", b.flag, bool(b.options.get("sharpen")), b.kind or "jpg", b.output)


from app import textedit  # noqa: E402


@_post("/api/tools/replace")
def t_replace(b: OpBody):
    o = dict(b.options)
    return textedit.replace_start(b.paths, b.recursive, list(o.get("pairs") or []), o, b.output, bool(o.get("dry")))


# ---------------------------------------------------------------- stamps and signatures
from app import printing, stamp, torrent  # noqa: E402


class StampBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    recursive: bool = True
    spec: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    name: str = ""
    kind: str = "signature"
    id: str = ""


@app.get("/api/stamp/items", dependencies=[Depends(guard)])
def stamp_items():
    return {"items": stamp.list_items(), "presets": stamp.PRESETS}


@_post("/api/stamp/render")
def stamp_render(b: StampBody):
    return {"png": stamp._thumb_data(stamp.make_from_spec(b.spec), 700)}


@_post("/api/stamp/save")
def stamp_save(b: StampBody):
    return stamp.save_item(b.name, b.kind, stamp.make_from_spec(b.spec))


@_post("/api/stamp/delete")
def stamp_delete(b: StampBody):
    stamp.delete_item(b.id)
    return {"ok": True}


@_post("/api/tools/stamp")
def t_stamp(b: StampBody):
    return stamp.apply_start(b.paths, b.recursive, b.spec, b.output)


# ---------------------------------------------------------------- print / copy
@app.get("/api/print/printers", dependencies=[Depends(guard)])
def print_printers():
    return printing.list_printers()


@_post("/api/tools/print")
def t_print(b: OpBody):
    o = dict(b.options)
    return printing.print_start(b.paths, b.recursive, str(o.get("printer", "")), int(o.get("copies", 1) or 1), o)


@_post("/api/tools/copy")
def t_copy(b: OpBody):
    o = dict(b.options)
    return printing.copy_start(str(o.get("scanner", "")), str(o.get("printer", "")), int(o.get("copies", 1) or 1), int(o.get("dpi", 300) or 300), str(o.get("mode", "color")), str(o.get("host", "")), o)


# ---------------------------------------------------------------- torrents
class TorBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    source: str = ""
    save: str = ""
    id: str = ""
    action: str = ""
    value: object = None
    trackers: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    comment: str = ""
    private: bool = False
    piece_kb: int = 0
    web_seeds: list[str] = Field(default_factory=list)
    output: dict = Field(default_factory=dict)
    down: int = 0
    up: int = 0
    name: str = ""


@app.get("/api/torrent/status", dependencies=[Depends(guard)])
def tor_status():
    return torrent.status()


@_post("/api/torrent/add")
def tor_add(b: TorBody):
    return torrent.add(b.source, b.save, bool(b.value))


@_post("/api/torrent/act")
def tor_act(b: TorBody):
    return torrent.act(b.id, b.action, b.value)


@app.get("/api/torrent/files", dependencies=[Depends(guard)])
def tor_files(id: str):
    return {"files": torrent.files_of(id)}


@_post("/api/torrent/limits")
def tor_limits(b: TorBody):
    return torrent.set_limits(b.down, b.up)


@_post("/api/torrent/info")
def tor_info(b: TorBody):
    from pathlib import Path as _P
    return torrent.info_of(_P(b.source))


@_post("/api/torrent/make")
def tor_make(b: TorBody):
    return torrent.make_start(b.paths, b.trackers, b.comment, b.private, b.piece_kb, b.web_seeds, b.output)


@_post("/api/torrent/links")
def tor_links(b: TorBody):
    return torrent.download_start(b.urls, b.output, b.name)


# ---------------------------------------------------------------- compare, QR, hex, touch-up
from app import extras  # noqa: E402


class ExBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    recursive: bool = True
    a: str = ""
    b: str = ""
    path: str = ""
    text: str = ""
    mode: str = ""
    number: int = 0
    length: int = 4096
    items: list = Field(default_factory=list)
    options: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    name: str = ""


@_post("/api/tools/compare")
def t_compare(b: ExBody):
    return extras.compare_start(b.a, b.b, bool(b.options.get("ignore_space")))


@_post("/api/tools/qr/make")
def t_qr_make(b: ExBody):
    import base64 as _b64
    o = b.options
    png = extras.qr_png(b.text, int(o.get("scale", 10)), str(o.get("ecc", "M")), str(o.get("dark", "#000000")), str(o.get("light", "#ffffff")))
    return {"png": "data:image/png;base64," + _b64.b64encode(png).decode()}


@_post("/api/tools/qr/save")
def t_qr_save(b: ExBody):
    o = b.options
    return extras.qr_save_start(b.text, int(o.get("scale", 10)), str(o.get("ecc", "M")), str(o.get("dark", "#000000")), str(o.get("light", "#ffffff")), b.name, b.output)


@_post("/api/tools/qr/read")
def t_qr_read(b: ExBody):
    return extras.qr_read_start(b.paths, b.recursive)


@_post("/api/tools/hex/view")
def t_hex_view(b: ExBody):
    return extras.hex_view(b.path, b.number, b.length)


@_post("/api/tools/hex/find")
def t_hex_find(b: ExBody):
    return extras.hex_find(b.path, b.text, b.mode, b.number)


@_post("/api/tools/hex/patch")
def t_hex_patch(b: ExBody):
    return extras.hex_patch_start(b.path, list(b.items), b.output)


@_post("/api/tools/touchup")
def t_touchup(b: ExBody):
    return extras.touchup_start(b.paths, b.recursive, dict(b.options), b.output)


# ---------------------------------------------------------------- the editor
from app import editor  # noqa: E402


class EdBody(BaseModel):
    path: str = ""
    kind: str = ""
    payload: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    replace: bool = False
    sheet: str = ""
    r0: int = 1
    c0: int = 1
    table: str = ""
    offset: int = 0


@_post("/api/editor/open")
def ed_open(b: EdBody):
    return editor.open_file(b.path)


@_post("/api/editor/save")
def ed_save(b: EdBody):
    return editor.save(b.path, b.kind, b.payload, b.output, b.replace)


@_post("/api/editor/sheet")
def ed_sheet(b: EdBody):
    return editor.sheet_cells(b.path, b.sheet, max(1, b.r0), max(1, b.c0))


@_post("/api/editor/dbrows")
def ed_dbrows(b: EdBody):
    return editor.db_rows(b.path, b.table, max(0, b.offset), 100)


@app.get("/api/editor/image")
def ed_image(path: str, t: str = ""):
    if not NO_TOKEN and t != TOKEN:
        raise HTTPException(403)
    from fastapi.responses import Response
    try:
        data, ct = editor.image_bytes(path)
    except Exception:
        raise HTTPException(415)
    return Response(data, media_type=ct, headers={"Cache-Control": "no-store"})


@_post("/api/tools/scrape")
def t_scrape(b: OpBody):
    return filetools3.scrape_start(b.paths, b.recursive, b.algos, b.text, bool(b.options.get("ocr")), bool(b.options.get("binary")))


@_post("/api/tools/scrape/export")
def t_scrape_export(b: OpBody):
    return filetools3.scrape_export(b.job, b.output, b.flag)


@_post("/api/tools/shred")
def t_shred(b: OpBody):
    return filetools3.shred_start(b.paths, b.recursive, b.mode, b.text)


@_post("/api/tools/codec")
def t_codec(b: OpBody):
    return filetools3.codec_start(b.paths, b.recursive, b.kind, b.mode, b.value, b.text, b.text2, b.options.get("newline", "keep"), b.output)


@_post("/api/tools/perms")
def t_perms_view(b: OpBody):
    return {"files": filetools3.perms_view(b.paths)}


@_post("/api/tools/perms/apply")
def t_perms_apply(b: OpBody):
    o = b.options
    return filetools3.perms_apply(b.paths, b.recursive, o.get("readonly", ""), o.get("hidden", ""), o.get("mode", ""), o.get("acl", ""), o.get("principal", ""), o.get("rights", "R"))


@_post("/api/tools/times")
def t_times(b: OpBody):
    return filetools3.times_start(b.paths, b.recursive, b.mode, b.text, b.number, b.algos)


@_post("/api/tools/exif")
def t_exif(b: OpBody):
    o = b.options
    return filetools3.exif_edit_start(b.paths, b.recursive, bool(o.get("remove_gps")), o.get("date", ""), o.get("artist", ""), o.get("copyright", ""), o.get("description", ""), b.output)


@_post("/api/tools/arrange")
def t_arrange(b: OpBody):
    return filetools3.pdf_arrange_start(b.paths, b.text, int(b.number or 0), b.output)


@_post("/api/pdf/info")
def pdf_info(b: OpBody):
    from app import pdfview
    return pdfview.info(b.paths[0] if b.paths else "")


@app.get("/api/pdf/page")
def pdf_page(path: str, page: int = 0, t: str = "", size: int = 160):
    """a small picture of one PDF page (page picker); the token travels in the address because <img> cannot send headers"""
    if not NO_TOKEN and t != TOKEN:
        raise HTTPException(403)
    from fastapi.responses import Response

    from app import pdfview
    try:
        data = pdfview.thumb_png(path, max(0, page), size)
    except Exception:
        raise HTTPException(415)
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


@_post("/api/tools/preview")
def tool_preview(b: OpBody):
    """BEFORE / AFTER of one chosen page or picture for a tool (touchup, scan) with the options being set on screen"""
    from app import livepreview
    return livepreview.make(b.mode, b.paths[0] if b.paths else "", int(b.number or 0), dict(b.options), int(b.value or 800))


@_post("/api/preview/files")
def preview_files(b: OpBody):
    from app import pdfview
    return pdfview.previewable(b.paths, b.recursive)


@app.get("/api/preview/page")
def preview_page(path: str, page: int = 0, t: str = "", size: int = 900):
    """one page of a PDF / document, or a picture, as a PNG for the 'preview on my file' screens; the page size and count travel in headers"""
    if not NO_TOKEN and t != TOKEN:
        raise HTTPException(403)
    from fastapi.responses import Response

    from app import pdfview
    try:
        data, meta = pdfview.page_png(path, max(0, page), size)
    except Exception as e:
        raise HTTPException(415, str(e)[:200])
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=300", "X-Pages": str(meta.get("pages", 1)), "X-Size": f"{meta.get('shown_w', 0)}x{meta.get('shown_h', 0)}", "Access-Control-Expose-Headers": "X-Pages, X-Size"})


@app.get("/api/thumb")
def thumb(path: str, t: str = "", size: int = 900):
    """A small JPEG preview of any picture on this PC (used by result lists). The token travels in the address because <img> cannot send headers."""
    if not NO_TOKEN and t != TOKEN:
        raise HTTPException(403)
    import io

    from PIL import Image

    from app.convert.core import file_bytes
    from app.convert.eng_image import load_frames
    from app.convert import formats

    p = __import__("pathlib").Path(path)
    if not p.is_file():
        raise HTTPException(404)
    try:
        fmt = formats.detect(p)
        frames, _d, _f = load_frames(p, fmt, all_frames=False)
        im = frames[0].convert("RGB")
        im.thumbnail((max(64, min(size, 2000)),) * 2)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    except Exception:
        raise HTTPException(415)
    from fastapi.responses import Response

    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@app.post("/api/quit", dependencies=[Depends(guard)])
def quit_app():
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return {"ok": True}


_SID = re.compile(r"^[0-9a-f]{32}$")


@app.get("/media/{sid}/{name}")
def media(sid: str, name: str):
    if not _SID.match(sid) or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(404)
    path = sessions_dir() / sid / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})



# ---------------------------------------------------------------- lab: forensics, disk images, junk, network sync
from app import forensics, junk, netsync, vmimage  # noqa: E402


class LabBody(BaseModel):
    paths: list[str] = Field(default_factory=list)
    path: str = ""
    recursive: bool = True
    kinds: list[str] = Field(default_factory=list)
    items: list = Field(default_factory=list)
    action: str = ""
    text: str = ""
    password: str = ""
    output: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)
    cfg: dict = Field(default_factory=dict)
    job: str = ""
    flag: bool = False
    number: float = 0


@_post("/api/lab/ads/scan")
def lab_ads_scan(b: LabBody):
    return forensics.ads_scan_start(b.paths, b.recursive)


@_post("/api/lab/ads/strip")
def lab_ads_strip(b: LabBody):
    return forensics.ads_strip(b.items, b.text)


@_post("/api/lab/attrs/find")
def lab_attrs_find(b: LabBody):
    return {"items": forensics.find_hidden(b.path, b.recursive), "platform": sys.platform}


@_post("/api/lab/attrs/apply")
def lab_attrs_apply(b: LabBody):
    return forensics.attr_apply(b.paths, b.action, b.recursive)


@app.get("/api/lab/carve/kinds", dependencies=[Depends(guard)])
def lab_carve_kinds():
    return {"kinds": forensics.CARVE_LABELS}


@_post("/api/lab/carve")
def lab_carve(b: LabBody):
    return forensics.carve_start(b.path, b.kinds, b.output, int(b.options.get("min_kb", 1)), bool(b.options.get("aligned", True)))


@_post("/api/lab/image/make")
def lab_image_make(b: LabBody):
    return forensics.image_start(b.path, b.output, b.text)


@_post("/api/lab/repair")
def lab_repair(b: LabBody):
    return forensics.repair_start(b.paths, b.recursive, b.output)


@app.get("/api/lab/damage/modes", dependencies=[Depends(guard)])
def lab_damage_modes():
    return {"modes": filetools3.DAMAGE_MODES}


@_post("/api/lab/damage")
def lab_damage(b: LabBody):
    return filetools3.damage_start(b.paths, b.recursive, b.action, float(b.number or 10), b.output)


@app.get("/api/lab/scanner/list", dependencies=[Depends(guard)])
def lab_scanner_list(host: str = ""):
    from app import scanner
    try:
        return scanner.list_all(host)
    except service.UserError as e:
        return {"scanners": [], "available": False, "why": str(e)}


@_post("/api/lab/scanner/scan")
def lab_scanner_scan(b: LabBody):
    from app import scanner
    o = b.options
    return scanner.scan_start(b.path, int(o.get("dpi", 300)), str(o.get("mode", "color")), str(o.get("out", "jpg")), b.output, o)


@app.get("/api/drives/fs/caps", dependencies=[Depends(guard)])
def drives_fs_caps():
    from app import fsformat
    return fsformat.capabilities()


@_post("/api/drives/fs/format")
def drives_fs_format(b: LabBody):
    from app import fsformat
    o = b.options
    return fsformat.format_start(b.text, b.action or "image", b.output, str(o.get("name", "")), int(b.number or 0), str(o.get("label", "")), b.path, str(o.get("confirm", "")))


@_post("/api/lab/steg/scan")
def lab_steg_scan(b: LabBody):
    return forensics.steg_scan_start(b.paths, b.recursive, b.password, b.output)


@_post("/api/lab/steg/hide")
def lab_steg_hide(b: LabBody):
    return forensics.steg_hide_start(b.path, b.text, b.password, b.output)


@_post("/api/lab/steg/capacity")
def lab_steg_cap(b: LabBody):
    return {"bytes": forensics.steg_capacity(b.path)}


@_post("/api/lab/image/list")
def lab_image_list(b: LabBody):
    return vmimage.list_entries(b.path)


@_post("/api/lab/image/extract")
def lab_image_extract(b: LabBody):
    return vmimage.extract_start(b.path, [str(i) for i in b.items], b.output)


@_post("/api/lab/junk/scan")
def lab_junk_scan(b: LabBody):
    return junk.scan_start()


@_post("/api/lab/junk/clear")
def lab_junk_clear(b: LabBody):
    return junk.clear(b.job, b.kinds, b.action or "recycle", [str(i) for i in b.items])


@app.get("/api/lab/net/kinds", dependencies=[Depends(guard)])
def lab_net_kinds():
    return {"kinds": netsync.KINDS}


@_post("/api/lab/net/browse")
def lab_net_browse(b: LabBody):
    return netsync.browse(b.cfg, b.path)


@_post("/api/lab/net/sync")
def lab_net_sync(b: LabBody):
    return netsync.sync_start(b.cfg, b.action, b.text, b.path, b.options)


# ---------------------------------------------------------------- the assistant and "My tools"
from app.ai import agent as ai_agent, llm as ai_llm, plugins as ai_plugins, store as ai_store  # noqa: E402


class AiSettings(BaseModel):
    settings: dict = Field(default_factory=dict)
    keys: dict = Field(default_factory=dict)


class AiSend(BaseModel):
    sid: str = ""
    text: str = ""
    attachments: list[dict] = Field(default_factory=list)
    voice: bool = False
    lang: str = ""


class AiScreen(BaseModel):
    on: bool | None = None


class AiSpeak(BaseModel):
    text: str
    lang: str = ""
    voice: str = ""


class AiAudio(BaseModel):
    data: str
    lang: str = ""


class AiAnswer(BaseModel):
    sid: str
    id: str
    answer: str = ""


class AiSid(BaseModel):
    sid: str = ""


class AiContext(BaseModel):
    context: dict = Field(default_factory=dict)


class AiUpload(BaseModel):
    name: str = "pasted"
    data: str = ""          # base64


class PluginRun(BaseModel):
    id: str
    paths: list[str] = Field(default_factory=list)
    recursive: bool = True
    output: dict = Field(default_factory=dict)
    inputs: dict = Field(default_factory=dict)


class PluginId(BaseModel):
    id: str


@app.get("/api/ai/settings", dependencies=[Depends(guard)])
def ai_settings_get():
    return ai_store.public()


@_post("/api/ai/settings")
def ai_settings_set(b: AiSettings):
    for name, val in (b.keys or {}).items():
        ai_store.set_secret(name, str(val or ""))
    if b.settings:
        ai_store.save(b.settings)
    return ai_store.public()


@_post("/api/ai/test")
def ai_test(b: AiSid):
    return ai_llm.test_connection()


@app.get("/api/ai/chats", dependencies=[Depends(guard)])
def ai_chats():
    return {"chats": ai_store.list_chats()}


@app.get("/api/ai/chat/{sid}", dependencies=[Depends(guard)])
def ai_chat(sid: str):
    s = ai_agent.get_session(sid)
    return {"id": s.id, "title": s.title, "status": s.status, "events": s.events[-1500:], "seq": s.seq}


@_post("/api/ai/chat/{sid}/delete")
def ai_chat_delete(sid: str):
    ai_agent.delete(sid)
    return {"ok": True}


@_post("/api/ai/send")
def ai_send(b: AiSend):
    s = ai_agent.send(b.sid or None, b.text, b.attachments, b.voice, b.lang)
    return {"sid": s.id}


@app.get("/api/ai/events", dependencies=[Depends(guard)])
def ai_events(sid: str, since: int = 0, wait: int = 0):
    s = ai_agent.get_session(sid)
    evs = s.wait_events(since, min(25, wait))
    return {"events": evs, "status": s.status, "seq": s.seq, "title": s.title}


@_post("/api/ai/answer")
def ai_answer(b: AiAnswer):
    ai_agent.answer(b.sid, b.id, b.answer)
    return {"ok": True}


@_post("/api/ai/stop")
def ai_stop(b: AiSid):
    ai_agent.stop(b.sid)
    return {"ok": True}


@_post("/api/ai/context")
def ai_context(b: AiContext):
    ai_agent.update_context(b.context)
    return {"ok": True}


@_post("/api/ai/upload")
def ai_upload(b: AiUpload):
    import base64
    import re as _re
    name = _re.sub(r'[\\/:*?"<>|]+', "_", b.name or "pasted")[:100] or "pasted"
    d = ai_store.root() / "uploads" / time.strftime("%Y%m%d")
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    n = 2
    while p.exists():
        p = d / f"{p.stem.rsplit(' (', 1)[0]} ({n}){p.suffix}"
        n += 1
    p.write_bytes(base64.b64decode(b.data.split(",", 1)[-1]))
    return {"path": str(p), "name": p.name}


@app.get("/api/ai/plugins", dependencies=[Depends(guard)])
def ai_plugins_list():
    return {"tools": ai_plugins.listing()}


@app.get("/api/ai/plugins/{pid}", dependencies=[Depends(guard)])
def ai_plugin_get(pid: str):
    return ai_plugins.get(pid)


@_post("/api/ai/plugins/run")
def ai_plugin_run(b: PluginRun):
    return ai_plugins.run_start(b.id, b.paths, b.recursive, b.output, b.inputs)


@_post("/api/ai/plugins/delete")
def ai_plugin_delete(b: PluginId):
    ai_plugins.delete(b.id)
    return {"ok": True}


# ---------------------------------------------------------------- handwriting
from app import handwriting  # noqa: E402


@_post("/api/tools/handwriting")
def t_handwriting(b: OpBody):
    return handwriting.read_start(b.paths, b.recursive, b.options, b.output)


@app.get("/api/handwriting/info", dependencies=[Depends(guard)])
def handwriting_info():
    return handwriting.info()


@_post("/api/handwriting/install")
def handwriting_install(b: AiSid):
    return handwriting.install_start()


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# ---------------------------------------------------------------- Activity & Undo
class HistoryUndo(BaseModel):
    id: str
    force: bool = False


class HistorySettings(BaseModel):
    keep_days: int | None = None
    enabled: bool | None = None
    clear: bool = False


@app.get("/api/history", dependencies=[Depends(guard)])
def history_list(q: str = "", limit: int = 300):
    from app import history
    return history.listing(limit, q)


@_post("/api/history/undo")
def history_undo(b: HistoryUndo):
    from app import history
    try:
        return history.undo(b.id, b.force)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@_post("/api/history/settings")
def history_settings(b: HistorySettings):
    from app import history
    if b.clear:
        history.prune(everything=True)
    s = history.set_settings(b.keep_days, b.enabled)
    if b.keep_days is not None:
        history.prune()
    return {**s, "copies_bytes": history.copies_bytes()}


# ---------------------------------------------------------------- Report a problem (a zip of logs, never keys or file contents)
@_post("/api/support/bundle")
def support_bundle():
    import platform, zipfile
    out_dir = Path.home() / "Downloads"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"fathom-report-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    info = {"version": VERSION, "python": platform.python_version(), "os": platform.platform(), "machine": platform.machine(), "time": time.ctime()}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("about.json", json.dumps(info, indent=1))
        for d in (logs_dir(), data_root()):
            for f in list(d.glob("*.log"))[:20]:
                try:
                    if f.stat().st_size < 30_000_000:
                        z.write(f, f"logs/{f.name}")
                except OSError:
                    pass
    return {"path": str(out)}


# ---------------------------------------------------------------- Assistant: live screen and voice
@_post("/api/ai/screen")
def ai_screen(b: AiScreen):
    from app.ai import screen
    return screen.set_on(b.on) if b.on is not None else screen.state()


@_post("/api/ai/screen/frame")
def ai_screen_frame():
    from app.ai import screen
    if not screen.is_on():
        raise service.UserError("Screen watching is off.")
    try:
        f = screen.grab(max_side=640, quality=55)
    except RuntimeError as exc:
        raise service.UserError(str(exc))
    return {"data": f"data:{f['media_type']};base64,{f['data']}", "width": f["width"], "height": f["height"]}


@app.get("/api/ai/voice", dependencies=[Depends(guard)])
def ai_voice_info():
    from app import speech
    return {"whisper": speech.available(), "openai": bool(ai_store.get_secret("openai"))}


@_post("/api/ai/transcribe")
def ai_transcribe(b: AiAudio):
    """Microphone recording -> text, in any language. Local Whisper first (no internet needed), else the OpenAI service if a key is saved."""
    import base64
    import tempfile
    from app import speech
    raw = base64.b64decode(b.data.split(",", 1)[-1])
    if len(raw) < 800:
        return {"text": "", "language": ""}
    ext = ".webm"
    head = b.data[:60].lower()
    if "ogg" in head:
        ext = ".ogg"
    elif "mp4" in head or "aac" in head:
        ext = ".m4a"
    elif "wav" in head:
        ext = ".wav"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as fh:
        fh.write(raw)
        tmp = Path(fh.name)
    try:
        lang = (b.lang or "").split("-")[0].lower()
        if lang in ("auto", "any"):
            lang = ""
        if speech.available():
            try:
                return speech.transcribe_any(tmp, "small", lang)
            except Exception as exc:
                log.exception("local transcription failed")
                if not ai_store.get_secret("openai"):
                    raise service.UserError(f"Could not understand the recording ({exc}).")
        key = ai_store.get_secret("openai")
        if key:
            import urllib.request, uuid as _uuid
            boundary = _uuid.uuid4().hex
            parts = [("model", "whisper-1")] + ([("language", lang)] if lang else [])
            body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in parts)
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a{ext}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + raw + f"\r\n--{boundary}--\r\n".encode()
            base = (ai_store.load()["base_urls"].get("openai") or "https://api.openai.com/v1").rstrip("/")
            req = urllib.request.Request(base + "/audio/transcriptions", data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "multipart/form-data; boundary=" + boundary})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return {"text": json.loads(r.read().decode("utf-8")).get("text", "").strip(), "language": lang}
            except Exception as exc:
                raise service.UserError(f"The speech service could not read the recording ({exc}).")
        raise service.UserError("no-engine")
    finally:
        tmp.unlink(missing_ok=True)


@_post("/api/ai/speak")
def ai_speak(b: AiSpeak):
    """Text -> a sound file (OpenAI voice if chosen, else the computer's own voice) so the window can play it in any language the computer has a voice for."""
    import base64
    import tempfile
    from app.ai import media
    d = Path(tempfile.mkdtemp(prefix="fxsay_"))
    try:
        try:
            r = media.speak(b.text[:1500], d / "say", b.voice, b.lang)
        except Exception as exc:
            log.warning("speak failed: %s", exc)
            raise
        p = Path(r["path"])
        mime = "audio/mpeg" if p.suffix == ".mp3" else "audio/wav"
        return {"data": f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode(), "mime": mime}
    finally:
        import shutil as _sh
        _sh.rmtree(d, ignore_errors=True)


# --- the computer's own speakers: the engine plays the voice itself (the window's sound can be silent on some PCs) ---
_say_ready: dict = {}
_say_lock = threading.Lock()


def _local_speakers_ok(request: Request) -> bool:
    """True only on a Windows PC when the person is using the window on this very computer (not another device over the network)."""
    host = request.client.host if request.client else ""
    return sys.platform.startswith("win") and not os.environ.get("FATHOM_SERVE") and host in ("127.0.0.1", "::1", "localhost")


@_post("/api/ai/speak_prepare")
def ai_speak_prepare(b: AiSpeak, request: Request):
    """Makes the voice file and keeps it ready; the answer says whether this PC will play it itself (local) or the window must (local=false)."""
    import tempfile
    from app.ai import media
    if not _local_speakers_ok(request):
        return {"local": False}
    d = Path(tempfile.mkdtemp(prefix="fxsay_"))
    try:
        r = media.speak(b.text[:1500], d / "say", b.voice, b.lang)
    except Exception as exc:
        log.warning("speak failed: %s", exc)
        raise
    p = Path(r["path"])
    if p.suffix.lower() != ".wav":
        return {"local": False}
    log.info("speak: voice file ready (%d bytes), will play on this PC", p.stat().st_size)
    sid = secrets.token_urlsafe(8)
    stale = []
    with _say_lock:
        _say_ready[sid] = (p, d)
        while len(_say_ready) > 20:             # prepared but never played (stopped): tidy the oldest
            stale.append(_say_ready.pop(next(iter(_say_ready))))
    import shutil as _sh
    for _p, _d in stale:
        _sh.rmtree(_d, ignore_errors=True)
    return {"local": True, "id": sid}


_say_proc = None


@_post("/api/ai/speak_play")
def ai_speak_play(b: dict, request: Request):
    """Plays a prepared voice file on this PC's speakers and returns when it has finished (or was stopped).
    It is played by a small hidden PowerShell (System.Media.SoundPlayer): the same way Windows' own test plays it."""
    global _say_proc
    import shutil as _sh
    import subprocess
    sid = str(b.get("id") or "")
    with _say_lock:
        item = _say_ready.pop(sid, None)
    log.info("speak: play requested (prepared file %s)", "found" if item else "NOT found")
    if not item or not _local_speakers_ok(request):
        return {"played": False}
    p, d = item
    try:
        t0 = time.time()
        flags = 0x08000000 if sys.platform.startswith("win") else 0
        proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", "(New-Object System.Media.SoundPlayer $env:FX_WAV).PlaySync()"],
                                env=dict(os.environ, FX_WAV=str(p)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                creationflags=flags)
        _say_proc = proc
        out, err = proc.communicate(timeout=600)
        log.info("speak: played on this PC's speakers in %.1f s (exit code %s) %s", time.time() - t0, proc.returncode, (err or b"")[:200].decode("utf-8", "replace"))
        return {"played": proc.returncode == 0 or proc.returncode is None}
    except Exception as exc:
        log.warning("playing the voice failed: %s", exc)
        return {"played": False}
    finally:
        _say_proc = None
        _sh.rmtree(d, ignore_errors=True)


@_post("/api/ai/speak_stop")
def ai_speak_stop():
    """Silences the voice that is playing on this PC's speakers."""
    proc = _say_proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
    return {"ok": True}


# ---------------------------------------------------------------- server mode: browse, upload and download from another device
@app.get("/api/info", dependencies=[Depends(guard)])
def app_info():
    import platform
    return {"version": VERSION, "serve": SERVE, "os": platform.system().lower(), "home": str(Path.home()),
            "folder": "" if SERVE else str(Path(__file__).resolve().parent.parent),
            "shell_ok": (not SERVE) or os.environ.get("FATHOM_ALLOW_SHELL") == "1"}


def _fs_roots() -> list[dict]:
    env = [r.strip() for r in os.environ.get("FATHOM_ROOTS", "").split(os.pathsep if os.name != "nt" else ";") if r.strip()]
    roots: list[dict] = []
    if env:
        roots = [{"name": Path(r).name or r, "path": r} for r in env if Path(r).exists()]
    else:
        roots.append({"name": "Home", "path": str(Path.home())})
        if os.name == "nt":
            import string
            roots += [{"name": f"{c}:", "path": f"{c}:\\"} for c in string.ascii_uppercase if Path(f"{c}:\\").exists()]
        else:
            for extra in ("/data", "/mnt", "/media", "/Volumes", "/"):
                if Path(extra).exists():
                    roots.append({"name": extra, "path": extra})
    return roots


def _fs_allowed(p: Path) -> bool:
    env = [r for r in os.environ.get("FATHOM_ROOTS", "").split(os.pathsep if os.name != "nt" else ";") if r.strip()]
    if not env:
        return True
    rp = p.resolve()
    return any(str(rp).startswith(str(Path(r).resolve())) for r in env)


class FsList(BaseModel):
    path: str = ""
    show_hidden: bool = False


@_post("/api/fs/list")
def fs_list(b: FsList):
    roots = _fs_roots()
    if not b.path.strip():
        return {"path": "", "parent": "", "roots": roots, "entries": [{"name": r["name"], "path": r["path"], "dir": True, "size": 0, "mtime": 0} for r in roots]}
    p = Path(os.path.expanduser(b.path))
    if not p.exists() or not p.is_dir():
        raise service.UserError("That folder does not exist.")
    if not _fs_allowed(p):
        raise service.UserError("That folder is outside the places this Fathom may show.")
    entries = []
    try:
        for e in os.scandir(p):
            if not b.show_hidden and e.name.startswith("."):
                continue
            try:
                st = e.stat()
                entries.append({"name": e.name, "path": str(Path(e.path)), "dir": e.is_dir(), "size": 0 if e.is_dir() else st.st_size, "mtime": st.st_mtime})
            except OSError:
                continue
            if len(entries) >= 4000:
                break
    except PermissionError:
        raise service.UserError("Fathom is not allowed to open that folder.")
    entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    parent = str(p.parent) if p.parent != p else ""
    return {"path": str(p), "parent": parent, "roots": roots, "entries": entries}


class FsChunk(BaseModel):
    id: str
    name: str
    index: int = 0
    last: bool = False
    data: str


@_post("/api/fs/upload")
def fs_upload(b: FsChunk):
    """A file from the device you are using, sent in pieces. The finished file lands in Fathom's uploads folder and its path is returned."""
    import base64
    import re as _re
    from app.paths import data_root
    safe_id = _re.sub(r"[^A-Za-z0-9_-]", "", b.id)[:40] or "x"
    name = _re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", b.name)[:120] or "upload"
    d = data_root() / "uploads" / time.strftime("%Y%m%d")
    d.mkdir(parents=True, exist_ok=True)
    part = d / f"{safe_id}.part"
    if b.index == 0 and part.exists():
        part.unlink()
    with part.open("ab") as fh:
        fh.write(base64.b64decode(b.data.split(",", 1)[-1]))
    if not b.last:
        return {"ok": True}
    final = d / name
    n = 2
    while final.exists():
        final = d / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    part.replace(final)
    return {"path": str(final), "name": final.name, "bytes": final.stat().st_size}


@app.get("/api/fs/download")
def fs_download(path: str, t: str = ""):
    if not NO_TOKEN and not _same(t, TOKEN):
        raise HTTPException(403)
    p = Path(path)
    if not p.is_file() or not _fs_allowed(p):
        raise HTTPException(404)
    from urllib.parse import quote
    return FileResponse(p, headers={"Cache-Control": "no-store", "Content-Disposition": "attachment; filename*=UTF-8''" + quote(p.name)})
