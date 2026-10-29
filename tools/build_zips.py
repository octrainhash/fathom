"""Builds fathom.zip (the one download; the setup window offers Full or Lite) from this folder.
Usage: python tools/build_zips.py [output_dir]"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent
SKIP_DIRS = {"__pycache__", ".git", ".github", "node_modules"}


def files():
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_file() and not (set(rel.parts) & SKIP_DIRS) and p.suffix != ".pyc":
            yield p, rel


def build(name: str, lite: bool) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / name
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p, rel in files():
            z.write(p, "fathom/" + rel.as_posix())
        if lite:
            z.writestr("fathom/LITE", "")
    return target


if __name__ == "__main__":
    for n, l in (("fathom.zip", False),):
        t = build(n, l)
        print(t, t.stat().st_size)
