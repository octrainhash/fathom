# Fathom

*Created by The Fathomist.*

**Website and downloads: https://fathomfile.pages.dev** · License: AGPL-3.0-or-later · Questions: buzznomore401@gmail.com

One Windows app for files: find things inside anything, convert any file to any other supported type, shrink or enlarge files, a big toolbox, a forensics lab, network sync and a drives manager. Every option has a hover tip in plain words.

## Install
**Which system?** Windows: use `Fathom.bat` (below). **macOS:** double-click `Fathom.command`. **Linux / Raspberry Pi / WSL:** run `./fathom.sh`. **Phone, tablet, Chromebook, iPad:** run Fathom in server mode on a computer or Docker (see *Any device* below) and open its link in the device's browser. Docker: `docker compose up -d`.

### Windows
1. Extract the zip anywhere (right-click > Extract All).
2. **Setup wizard (you choose where everything goes):** double-click **`Fathom-Setup.vbs`**. A window with pages asks what to install (LibreOffice, Calibre, 7-Zip, the free local assistant) and **which folder or drive** gets the Fathom app, its data, and each program. If nothing happens, open a Command Prompt in the folder and run `Fathom.bat setup` (same wizard).
3. **Direct way (no questions):** right-click **Fathom.bat** > **Run as administrator**. It downloads and sets up everything where you extracted it (Python packages, FFmpeg, LibreOffice, Calibre, 7-Zip, speech and vision models) and starts the app. Next time use the **Fathom** shortcut it makes. `Fathom.bat lite` skips the big programs.
4. Logs: `%LOCALAPPDATA%\Fathom\setup.log`, `bat.log`, `launch.log`, `server.log`. Send `setup.log` if something fails.
5. Something wrong? Double-click a script in the `support` folder (see `support\README-SUPPORT.txt`) or `Fix-Ollama.cmd`.

## Any device, any system
* **macOS / Linux**: `Fathom.command` (macOS) or `./fathom.sh` (Linux and macOS). The first run finds Python 3.12 or fetches it with `uv`, creates a private environment in `~/.fathom`, installs everything, and opens Fathom (in its own window if the system's window libraries are present, otherwise in your browser). On Linux it also adds a menu entry. Windows-only tools (WIA/TWAIN scanners, NTFS/ReFS drive tools, hidden NTFS streams) are not available there; the rest is.
* **Match a picture / video links:** in Find, "Match a picture" takes reference pictures and finds that person or thing in files and videos; "Add link…" fetches a video from a web link (YouTube-style pages need `yt-dlp`, installed with the optional packages).
* **Server mode** (phones, tablets, other computers): `./fathom.sh --serve` (Windows: `Fathom.bat serve`; or `python launch.py --serve`). It prints a private link ending in `?token=…`; open it on any device on your network. Add `--https` for a self-made certificate (browsers only allow the microphone on https), `--port 9000` to change the port, `--host 127.0.0.1` to stay local. The key is kept in `~/.fathom/serve-token.txt` (or set `FATHOM_TOKEN`) so the link stays the same. In this mode *Add files* browses the folders of the computer running Fathom and **Upload from this device** sends files from your phone; *Show/Open* downloads the file. The assistant cannot run shell commands or Python unless you start with `FATHOM_ALLOW_SHELL=1`. `FATHOM_ROOTS=/path1:/path2` limits which folders can be browsed.
* **Docker**: `docker compose up -d`, then `docker compose logs fathom` for the link. Put your files in `./files` (shown as `/data`). Add `--build-arg WITH_OFFICE=1` to the build for LibreOffice. Safe default: only reachable from the same machine; to reach it from a phone change the port line in `docker-compose.yml`, and put it behind a VPN (Tailscale) or HTTPS.
* **Away from home**: do not forward a router port. Use Tailscale or a Cloudflare Tunnel with access control.
* The page can be added to a phone's home screen like an app (it has a web-app manifest).
* Not tested here: real macOS, real Linux desktops, Raspberry Pi, Docker builds (the sandbox had no Docker), phones. The server-mode security rules, folder browser, uploads and downloads were tested with a phone-sized browser.

## The tool bar (top)
| Group | Tools |
|---|---|
| **Assistant** | **Assistant** (chat that sees your open tab and files, and can read, make and change files), **Settings** (which AI, key, approval mode, folder for its work, image/voice services, handwriting reader, what it remembers) |
| Search | Find (words, numbers, objects, **handwriting**; clips with a held, circled still), **Read handwriting** (pages and photos to typed text, with proof pictures), Data finder (emails, keys, cards…) |
| Convert | Convert (search + dropdown of every file type; change a video's container, such as MP4 to MKV, without re-encoding when the format allows, which is very fast; plus volume, loudness, fades, bass and treble, speed, cut a part, turn and mirror, light and colour, clean-up, encoding speed, graphics-card encoding and picture adjustments, even from one type to the same type), Encodings (text encodings, Base64, Hex…) |
| Size | Smaller / bigger (zero or random fill), Pack (ZIP, 7z, TAR, SFX .exe, passwords, parts) |
| Edit | **Editor** (open any file and change what is inside: text and code, Word/PowerPoint/OpenDocument paragraphs, Excel cells, database rows, PDF text, pictures with draw/write/box/blur/crop; also reachable from the ✏️ button beside every file you add), **Find & replace** (Word, Excel, PowerPoint, OpenDocument, e-books, HTML/XML, text in any encoding, PDF, SQLite databases, old Office files, pictures, even raw bytes), **Stamp** (ready-made, own words, own picture, watermarks, page numbers), **Sign** (draw, type, or clean up a photo of your signature), Merge, Split, Join parts, Cut, Rotate/flip, PDF pages, Pictures out, Scan pages, **Print** (digital to paper), **Photocopy** (paper to paper: scan then print), QR codes (make and read), Touch up pictures, Import from scanner (WIA, TWAIN and SANE drivers; see the scanner notes below) |
| Protect | **Redact** (permanently black out emails, phone numbers, card numbers or your own words), Lock (AES-256 / ChaCha20), PDF password, Shredder (NIST, DoD, VSITR, HMG, Gutmann), Checksums, Hidden details, Photo details, Dates, Permissions |
| Tidy | Duplicates, Inspect, Rename, Organise, Empty folders (with Undo), **Compare** (files: changed lines, changed pixels, first differing byte; folders: what is missing or different) |
| **Lab** | Hex view and patch (on a copy), Hidden NTFS streams, Hidden items (attrib / chflags / dotfiles), Recover deleted (signature carving from drives and images), Hidden data in pictures and sound (LSB and appended data, AES-packed), Disk images (VHD, VHDX, VMDK, VDI, QCOW2, SquashFS, ISO, Docker layers), Junk cleaner, Drive to image (read-only copy with SHA-256), Repair files (PNG, JPEG, GIF, ZIP/Office, PDF), Damage copies (broken test copies, never the original), Linux formats (ext4/Btrfs/XFS/F2FS/ZFS where the system can make them) |
| **Sync** | SFTP, FTP/FTPS, WebDAV, S3, Azure Blob, SMB, NFS, Android (ADB), MTP, Google Drive and others (via rclone); multi-threaded, optional encryption before upload |
| **Torrent** | Downloads (BitTorrent client with magnet links and .torrent files, per-file choice, speed limits, resumes after restart), Make a torrent, Torrent info, Download links (http/https/ftp) |
| **My tools** | Tools the assistant wrote for you. Ask it "make me a tool that…" and it appears here next to the built-in ones |
| Drives | Overview (NTFS, exFAT, FAT32, ReFS, APFS/HFS+/ext detection; check, repair, optimise, format, convert to NTFS), Space map, Will it fit?, Speed up, Which format? |

## Notes on the Lab and Sync modules
* They are plain FastAPI endpoints (`/api/lab/*`) in `app/forensics.py`, `app/vmimage.py`, `app/junk.py`, `app/netsync.py`, with screens in `static/lab.js`. The UI is the existing plain-JavaScript shell (no React), so everything plugs into the same tool bar.
* Carving reads drives read-only and needs administrator rights for `E:`; always save recovered files on a different drive.
* Disk images and ISO need 7-Zip (installed by setup). Docker images are read natively (`docker save` tar files).
* Sync extras: `pip install paramiko boto3 azure-storage-blob`; Google Drive needs rclone. Passwords are never stored.
* Not possible in this app: raw disk cloning, fake or forged metadata, formatting ZFS/Btrfs/ext on Windows.

## Find & replace, Stamp, Sign, Print, Torrent: what to know
* **Find & replace** never touches the original unless you tick "Replace the original" (it then goes to the Recycle Bin). It edits inside Word, Excel, PowerPoint, OpenDocument, EPUB, web pages, text and code (keeping the file's encoding and line endings), PDF (the text is rubbed out and typed again in a matching standard font, so exotic PDF fonts can look slightly different), SQLite databases, pictures (found with OCR, painted over and re-typed; best effort) and old Office files (converted with LibreOffice, edited, converted back). "Preview matches" shows counts and examples first.
* **Stamp / Sign** put a *picture* of a stamp or signature on PDFs and pictures (Word/Excel/PowerPoint are turned into a PDF first). This is the same as signing a printout; it is not a cryptographic certificate signature.
* **Print / Photocopy**: Windows draws pictures straight to the printer (pywin32) and hands every other file to the program Windows uses for it; macOS/Linux use CUPS (`lp`). Photocopy scans with the chosen scanner and prints the result.
* **Torrent**: Fathom is a plain BitTorrent client (libtorrent) with no search for content. Only download and share what you have the right to. Making and reading .torrent files works without libtorrent.
* Tested here: replace (Word/Excel/PowerPoint/ODF/HTML/text/SQLite/binary), stamping and signing (PDFs incl. rotated pages, pictures), printing against a simulated CUPS, torrent creation and reading, QR, compare, hex, touch-up, all screens in a browser. **Not tested here** (needs Windows, hardware, keys or optional packages): PDF replace/redact (PyMuPDF), the Windows printing path, real scanners, libtorrent downloads, LibreOffice round trips, real AI model calls, microphone and Windows speech output, live screen capture on Windows (tested under a virtual screen), the move-to-D script, image-generation services, the offline handwriting reader, and the installer itself.

## Proof pictures (what changed, shown)

Whenever Fathom changes or adds something it also makes **proof pictures**: a BEFORE and an AFTER image where the changed part is highlighted in yellow and circled in red, the same marking the Find tool uses. Look for **Show proof** on a finished row (or the "Proof of what changed" panel); click any picture to enlarge it (arrow keys move between changes, Space flips Before/After, + and - zoom).

- Find & replace and Redact: the lines/pages/cells with the changed words marked, also in the preview before anything is changed.
- Stamp and Sign: the page or picture before, and after with the stamp circled.
- Editor: every changed paragraph, spreadsheet cell, database row, PDF text or picture region after you press Save.
- Touch up, Hex patch, Rotate, Resize, Clean pages, Repair, Photo details, Hidden details, Dates, Permissions.
- Big jobs show the first few changes (Fathom says how many more there are) so the screen stays fast. The pictures live with the other saved results and are removed by "Saved results".
- PDF page pictures need PyMuPDF (installed by Fathom.bat); without it Fathom draws text cards instead.

## Scanners (WIA, TWAIN, SANE)
* `app/scanner.py` lists every scanner it can reach and runs the scan. WIA uses Windows' own scanning service (needs `pywin32`).
* `app/twain.py` is a TWAIN client written from the TWAIN 2.x specification with ctypes (Windows; needs `twaindsm.dll`, which scanner driver packages install). It supports the maker's own scan window and feeders.
* `app/sane.py` is a SANE client written from the SANE standard: the network protocol in plain Python (talks to `saned` on port 6566, so Windows can use a scanner on a Linux box or Raspberry Pi) and local `libsane` through ctypes on Linux/macOS.
* Tested against simulated TWAIN/SANE endpoints only; no physical scanner was available. If a particular model misbehaves, send `%LOCALAPPDATA%\Fathom\logs\server.log`.

## Page pickers, real-page previews and dragging
* Wherever a tool works on pages (Stamp, Sign, Rotate/flip, Split, Cut, PDF pages, Print, Redact…) it asks **which pages** (all, odd, even, first, last, a range such as `2-5, 9`, or tick them on thumbnails).
* **Preview on** shows a real page of a file you added (choose which file and which page; if you only added folders it asks which file in the folder). A blank page is one choice in the list.
* Stamps and signatures can be placed by **dragging** on that preview, resizing and rotating with the handles, and every number box (position, size, angle, opacity, margins) still works and stays in sync.

## The Assistant
* Open **Assistant** in the top bar, or press **Ctrl+J** anywhere for a side drawer. It knows which tab you are on, the values in the form, the files you added and what you just did, and can open a tool for you.
* It can: read and search your files, look at pictures and PDF pages, write and edit files (originals are backed up first), run any Fathom tool for you (with proof pictures), make **PDF, Word, web page, PowerPoint, Excel and chart files**, design pictures (text, shapes, gradients, photos), generate pictures with an image service, make **narrated videos** (slideshow style with motion, captions, voice and music), speak text, search and read the web, run Python or shell commands, and remember things you tell it.
* You can give it **files, folders, pasted pictures and links** (Files / Folder / Use my list under the box) to work from.
* **Approvals** (Settings): *Ask before changes* (default), *Ask before everything*, or *Never ask*. Reading is free; making, changing and running things show a card first.
* **My tools**: if what you want is not built in, say so; it writes a small tool, tests it on a copy, and it appears in the **My tools** group (run, edit by asking, delete).
* Provider: Anthropic Claude, any OpenAI-compatible service, or a local Ollama model (Settings > Which AI). The key is stored encrypted for your Windows user (DPAPI). Nothing is sent anywhere until you add a key; web search and fetch can be switched off.
* **Talk to it, in any language**: press 🎤 Talk and speak; Fathom writes what you said in the chat and the assistant answers in writing and out loud, in the language you used. Recognition uses the offline Whisper engine (about 99 languages, language detected automatically; installed by Fathom.bat when possible) or, if you saved an OpenAI key, that service; otherwise it falls back to the browser's voice typing in the language you pick. Spoken answers use the voices Windows has installed (add more under Windows Settings > Time & language > Speech). 🗣 Hands-free keeps a conversation going; 🔊 turns spoken answers on or off.
* **Watch my screen**: press 👁 and the assistant sees your whole screen (every monitor) while you use the app: each message you send carries a fresh picture, and it can look again by itself while a job runs. A small preview shows what it sees. It is off until you press it, nothing is recorded or saved, and only the newest picture is kept in the chat.
* Hard stops: the assistant's shell and Python tools refuse commands that would wipe a drive, delete system folders, damage Windows or switch off protection, even in "Never ask" mode.
* Honest limits: video is made from pictures, motion and voice (there is no text-to-video model inside); photo-style picture generation needs an image service key or a local Stable Diffusion server; the assistant adds tools but does not rewrite Fathom itself.

## Reading handwriting
* **Search > Find > "Also read handwriting"** and **Search > Read handwriting**. Fathom flattens the lighting, straightens the page, removes ruled and margin lines, cuts the page into lines, and reads every line. Results are cached, so a second search is instant.
* Readers: the **AI vision model** from Settings (best for very messy writing; unsure lines get a second look), an **offline reader** (TrOCR; one-click install in the tool, about 1 GB), or the built-in OCR on cleaned-up line crops. Search matching forgives spelling slips ("invoise" finds "invoice").
* Messy-but-readable writing depends on the AI model; nothing reads truly unreadable writing, and it marks doubtful words with `[?]` instead of guessing quietly.
* Tested here with generated tilted, ruled, shadowed pages and a scripted model; **not** tested with a real vision model, real handwriting or the offline reader (no internet or key in the build environment).

## Voice settings, chat width
* **Assistant › Settings › Microphone and voice**: pick which microphone to use (with a live level meter and *Test microphone*), the voice that speaks, its speed, and an engine choice. If you hear nothing in *Automatic*, choose *Always use the computer's own voice*; it uses the voices of Windows / macOS / Linux (espeak-ng), or your OpenAI voice if set. *Test voice* reads a sentence you type, in any language.
* The side chat has a **draggable edge** (drag to widen or narrow it, double-click to reset, arrow keys when selected) and a **Dock** button that moves the app over instead of covering it. The width is remembered.

## Activity & Undo, move to another drive, help
* **Tidy > Activity & Undo** lists every change Fathom made to your files (what was made, what was replaced, what was renamed). Undo puts originals back (Fathom keeps a private copy, a hard link when it can so it costs no extra room, for 30 days by default), moves renamed files back, and sends files Fathom made to the Recycle Bin. A file you edited yourself afterwards is never touched.
* **Put everything where you want (your choice).** Run **`Fathom-Setup.vbs`** (the setup wizard): a window with pages asks which extras to install (LibreOffice, Calibre, 7-Zip, the free local assistant) and **which folder or drive** each part goes to: the Fathom app, its data (Python packages, models, results), and every program (together in one folder, or each in its own, or in Windows' usual places). Windows keeps a tiny folder link at each old place (a few KB) so every program still finds what it needs; Ollama's AI model is not linked, Ollama is told where it is. Old copies are removed only after the new copy is checked. Running `Fathom.bat` directly asks nothing and moves nothing. `Fathom.bat setup` opens the same wizard.
* **?** (bottom left): the first-run tour again, or **Save a problem report** (a zip of the log files in Downloads; no file contents or keys). Alt+1…9 jump between top-bar groups; every control with a hover tip also has a screen-reader name.

## Shortcuts
Press **Ctrl+J** for the Assistant and **Ctrl+K** anywhere to jump to a tool by typing what you want to do. The **Home** tab lists every tool and has a Light/Dark switch.

## Updating
Copy the new folder over the old one (or unzip it anywhere) and run **Fathom.bat**: it sees the newer version, updates what is needed (nothing already installed is downloaded again) and starts Fathom. If an update ever fails, the installed Fathom still starts.

## Search: what to find (six choices) and where to look
In **Search > Find**, pick one of six choices, then (optionally) change **Look in** (documents, pictures, videos, audio):
- **Words & numbers**: typed text in any file, plus words inside pictures and video frames.
- **Words seen** (pictures & videos): only text you can see (signs, slides, screenshots, subtitles).
- **Words spoken** (videos & audio): what is said, like searching a transcript (needs the speech engine).
- **Objects & scenes**: the actual thing, anywhere (pictures, PDF pages, videos).
- **Objects in pictures** / **Objects in videos**: the same, limited to one kind of file.

Search also reads inside files that used to be skipped: old Office files (.doc .xls .ppt and relatives, through LibreOffice), SQLite databases (.db .sqlite, every table and row), e-mail files (.eml: subject, sender, body and attachments), camera RAW photos (.cr2 .nef .arw .dng ...; full decode with the optional `rawpy`, otherwise the embedded preview picture) and more plain-text types (.vcf .ics .reg .m3u .nfo .mht ...).

## Changing volume, quality and more while you convert
In **Convert**, open the sections on the left. Every setting has a hover tip, and all of them work together:
* **Sound options and adjustments** (sound files and the sound of a video): volume (0-500%), even out the loudness, bass and treble, reduce hiss, fade in and out, mono or stereo, sample rate, sound quality.
* **Cut a part and change speed** (video and sound): keep only a part between two seconds, and play faster or slower (0.25x to 4x, the pitch of the sound is kept).
* **Video and GIF options**: quality, size, frame rate, keep the sound, **Only copy (no re-encode)**, encoding speed (faster or smaller file) and **Use the graphics card (NVIDIA)**.
* **Video look**: turn and mirror, brightness, contrast, colour strength, black and white, reduce grain, sharpen.
* **Picture adjustments**: brightness, contrast, colour strength, sharpness, blur, fix the lighting, black and white, invert, turn, mirror, print sharpness (DPI), next to the existing quality, size and metadata options.
* **Same type, only your changes.** To make a song louder, a video faster or a photo brighter without changing its type, choose the file's own type as the target (for example MP3 to MP3) after you set what to change. Fathom saves a new file and never overwrites the original; with nothing to change it says so instead of making a pointless copy. "Convert everything to…" never picks the same type by itself.
* **Copy first.** When you only change the container (MP4 to MKV) and pick nothing that changes the picture, Fathom copies the video as it is, in seconds, and only re-makes the sound if you changed it. Choosing quality, size, frame rate, speed, turn, colours or the graphics card means the picture is re-encoded.
* **Graphics card.** Fathom's built-in FFmpeg has no NVIDIA encoder. For the graphics-card option, install a full FFmpeg once (double-click `Get-FFmpeg-GPU.bat`, which uses winget) so it is on your PATH. Without one, or if the card cannot do the job, Fathom uses the processor.

## Fathom 1.1

**Also in 1.1:** save your settings as **presets**; choose which **sound track** of a video to keep; **cut silence** from audio; set an exact **quality (CRF)**; **deinterlace** old video; change a video's **shape** (crop or black bars); for pictures: **crop to a shape**, **auto-trim** empty edges, **border**, **fewer colours** and a choice of **resize method**.

- **Adjustments while converting:** volume, loudness, fades, bass and treble, noise reduction, mono or stereo, sample rate, cut a part, speed, turn and mirror, light and colour for video and pictures, blur and sharpen, DPI, encoding speed and graphics-card encoding. Conversions to the same type apply only your changes.
- **Copy-only video:** changing a container (MP4 to MKV) is a copy by default and takes seconds; it falls back to a normal conversion if copying fails.
- **Update:** the version is 1.1.0, so `Fathom.bat` updates an installed 1.0 copy the next time it runs.

## Fathom 1.0
- First official release. Everything above, plus a **setup wizard** (`Fathom-Setup.vbs`) that lets you choose where the Fathom app, its data and every program go, shows what each drive has free, and shows live progress.
- **Free Assistant** that runs on your own PC (Ollama): fast `qwen3-vl:4b-instruct` model by default, extra working memory and keep-alive so answers start quickly, and a self-repair for the "model not found" problem (`Fix-Ollama.cmd`).
- **`support` folder:** double-click help scripts (check everything, repair Ollama, scan for leftovers, update from a zip, download the fast model, speed test, repair, open logs). Each `.cmd` only starts a readable `.ps1`. None deletes your files or models.
- **"Please wait, this takes time":** anything slower than a few seconds (conversions, searches, repairs, the assistant's first answer, the Talk button, the setup wizard) shows how long it has taken and an approximate time left. Jobs with a progress bar compute it from how far they are; other work learns from earlier runs on the same PC.
- **Talk button** no longer waits for a surprise download: setup fetches the speech model (about 480 MB) up front. **Assistant first answer:** Fathom reads its long instructions once in the background at start (the model stays loaded for 60 minutes), so the first question starts quickly.
- **License:** Fathom is released under AGPL-3.0-or-later (see `LICENSE`).
- **Voice:** on Windows the answer is now read with the computer's own voice first (the window's reader is the fallback), and the assistant knows it can speak.
- **Ollama in the background:** the free assistant's engine starts by itself, hidden (no window, only its llama icon in the system tray), when Fathom opens, and closes again when Fathom closes. If it was stopped meanwhile, the assistant starts it again by itself, so "Could not reach Ollama" no longer happens. An Ollama you started yourself is never closed by Fathom.
- **Setup fixes:** choosing "keep my data in Windows' usual place" no longer stops the move step; programs an earlier setup left in another folder are moved to the folder you choose (the old one is only renamed to `<name>.moved`); failures show the real reason on the "Setup did not finish" page; `Fix-Ollama` removes only the small folder link and leaves no `.ollama.junction-old` behind.
- **Uninstall-Fathom.cmd** removes what Fathom installed, wherever you put it (asks first; your own files are never touched). **Lite** download (`fathom-lite.zip`, or `Fathom.bat lite`; `Fathom.bat full` adds the rest later). **Fathom Online**: a no-install, in-browser page on the website (nothing is uploaded).

## Updating Fathom (important)
Extract the new zip anywhere and run its `Fathom-Setup.vbs` or `Fathom.bat`. Fathom always re-points its Desktop and Start-menu shortcuts to the folder you ran, so the newest copy is the one that starts. Click **?** in the app: the last line of the menu shows the version and the folder that is running. If that is not the folder you expect, you are running an old copy.

---

**Copyright (C) 2026 The Fathomist.** Free software under AGPL-3.0-or-later with attribution and name terms; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
