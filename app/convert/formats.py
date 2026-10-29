# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Every file format Fathom knows by name, and how to recognise a file's real format.

A format id is the lower-case extension without the dot ("jpg", "tar.gz"). Several extensions can share
one id (jpeg -> jpg). Anything that is plain text but has an unknown extension is treated as "txt"."""
from __future__ import annotations

from pathlib import Path

# id | name | category
_TABLE = """
png|PNG image|image
jpg|JPEG image|image
gif|GIF image|image
bmp|BMP bitmap|image
tif|TIFF image|image
webp|WebP image|image
ico|Windows icon|image
icns|macOS icon|image
tga|TGA (Targa) image|image
ppm|PPM image|image
pgm|PGM image|image
pbm|PBM image|image
pcx|PCX image|image
sgi|SGI image|image
dds|DDS texture|image
psd|Photoshop (PSD)|image
heic|HEIC photo (iPhone)|image
avif|AVIF image|image
jp2|JPEG 2000|image
jxl|JPEG XL|image
svg|SVG vector image|image
eps|EPS image|image
emf|EMF image|image
wmf|WMF image|image
xbm|XBM image|image
cur|Windows cursor|image
fits|FITS image|image
mpo|MPO photo|image
raw|Camera RAW photo|image
apng|Animated PNG|image
mp4|MP4 video|video
mkv|MKV video|video
webm|WebM video|video
avi|AVI video|video
mov|QuickTime video (MOV)|video
flv|Flash video (FLV)|video
wmv|Windows Media video|video
mpg|MPEG video|video
ts|MPEG transport stream|video
m2ts|Blu-ray video (M2TS)|video
vob|DVD video (VOB)|video
ogv|Ogg video|video
3gp|3GP phone video|video
3g2|3G2 phone video|video
m4v|M4V video|video
asf|ASF video|video
divx|DivX video|video
f4v|F4V video|video
rm|RealMedia video|video
rmvb|RealMedia VB video|video
mxf|MXF video|video
swf|Flash animation (SWF)|video
mp3|MP3 audio|audio
wav|WAV audio|audio
flac|FLAC audio|audio
ogg|Ogg Vorbis audio|audio
opus|Opus audio|audio
m4a|M4A audio|audio
aac|AAC audio|audio
wma|Windows Media audio|audio
aiff|AIFF audio|audio
ac3|AC3 audio|audio
amr|AMR audio|audio
mka|Matroska audio|audio
mp2|MP2 audio|audio
au|AU audio|audio
caf|CAF audio|audio
ape|Monkey's Audio|audio
wv|WavPack audio|audio
tta|TTA audio|audio
dts|DTS audio|audio
ra|RealAudio|audio
pdf|PDF document|document
docx|Word document|document
doc|Word 97-2003 document|document
odt|OpenDocument text|document
rtf|Rich text (RTF)|document
wpd|WordPerfect document|document
wps|Microsoft Works document|document
dotx|Word template|document
dot|Word 97-2003 template|document
ott|OpenDocument text template|document
sxw|OpenOffice Writer (old)|document
abw|AbiWord document|document
pages|Apple Pages|document
xps|XPS document|document
vsdx|Visio drawing|document
vsd|Visio 97-2003 drawing|document
pub|Publisher document|document
cdr|CorelDRAW drawing|document
odg|OpenDocument drawing|document
pptx|PowerPoint presentation|presentation
ppt|PowerPoint 97-2003|presentation
ppsx|PowerPoint show|presentation
pps|PowerPoint 97-2003 show|presentation
odp|OpenDocument presentation|presentation
potx|PowerPoint template|presentation
sxi|OpenOffice Impress (old)|presentation
key|Apple Keynote|presentation
xlsx|Excel workbook|spreadsheet
xls|Excel 97-2003 workbook|spreadsheet
xlsm|Excel macro workbook|spreadsheet
ods|OpenDocument spreadsheet|spreadsheet
xltx|Excel template|spreadsheet
sxc|OpenOffice Calc (old)|spreadsheet
numbers|Apple Numbers|spreadsheet
dbf|dBase table|spreadsheet
dif|DIF spreadsheet|spreadsheet
slk|SYLK spreadsheet|spreadsheet
csv|CSV table|data
tsv|TSV table|data
json|JSON|data
jsonl|JSON Lines|data
xml|XML|data
yaml|YAML|data
toml|TOML|data
sql|SQL script|data
ini|INI settings|data
ipynb|Jupyter notebook|data
txt|Plain text|text
md|Markdown|text
html|HTML web page|text
rst|reStructuredText|text
tex|LaTeX|text
org|Org-mode|text
textile|Textile|text
wiki|MediaWiki|text
docbook|DocBook|text
asciidoc|AsciiDoc|text
fb2|FictionBook (FB2)|ebook
epub|EPUB e-book|ebook
mobi|Kindle MOBI|ebook
azw3|Kindle AZW3|ebook
azw|Kindle AZW|ebook
lit|Microsoft Reader (LIT)|ebook
lrf|Sony LRF|ebook
pdb|Palm PDB e-book|ebook
djvu|DjVu document|ebook
cbz|Comic book (CBZ)|ebook
cbr|Comic book (CBR)|ebook
htmlz|Zipped HTML|ebook
txtz|Zipped text|ebook
zip|ZIP archive|archive
7z|7-Zip archive|archive
tar|TAR archive|archive
tar.gz|TAR.GZ archive|archive
tar.bz2|TAR.BZ2 archive|archive
tar.xz|TAR.XZ archive|archive
gz|GZ compressed file|archive
bz2|BZ2 compressed file|archive
xz|XZ compressed file|archive
rar|RAR archive|archive
cab|CAB archive|archive
iso|ISO disc image|archive
cpio|CPIO archive|archive
lzh|LZH archive|archive
deb|DEB package|archive
rpm|RPM package|archive
jar|JAR archive|archive
b64|Base64 text|archive
hex|Hex dump text|archive
folder|Folder of files|archive
ttf|TrueType font|font
otf|OpenType font|font
woff|WOFF web font|font
woff2|WOFF2 web font|font
srt|SRT subtitles|subtitle
vtt|WebVTT subtitles|subtitle
ass|ASS subtitles|subtitle
ssa|SSA subtitles|subtitle
sub|MicroDVD subtitles|subtitle
stl|STL 3D model|mesh
obj|OBJ 3D model|mesh
ply|PLY 3D model|mesh
off|OFF 3D model|mesh
glb|GLB 3D model|mesh
gltf|glTF 3D model|mesh
3mf|3MF 3D model|mesh
dae|Collada 3D model|mesh
qoi|QOI image|image
sun|Sun raster image|image
dcx|DCX image|image
xpm|XPM image|image
msp|MSP bitmap|image
pcd|Kodak Photo CD (PCD)|image
fli|FLI animation|image
blp|BLP texture|image
im|IFUNC image|image
ogm|OGM video|video
wtv|Windows TV recording (WTV)|video
dv|DV video|video
nut|NUT video|video
ivf|IVF video|video
y4m|Y4M raw video|video
h264|Raw H.264 video|video
hevc|Raw H.265 (HEVC) video|video
amv|AMV video|video
bik|Bink video|video
smk|Smacker video|video
mpc|Musepack audio|audio
w64|Sony Wave64 audio|audio
voc|Creative VOC audio|audio
mp1|MP1 audio|audio
eac3|Dolby Digital Plus (E-AC3)|audio
thd|Dolby TrueHD audio|audio
dsf|DSD audio (DSF)|audio
dff|DSD audio (DFF)|audio
gsm|GSM audio|audio
ircam|IRCAM audio|audio
tak|TAK audio|audio
oma|Sony OMA audio|audio
sdw|StarWriter document|document
stw|StarOffice template|document
hwp|Hangul (HWP) document|document
lwp|Lotus Word Pro|document
t602|T602 document|document
mw|MacWrite document|document
zabw|AbiWord (compressed)|document
uot|Uniform Office text|document
sdc|StarCalc spreadsheet|spreadsheet
stc|StarCalc template|spreadsheet
lotus123|Lotus 1-2-3 spreadsheet|spreadsheet
wk1|Lotus 1-2-3 (WK1)|spreadsheet
wks|Lotus 1-2-3 (WKS)|spreadsheet
qpw|Quattro Pro spreadsheet|spreadsheet
wb2|Quattro Pro (WB2)|spreadsheet
xlsb|Excel binary workbook|spreadsheet
uos|Uniform Office spreadsheet|spreadsheet
sdd|StarImpress presentation|presentation
sti|StarImpress template|presentation
uop|Uniform Office presentation|presentation
pot|PowerPoint 97-2003 template|presentation
vdx|Visio XML drawing|document
wpg|WordPerfect graphic|document
cmx|Corel CMX graphic|document
pmd|PageMaker document|document
qxp|QuarkXPress document|document
zmf|Zoner Callisto drawing|document
dxf|AutoCAD DXF drawing|document
cgm|CGM vector graphic|document
svm|StarView metafile|document
fh|FreeHand drawing|document
chm|Compiled HTML help (CHM)|ebook
fbz|Zipped FictionBook (FBZ)|ebook
pml|Palm Markup (PML) e-book|ebook
rb|Rocket eBook|ebook
snb|Shanda Bambook (SNB)|ebook
tcr|Psion TCR e-book|ebook
arj|ARJ archive|archive
z|Unix compress (Z)|archive
lzma|LZMA compressed file|archive
zst|Zstandard compressed file|archive
wim|Windows image (WIM)|archive
dmg|Apple disk image (DMG)|archive
msi|Windows installer (MSI)|archive
xar|XAR archive|archive
bin|Other file|other
"""

FORMATS: dict[str, tuple[str, str]] = {}
for _line in _TABLE.strip().splitlines():
    _id, _name, _cat = _line.split("|")
    FORMATS[_id] = (_name, _cat)

# extension -> format id, when they differ
ALIASES = {
    "ras": "sun", "flc": "fli", "264": "h264", "h265": "hevc", "265": "hevc", "mod": "mpg", "tod": "mpg", "vro": "vob", "evo": "vob",
    "3gpp": "3gp", "m4b": "m4a", "m4r": "m4a", "weba": "webm", "adts": "aac", "snd": "au", "mjpg": "avi", "602": "t602",
    "123": "lotus123", "wk3": "wk1", "wk4": "wk1", "wq1": "qpw", "wb1": "wb2", "wb3": "wb2", "uop": "uop", "pm6": "pmd", "p65": "pmd", "pm": "pmd",
    "fh11": "fh", "fh10": "fh", "fh9": "fh", "fh8": "fh", "fh7": "fh", "mcw": "mw", "sdw": "sdw", "vdw": "vdx", "vsx": "vsdx", "vtx": "vsdx",
    "ots": "xltx", "stw": "stw", "tgz": "tar.gz", "lzma": "lzma", "taz": "tar.gz",
    "jpeg": "jpg", "jpe": "jpg", "jfif": "jpg", "tiff": "tif", "heif": "heic", "htm": "html", "xhtml": "html",
    "markdown": "md", "mdown": "md", "yml": "yaml", "mpeg": "mpg", "mpe": "mpg", "mts": "m2ts", "aif": "aiff",
    "aifc": "aiff", "oga": "ogg", "tgz": "tar.gz", "tbz2": "tar.bz2", "tbz": "tar.bz2", "txz": "tar.xz",
    "dib": "bmp", "j2k": "jp2", "jpx": "jp2", "rgb": "sgi", "bw": "sgi", "pnm": "ppm", "ndjson": "jsonl",
    "text": "txt", "latex": "tex", "wiki": "wiki", "mediawiki": "wiki", "adoc": "asciidoc", "dotm": "dotx",
    "docm": "docx", "pptm": "pptx", "potm": "potx", "ppsm": "ppsx", "xltm": "xltx", "ott": "ott", "fodt": "odt",
    "fods": "ods", "fodp": "odp", "war": "jar", "apk": "jar", "ear": "zip", "whl": "zip", "nupkg": "zip",
    "vsdm": "vsdx", "oxps": "xps", "mp4v": "mp4", "qt": "mov", "mka": "mka", "opus": "opus", "spx": "ogg",
    "cr2": "raw", "cr3": "raw", "nef": "raw", "arw": "raw", "dng": "raw", "orf": "raw", "rw2": "raw", "raf": "raw",
    "pef": "raw", "srw": "raw", "x3f": "raw", "3fr": "raw", "kdc": "raw", "mrw": "raw", "erf": "raw",
    "lha": "lzh", "docbook": "docbook", "sxd": "odg", "sxg": "odt",
    "svgz": "svg", "mobi": "mobi", "prc": "mobi", "azw4": "azw3", "kfx": "azw3", "ods": "ods", "ots": "xltx",
    "otp": "potx", "xlt": "xltx", "xlw": "xls", "wpt": "wpd", "m2v": "mpg", "m2p": "mpg", "ps": "eps", "ai": "eps",
    "tpl": "txt", "markdown": "md", "mkd": "md", "rest": "rst", "jsonc": "json", "geojson": "json", "gpx": "xml",
    "kml": "xml", "xsl": "xml", "xslt": "xml", "xsd": "xml", "rss": "xml", "atom": "xml", "plist": "xml",
    "csproj": "xml", "resx": "xml", "config": "xml", "csv.txt": "csv",
}

# plain-text-like extensions that are simply "text" to a converter (source code, logs, settings, ...)
TEXT_LIKE = {
    "css", "js", "mjs", "cjs", "ts", "tsx", "jsx", "py", "pyw", "rs", "go", "java", "c", "cpp", "cc", "cxx", "h", "hpp",
    "cs", "php", "rb", "sh", "bash", "zsh", "bat", "cmd", "ps1", "log", "cfg", "conf", "env", "eml", "lua", "kt", "swift",
    "r", "m", "vue", "gradle", "properties", "pl", "pm", "scala", "dart", "jl", "hs", "ex", "exs", "erl", "clj", "lisp",
    "vb", "vbs", "asm", "s", "makefile", "mk", "cmake", "dockerfile", "gitignore", "lock", "diff", "patch", "tpl", "nfo",
    "readme", "license", "tsv.txt", "pro", "sln", "bib", "cls", "sty", "ahk", "au3", "nim", "zig", "v", "sv", "vhd",
    "pas", "f90", "f", "for", "cob", "tcl", "awk", "sed", "reg", "inf", "url", "desktop", "service", "toml.txt",
}


def ext_of(name: str | Path) -> str:
    """Lower-case extension id of a file name ('tar.gz' for archive.tar.gz, '' for none)."""
    n = Path(name).name.lower()
    for compound in ("tar.gz", "tar.bz2", "tar.xz", "csv.txt"):
        if n.endswith("." + compound):
            return compound
    return n.rsplit(".", 1)[1] if "." in n.strip(".") else ""


def known_fmt(ext: str) -> str | None:
    ext = ext.lower().lstrip(".")
    ext = ALIASES.get(ext, ext)
    if ext in FORMATS and ext not in ("folder", "bin", "b64", "hex"):
        return ext
    if ext in TEXT_LIKE:
        return "txt"
    return None


# ---------------------------------------------------------------- recognising a file by its content
_SIGS: list[tuple[int, bytes, str]] = [
    (0, b"%PDF-", "pdf"), (0, b"\x89PNG\r\n\x1a\n", "png"), (0, b"\xff\xd8\xff", "jpg"), (0, b"GIF87a", "gif"), (0, b"GIF89a", "gif"),
    (0, b"BM", "bmp"), (0, b"II*\x00", "tif"), (0, b"MM\x00*", "tif"), (0, b"8BPS", "psd"), (0, b"\x00\x00\x01\x00", "ico"),
    (0, b"icns", "icns"), (0, b"DDS ", "dds"), (0, b"\x0a\x05\x01", "pcx"), (0, b"\x01\xda", "sgi"), (0, b"P6", "ppm"), (0, b"P5", "pgm"), (0, b"P4", "pbm"),
    (0, b"\x00\x00\x00\x0cjP  ", "jp2"), (0, b"\xff\x0a", "jxl"), (0, b"\x00\x00\x00\x0cJXL ", "jxl"), (0, b"SIMPLE  =", "fits"),
    (0, b"%!PS", "eps"), (0, b"\xc5\xd0\xd3\xc6", "eps"),
    (0, b"\x1aE\xdf\xa3", "mkv"), (0, b"OggS", "ogg"), (0, b"fLaC", "flac"), (0, b"ID3", "mp3"), (0, b"\xff\xfb", "mp3"), (0, b"\xff\xf3", "mp3"),
    (0, b"\xff\xf1", "aac"), (0, b"\xff\xf9", "aac"), (0, b"FLV\x01", "flv"), (0, b"\x30\x26\xb2\x75\x8e\x66\xcf\x11", "wmv"),
    (0, b"\x00\x00\x01\xba", "mpg"), (0, b"\x00\x00\x01\xb3", "mpg"), (0, b".RMF", "rm"), (0, b"FORM", "aiff"), (0, b"#!AMR", "amr"),
    (0, b"MThd", "bin"), (0, b"\x0b\x77", "ac3"), (0, b"MAC ", "ape"), (0, b"wvpk", "wv"), (0, b"TTA1", "tta"), (0, b"CAFF", "caf"), (0, b".snd", "au"),
    (0, b"PK\x03\x04", "zip"), (0, b"Rar!\x1a\x07", "rar"), (0, b"7z\xbc\xaf\x27\x1c", "7z"), (0, b"\x1f\x8b", "gz"), (0, b"BZh", "bz2"),
    (0, b"\xfd7zXZ\x00", "xz"), (0, b"MSCF", "cab"), (0, b"\xed\xab\xee\xdb", "rpm"), (257, b"ustar", "tar"), (0, b"!<arch>", "deb"),
    (0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "doc"), (0, b"{\\rtf", "rtf"), (0, b"\x00\x01\x00\x00\x00", "ttf"), (0, b"true", "ttf"),
    (0, b"OTTO", "otf"), (0, b"wOFF", "woff"), (0, b"wOF2", "woff2"), (0, b"glTF", "glb"), (0, b"solid ", "stl"),
    (0, b"SQLite format 3\x00", "bin"), (0, b"MZ", "bin"), (0, b"\x7fELF", "bin"), (0, b"AT&TFORM", "djvu"), (0, b"\xca\xfe\xba\xbe", "bin"),
]


def _head(path: Path, n: int = 4096) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def sniff(path: Path) -> str:
    """The real format id of a file from its first bytes ('' when it is unknown)."""
    head = _head(path, 600)
    if not head:
        return ""
    if head[:4] == b"RIFF":
        return {"WEBP": "webp", "AVI ": "avi", "WAVE": "wav"}.get(head[8:12].decode("latin1"), "")
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            return "m4a"
        if brand in (b"qt  ",):
            return "mov"
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "heic"
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand[:2] == b"3g":
            return "3gp"
        if brand == b"M4V ":
            return "m4v"
        return "mp4"
    if head[:6] == b"{\\rtf1"[:6]:
        return "rtf"
    if head.startswith(b"PK\x03\x04"):
        return _sniff_zip(path)
    for off, sig, fmt in _SIGS:
        if head[off:off + len(sig)] == sig:
            if fmt == "bin":
                return ""
            return fmt
    if len(head) > 376 and head[0] == 0x47 and head[188] == 0x47:
        return "ts"
    return ""


def _sniff_zip(path: Path) -> str:
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if "mimetype" in names:
                mime = zf.read("mimetype")[:80].decode("latin1")
                for key, fmt in (("epub", "epub"), ("opendocument.text", "odt"), ("opendocument.spreadsheet", "ods"),
                                 ("opendocument.presentation", "odp"), ("opendocument.graphics", "odg")):
                    if key in mime:
                        return fmt
            if any(n.startswith("word/") for n in names):
                return "docx"
            if any(n.startswith("ppt/") for n in names):
                return "pptx"
            if any(n.startswith("xl/") for n in names):
                return "xlsx"
            if "META-INF/MANIFEST.MF" in names:
                return "jar"
    except Exception:
        pass
    return "zip"


def looks_text(head: bytes) -> bool:
    from app.extract import looks_text as lt

    return lt(head)


def detect(path: Path) -> str:
    """Format id of a file: by extension when it is a known one, otherwise by content ('txt' or 'bin' last)."""
    ext = ext_of(path)
    fmt = known_fmt(ext)
    if fmt == "ts":  # .ts is both MPEG video and TypeScript
        head = _head(path, 377)
        return "ts" if len(head) > 376 and head[0] == 0x47 and head[188] == 0x47 else "txt"
    if fmt == "sub":  # .sub is MicroDVD subtitles or VobSub binary
        return "sub" if looks_text(_head(path)) else "bin"
    if fmt:
        return fmt
    real = sniff(path)
    if real:
        return real
    head = _head(path)
    if not head or looks_text(head):
        return "txt"
    return "bin"


def category(fmt: str) -> str:
    return FORMATS.get(fmt, ("", "other"))[1]


def label(fmt: str) -> str:
    return FORMATS.get(fmt, (fmt.upper() + " file", "other"))[0]
