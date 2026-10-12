/* Lab (forensics, disk images, junk) and Sync (remote places). Each is its own tool tab. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  const post = (p, b) => api(p, { method: "POST", body: b });
  const reg = (t, build) => F.addTool({ ...t, el: F.makeView(t.id), build: (sec) => { const v = F.standardView(t.id, { files: t.files !== false && !!t.files, output: !!t.output, hint: t.hint }); sec.replaceWith(v.sec); F.tools.find((x) => x.id === t.id).el = v.sec; v.sec.classList.add("on"); build(v.main, v); } });
  const mono = (t) => h("span", { class: "mono", text: t });

  /** text box + Browse button for one path on this PC */
  function pathRow(label, kind, tipText, ph) {
    const box = h("input", { type: "text", placeholder: ph || "", spellcheck: "false", style: "flex:1;min-width:200px" }); F.tip(box, tipText);
    const btn = h("button", { class: "btn small", tip: "Opens a window to choose it.", onclick: async () => { const p = await F.pickOne(kind); if (p) box.value = p; } }, "Browse…");
    return { el: h("div", { class: "field" }, h("div", { class: "lab", text: label }), h("div", { class: "inline", style: "display:flex;gap:8px" }, box, btn)), get: () => box.value.trim(), set: (v) => (box.value = v) };
  }
  function runBar(main, label, tipText, start, panelOpts = {}) {
    const go = h("button", { class: "primary", tip: tipText }, label); const host = h("div");
    const panel = new F.JobPanel(host, { ...panelOpts, onDone: (s, items) => { go.disabled = false; panelOpts.onDone && panelOpts.onDone(s, items); } });
    main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
    go.onclick = async () => { try { go.disabled = true; const r = await start(); if (r) panel.start(r.job); else go.disabled = false; } catch (e) { go.disabled = false; F.toast(e.message); } };
    return { go, panel, host };
  }

  // ---------------------------------------------------------------- hidden streams
  reg({ id: "streams", group: "lab", icon: "🫥", label: "Hidden streams", blurb: "Windows (NTFS) can hide extra data behind a normal file. Find it, look at it, and cut it out.", files: true, hint: "Add files or folders on an NTFS drive." }, (main) => {
    main.append(F.titleBlock("Hidden streams (NTFS)", "On Windows drives a file can carry secret 'streams': extra data that does not show in the file size or in Explorer. Most are harmless (the 'downloaded from the internet' mark), but programs and scripts can hide there too. Fathom lists every one, tells you what it looks like, and removes the ones you choose."));
    const out = h("div"); let rows = [];
    const r = runBar(main, "Look for hidden streams", "Checks every file on the left for hidden streams. Nothing is changed.", async () => { if (!F.needFiles()) return null; out.replaceChildren(); return post("/api/lab/ads/scan", { paths: F.state.sources, recursive: true }); },
      { noun: "file", summary: false, renderItem: () => document.createComment(""), onDone: (s) => draw(s.data) });
    main.append(out);
    function draw(d) {
      rows = (d && d.streams) || [];
      if (d && d.windows_only) return out.replaceChildren(h("div", { class: "warnbox", text: "Hidden streams only exist on Windows (NTFS) drives, so there is nothing to find on this computer." }));
      if (!rows.length) return out.replaceChildren(h("div", { class: "card-box" }, h("b", { text: "No hidden streams found." })));
      const checks = rows.map((x) => { const i = h("input", { type: "checkbox" }); i.checked = x.risk !== "low"; return i; });
      const save = h("input", { type: "checkbox" }); save.checked = true;
      out.replaceChildren(h("div", { class: "card-box" }, h("h3", { text: `${rows.length} hidden stream${rows.length === 1 ? "" : "s"}` }),
        h("table", { class: "tbl" }, h("tr", {}, ["", "File", "Stream", "Size", "Looks like"].map((x) => h("th", { text: x }))), ...rows.map((x, i) => h("tr", {}, h("td", {}, checks[i]), h("td", { text: F.baseName(x.file), title: x.file }), h("td", { class: "mono", text: x.stream }), h("td", { text: F.fmtBytes(x.size) }), h("td", { class: x.risk === "high" ? "badc" : x.risk === "medium" ? "warnc" : "", text: x.kind })))),
        h("div", { class: "row", style: "margin-top:12px" }, h("label", { tip: "On: each removed stream is first saved as a small file next to the Fathom save location, so nothing is lost.\nOff: removed streams are gone for good." }, save, "Keep a copy of what I remove"),
          h("button", { class: "primary warn", tip: "Deletes the ticked streams from their files. The normal content of the files stays exactly as it is.", onclick: async () => {
            const items = rows.filter((_, i) => checks[i].checked).map((x) => ({ file: x.file, stream: x.stream })); if (!items.length) return F.toast("Tick the streams to remove.");
            try { const res = await post("/api/lab/ads/strip", { items, text: save.checked ? (F.state.output.dir || "") : "" }); F.toast(`Removed ${res.removed}` + (res.failed.length ? `, ${res.failed.length} failed` : "")); out.replaceChildren(); } catch (e) { F.toast(e.message); } } }, "Remove ticked streams"))));
    }
  });

  // ---------------------------------------------------------------- attributes
  reg({ id: "attrs", group: "lab", icon: "👁", label: "Hidden items", blurb: "Show what the system hides in a folder (hidden, system and dot files) and flip those switches.", files: false }, (main) => {
    main.append(F.titleBlock("Hidden items", "Windows hides files with the Hidden and System flags, macOS with the 'hidden' flag, and Linux with a dot at the start of the name. Fathom lists everything hidden in a folder and lets you expose it or hide it again."));
    const root = pathRow("Folder to look in", "folder", "The folder to look through, including all folders inside it.", "e.g. C:\\Users\\you");
    const deep = h("input", { type: "checkbox" }); deep.checked = true;
    main.append(h("div", { class: "card-box" }, root.el, h("label", { tip: "On: also looks inside every folder within.\nOff: only the folder you chose." }, deep, "Look inside folders too")));
    const out = h("div"); let items = [];
    const find = h("button", { class: "primary", tip: "Lists the hidden items in that folder. Nothing is changed." }, "Find hidden items");
    main.append(h("div", { class: "row", style: "margin-top:16px" }, find), out);
    const apply = async (action, label) => {
      const paths = items.filter((_, i) => out._c[i].checked).map((x) => x.path); if (!paths.length) return F.toast("Tick some items first.");
      try { const r = await post("/api/lab/attrs/apply", { paths, action }); F.toast(`${label}: ${r.changed} changed` + (r.failed.length ? `, ${r.failed.length} failed` : "")); find.click(); } catch (e) { F.toast(e.message); }
    };
    find.onclick = async () => {
      if (!root.get()) return F.toast("Choose a folder.");
      try { const r = await post("/api/lab/attrs/find", { path: root.get(), recursive: deep.checked }); items = r.items;
        if (!items.length) return out.replaceChildren(h("div", { class: "card-box" }, h("b", { text: "Nothing hidden in there." })));
        out._c = items.map(() => { const i = h("input", { type: "checkbox" }); i.checked = true; return i; });
        out.replaceChildren(h("div", { class: "card-box" }, h("h3", { text: `${items.length} hidden item${items.length === 1 ? "" : "s"}` }),
          h("div", { class: "row" },
            h("button", { class: "btn", tip: "Makes the ticked items visible again (removes the Hidden flag, or the dot at the start of the name on Linux).", onclick: () => apply("show", "Exposed") }, "Expose ticked"),
            h("button", { class: "btn", tip: "Hides the ticked items again.", onclick: () => apply("hide", "Hidden") }, "Hide ticked"),
            r.platform === "win32" ? h("button", { class: "btn", tip: "Removes the System flag. Only do this for files you know. System files are normally hidden because changing them can break Windows.", onclick: () => apply("system_off", "System flag removed") }, "Remove System flag") : null),
          h("table", { class: "tbl" }, h("tr", {}, ["", "Name", "Type", "Flags"].map((x) => h("th", { text: x }))), ...items.map((x, i) => h("tr", {}, h("td", {}, out._c[i]), h("td", { text: x.name, title: x.path }), h("td", { text: x.dir ? "Folder" : "File" }), h("td", { text: [x.hidden && "hidden", x.system && "system", x.readonly && "read-only", x.dot && "dot-name"].filter(Boolean).join(", ") }))))));
      } catch (e) { F.toast(e.message); }
    };
  });

  // ---------------------------------------------------------------- carving
  reg({ id: "carve", group: "lab", icon: "⛏", label: "Recover deleted", blurb: "Scan a whole drive or disk image for deleted pictures, documents, videos and more, and rebuild them.", output: true }, async (main) => {
    main.append(F.titleBlock("Recover deleted files", "When you delete a file, its data usually stays on the drive until something writes over it. Fathom reads the drive (or a disk image file) sector by sector, recognises the start of files by their signatures (JPEG, PNG, PDF, ZIP, MP4…), and rebuilds them. File names and folders are lost this way; the contents come back. Fathom only reads the drive, it never writes to it."));
    const src = pathRow("Drive or disk image to scan", "files", "Type a drive letter like E: (needs administrator rights) or choose a disk image file (.img, .dd, .vhd…). Never recover onto the drive you are scanning.", "E:   or   C:\\images\\card.img");
    let kinds = {}; try { kinds = (await api("/api/lab/carve/kinds")).kinds; } catch { /* ignore */ }
    const form = F.form([{ id: "kinds", type: "multi", label: "Look for", value: Object.keys(kinds), options: Object.entries(kinds).map(([v, l]) => ({ v, l, tip: `Rebuilds ${l} files.` })), tip: "Which kinds of files to rebuild." },
      { id: "min", type: "number", label: "Ignore anything smaller than", value: 4, min: 0, unit: "KB", tip: "Small fragments are often false hits.\nLow: more results, more junk.\nHigh: fewer, more useful results." },
      { id: "aligned", type: "check", label: "Only files that start on a sector boundary", value: true, tip: "On: faster and far fewer false results. Real files almost always start there.\nOff: slower, also finds files in odd places (for example inside other files)." }]);
    main.append(h("div", { class: "card-box" }, src.el, form.el, h("div", { class: "warnbox", text: "Save recovered files on a different drive than the one you scan. Pick the save folder on the left. The sooner you scan after deleting, the better the result. On SSDs, deleted data is often wiped by the drive itself, so recovery may find little." })));
    const res = h("div");
    runBar(main, "Start scanning", "Reads the drive from start to end. Large drives take a long time; you can stop at any moment and keep what was found.", async () => { const v = form.values(); if (!src.get()) { F.toast("Choose the drive or disk image to scan."); return null; } res.replaceChildren(); return post("/api/lab/carve", { path: src.get(), kinds: v.kinds, output: F.outputBody(), options: { min_kb: v.min || 0, aligned: v.aligned } }); },
      { noun: "scan", summary: false, onDone: (s) => { const c = (s.data && s.data.carved) || []; res.replaceChildren(c.length ? h("table", { class: "tbl" }, h("tr", {}, ["File", "Type", "Size", "Found at"].map((x) => h("th", { text: x }))), ...c.slice(0, 2000).map((x) => h("tr", {}, h("td", {}, h("button", { class: "link", onclick: () => F.reveal(x.path) }, F.baseName(x.path))), h("td", { text: x.type }), h("td", { text: F.fmtBytes(x.size) }), h("td", { class: "mono", text: x.offset.toLocaleString() })))) : h("p", { class: "hint", text: "Nothing could be rebuilt." })); } });
    main.append(res);
  });

  // ---------------------------------------------------------------- steganography
  reg({ id: "steg", group: "lab", icon: "🫧", label: "Hidden data", blurb: "Find files hidden inside pictures and sound (and hide your own, locked with a password).", files: true, output: true, hint: "Add PNG, BMP, TIFF pictures or WAV sounds." }, (main) => {
    main.append(F.titleBlock("Hidden data in pictures and sound", "Secret files can be tucked into the tiniest parts of a picture's pixels or a sound's samples, or glued after the end of a file. Fathom checks for both, isolates what it finds and unlocks Fathom-made packets with the password. You can also hide a file of your own the same way, encrypted with AES-256. JPEG cannot be used for hiding because saving it destroys the hidden bits."));
    const pw = F.form([{ id: "pw", type: "password", label: "Password for the hidden packet (if any)", tip: "If the hidden data is locked, type the password so Fathom can open it. Leave empty to only find it and save the locked packet." }]);
    main.append(h("div", { class: "card-box" }, h("h3", { text: "Look for hidden data" }), pw.el));
    runBar(main, "Search the files on the left", "Checks each picture or sound for hidden data and appended data. Results are saved in your chosen save location.", async () => (F.needFiles() ? post("/api/lab/steg/scan", { paths: F.state.sources, recursive: true, password: pw.values().pw || "", output: F.outputBody() }) : null), { noun: "file" });
    main.append(h("hr"));
    const cover = pathRow("Cover picture or sound", "image", "The picture (PNG, BMP, TIFF) or WAV sound the secret will hide in. The bigger it is, the more it can hold.", "");
    const secret = pathRow("File to hide", "files", "Any file. It is encrypted before it is hidden.", "");
    const form = F.form([{ id: "pw", type: "password", label: "Lock with a password", tip: "Strongly recommended. Without a password the hidden file can be read by anyone who knows where to look. If you forget it, the secret cannot be recovered." }]);
    const cap = h("small", { class: "hint" });
    cover.el.querySelector("input").addEventListener("change", async () => { try { cap.textContent = "Room for about " + F.fmtBytes((await post("/api/lab/steg/capacity", { path: cover.get() })).bytes); } catch (e) { cap.textContent = e.message; } });
    main.append(h("div", { class: "card-box" }, h("h3", { text: "Hide a file" }), cover.el, cap, secret.el, form.el));
    runBar(main, "Hide it", "Makes a new picture or sound that carries the secret. The original is not touched. Never edit, resize or re-save the new file.", async () => { if (!cover.get() || !secret.get()) { F.toast("Choose both the cover and the file to hide."); return null; } return post("/api/lab/steg/hide", { path: cover.get(), text: secret.get(), password: form.values().pw || "", output: F.outputBody() }); }, { noun: "file" });
  });

  // ---------------------------------------------------------------- disk images
  reg({ id: "images", group: "lab", icon: "💽", label: "Disk images", blurb: "Open virtual disks (VHD, VHDX, VMDK, VDI, SquashFS, ISO) and Docker images and take files out, without mounting.", output: true }, (main) => {
    main.append(F.titleBlock("Disk images and containers", "Look inside a virtual machine's disk (VHD, VHDX, VMDK, VDI, QCOW2), a SquashFS or ISO, or a Docker image and copy files out. Snapshots inside snapshots are opened automatically. Docker layers are merged in order, so you see the real file tree of the container. Nothing is mounted or started."));
    const src = pathRow("Disk image or Docker image (.tar)", "files", "Choose the virtual disk or the saved Docker image (from 'docker save').", "");
    const filt = h("input", { type: "search", placeholder: "Filter the list…", style: "max-width:320px" }); F.tip(filt, "Type part of a name to show only matching files.");
    const info = h("p", { class: "hint" }), list = h("div"); let entries = [], checked = new Set();
    const open = h("button", { class: "btn", tip: "Reads the list of files inside the image. Large images can take a moment." }, "Look inside");
    main.append(h("div", { class: "card-box" }, src.el, h("div", { class: "row" }, open, filt), info), list);
    const draw = () => { const q = filt.value.toLowerCase(); const shown = entries.filter((e) => !q || e.path.toLowerCase().includes(q)).slice(0, 400);
      list.replaceChildren(h("table", { class: "tbl" }, h("tr", {}, ["", "Path", "Size"].map((x) => h("th", { text: x }))), ...shown.map((e) => { const c = h("input", { type: "checkbox" }); c.checked = checked.has(e.path); c.onchange = () => (c.checked ? checked.add(e.path) : checked.delete(e.path)); return h("tr", {}, h("td", {}, c), h("td", { text: (e.dir ? "📁 " : "") + e.path }), h("td", { text: e.dir ? "" : F.fmtBytes(e.size) })); })), entries.length > 400 ? h("p", { class: "hint", text: "Showing the first 400 matches. Use the filter to narrow down." }) : null); };
    filt.oninput = draw;
    open.onclick = async () => { if (!src.get()) return F.toast("Choose an image first."); try { const r = await post("/api/lab/image/list", { path: src.get() }); entries = r.entries; checked = new Set(); info.textContent = `${r.kind === "docker" ? `Docker image · ${r.layers} layers · ` : ""}${entries.length}${r.truncated ? "+" : ""} items`; draw(); } catch (e) { F.toast(e.message); } };
    runBar(main, "Copy files out", "Copies the ticked files and folders. If nothing is ticked, everything is copied.", async () => (src.get() ? post("/api/lab/image/extract", { path: src.get(), items: [...checked], output: F.outputBody() }) : (F.toast("Choose an image first."), null)), { noun: "image" });
  });

  // ---------------------------------------------------------------- junk
  reg({ id: "junk", group: "lab", icon: "🧹", label: "Junk cleaner", blurb: "Clear temp files, crash reports, thumbnail caches and leftovers of programs you removed.", files: false }, (main) => {
    main.append(F.titleBlock("Junk cleaner", "Finds files your system no longer needs: temporary files, crash reports and memory dumps, picture and icon caches, old logs, and the settings folders that uninstalled programs left behind. Scanning only measures. Cleared items go to the Recycle Bin unless you choose to delete them for good. Anything in use is skipped."));
    const res = h("div"); let jobId = null, cats = {};
    const r = runBar(main, "Scan for junk", "Measures how much each kind of junk uses. Nothing is deleted yet.", async () => { res.replaceChildren(); return post("/api/lab/junk/scan", {}); },
      { noun: "kind", summary: false, renderItem: () => document.createComment(""), onDone: (s) => { jobId = s.id; cats = (s.data && s.data.cats) || {}; draw(); } });
    main.append(res);
    function draw() {
      const list = Object.values(cats).sort((a, b) => b.bytes - a.bytes); const boxes = {};
      const sel = h("span", { class: "hint" }); const upd = () => { const t = list.filter((c) => boxes[c.id].checked).reduce((s, c) => s + c.bytes, 0); sel.textContent = `${F.fmtBytes(t)} selected`; };
      const perm = h("input", { type: "checkbox" });
      const leftoverPick = new Set();
      res.replaceChildren(h("div", { class: "card-box" }, ...list.map((c) => { const i = h("input", { type: "checkbox" }); i.checked = c.safe && c.bytes > 0; i.disabled = !c.bytes; i.onchange = upd; boxes[c.id] = i;
          return h("div", { class: "dupgroup" }, h("label", { tip: c.tip }, i, h("b", { text: ` ${c.label}` }), h("small", { text: `  ${F.fmtBytes(c.bytes)} · ${c.files} files` })),
            c.id === "leftovers" && c.folders.length ? h("div", { style: "margin:6px 0 0 24px" }, ...c.folders.slice(0, 60).map((f) => { const j = h("input", { type: "checkbox" }); j.onchange = () => (j.checked ? leftoverPick.add(f.path) : leftoverPick.delete(f.path)); return h("label", { style: "display:block" }, j, `${f.path}  `, h("small", { text: F.fmtBytes(f.bytes) })); })) : null); }),
        h("div", { class: "row", style: "margin-top:12px" }, sel, h("label", { tip: "On: items are deleted at once and cannot be restored.\nOff: items go to the Recycle Bin first, so you can bring them back." }, perm, "Delete for good (skip the Recycle Bin)"),
          h("button", { class: "primary warn", tip: "Clears everything that is ticked.", onclick: async () => { const ids = list.filter((c) => boxes[c.id].checked).map((c) => c.id); if (!ids.length) return F.toast("Tick something to clear.");
            try { const o = await post("/api/lab/junk/clear", { job: jobId, kinds: ids, action: perm.checked ? "delete" : "recycle", items: [...leftoverPick] }); F.toast(`Cleared ${o.cleared} items · ${F.fmtBytes(o.freed)} freed` + (o.failed_count ? ` · ${o.failed_count} in use, skipped` : "")); res.replaceChildren(); } catch (e) { F.toast(e.message); } } }, "Clear selected"))));
      upd();
    }
  });

  // ---------------------------------------------------------------- drive -> image, repair
  reg({ id: "mkimage", group: "lab", icon: "📀", label: "Drive to image", blurb: "Copy a whole drive, card or disk to one image file (read only), with a fingerprint to prove the copy is exact.", output: true }, (main) => {
    main.append(F.titleBlock("Drive to image file", "Makes an exact copy of a drive, SD card or USB stick as one .img file, for backups or for later recovery. The drive is only read, never changed. Unreadable spots are skipped and counted, so a failing drive still gives you what can be saved. A SHA-256 fingerprint file is saved next to it. Writing an image back onto a drive is deliberately not offered here, because one wrong click would erase the wrong disk."));
    const src = pathRow("Drive to copy", "files", "Type a drive letter like E: (needs administrator rights), or choose a disk image or device file.", "E:");
    const nm = F.form([{ id: "name", type: "text", label: "Image name (optional)", placeholder: "my-card", tip: "The name of the new image file, without the ending." }]);
    main.append(h("div", { class: "card-box" }, src.el, nm.el, h("div", { class: "warnbox", text: "Choose the save folder on the left. It must be on a different drive, and have as much free space as the drive you copy." })));
    runBar(main, "Make the image", "Reads the whole drive from start to end. You can stop at any time.", async () => (src.get() ? post("/api/lab/image/make", { path: src.get(), text: nm.values().name || "", output: F.outputBody() }) : (F.toast("Type or choose the drive to copy."), null)), { noun: "drive" });
  });

  jobTool_repair();
  function jobTool_repair() {
    reg({ id: "repair", group: "lab", icon: "🩹", label: "Repair files", blurb: "Fix damaged pictures (PNG, JPEG, GIF), ZIP and Office files and PDFs. Works on a copy.", files: true, output: true, hint: "Add the damaged files." }, (main) => {
      main.append(F.titleBlock("Repair damaged files", "Rebuilds files that will not open: a PNG with bad checksums or a missing end, a JPEG cut short, a GIF or ZIP with a broken ending, Word, Excel and PowerPoint files that are really damaged ZIPs, and PDFs with a broken index. Your original is never changed; the repaired copy is saved next to it or in your chosen folder. Only the readable part can be saved, so a badly damaged file may come back partly."));
      runBar(main, "Repair the files on the left", "Makes a repaired copy of each file.", async () => (F.needFiles() ? post("/api/lab/repair", { paths: F.state.sources, recursive: true, output: F.outputBody() }) : null), { noun: "file" });
    });
  }


  // ---------------------------------------------------------------- damaged test copies
  reg({ id: "damage", group: "lab", icon: "🧪", label: "Damage copies", blurb: "Make a deliberately damaged copy of a file, to test how other software (or the Repair tool) copes with broken files.", files: true, output: true, hint: "Add the files to make damaged test copies of." }, async (main) => {
    main.append(F.titleBlock("Make damaged test copies", "Creates a broken copy of a file on purpose: a scrambled header, a cut-off end, a zeroed-out chunk (like a bad sector), or scattered random changes. Useful for testing how a program handles broken input, or for trying out the Repair tool. This only ever makes a new copy — your original file is never touched."));
    let modes = {}; try { modes = (await api("/api/lab/damage/modes")).modes; } catch { modes = {}; }
    const tips = { header: "Scrambles the first part of the file, where the file type is usually recognised from.", footer: "Scrambles the last part of the file, where many formats keep their closing marker.", zero: "Overwrites one chunk with zeros, like a drive that failed to read that spot.", flip: "Changes one byte in many places scattered through the file, like noise on a cable or a flaky memory card.", truncate: "Cuts the file short, as if the copy or download stopped partway." };
    const form = F.form([{ id: "mode", type: "select", label: "How to damage it", value: "header", options: Object.entries(modes).map(([v, l]) => ({ v, l, tip: tips[v] })) },
      { id: "strength", type: "range", label: "How much", min: 1, max: 100, value: 15, fmt: (v) => v + "%", tip: "Low: a small, often fixable amount of damage.\nHigh: heavy damage that may be impossible to recover." }]);
    main.append(h("div", { class: "card-box" }, form.el));
    runBar(main, "Make damaged copies", "Makes one damaged copy of each file on the left, saved to your chosen location.", async () => { const v = form.values(); return F.needFiles() ? post("/api/lab/damage", { paths: F.state.sources, recursive: true, action: v.mode, number: +v.strength, output: F.outputBody() }) : null; }, { noun: "file" });
  });

  // ---------------------------------------------------------------- scanner import (Windows WIA, TWAIN and SANE; tested only against simulators, not real scanners)
  reg({ id: "scanner", group: "edit", icon: "🖨", label: "Import from scanner", blurb: "Pull a page straight from a physical scanner: Windows scanners (WIA), TWAIN drivers, and SANE scanners on this computer or on a network server.", files: false, output: true }, async (main) => {
    main.append(F.titleBlock("Import from a scanner", "Scans a page on a real scanner and saves it here. Fathom speaks three scanner languages and lists every scanner it finds: WIA (Windows' own scanning service, the one the built-in Windows Scan app uses), TWAIN (the older driver standard that many manufacturers still provide, with feeder support) and SANE (scanners on Linux or Mac, or on any computer or print server running the SANE 'saned' service, reached over the network). After scanning, use 'Scan pages' in the Edit group to straighten and clean up the page."));
    const host = h("div"); main.append(host);
    const refresh = h("button", { class: "btn", tip: "Looks for scanners connected to this PC (WIA, TWAIN and SANE), and on the SANE server below if you typed one." }, "Look for scanners");
    const list = h("div");
    const hostForm = F.form([{ id: "host", type: "text", label: "SANE server (optional)", value: F.load("scanhost", ""), placeholder: "e.g. 192.168.1.20  or  192.168.1.20:6566", tip: "Only for scanners attached to another computer that runs the SANE 'saned' service (Linux, Raspberry Pi, a Mac, some print servers). Leave empty for scanners on this PC." }]);
    main.append(h("div", { class: "card-box" }, hostForm.el), h("div", { class: "row" }, refresh), list);
    let chosen = "";
    refresh.onclick = async () => { list.replaceChildren(h("p", { class: "hint", text: "Looking…" }));
      try { const host = (hostForm.values().host || "").trim(); try { F.save("scanhost", host); } catch {}
        const r = await api("/api/lab/scanner/list" + (host ? "?host=" + encodeURIComponent(host) : ""));
        if (!r.available) return list.replaceChildren(h("div", { class: "warnbox", text: r.why }));
        const notes = (r.notes || []).map((n) => h("p", { class: "hint", text: n }));
        if (!r.scanners.length) return list.replaceChildren(h("p", { class: "hint", text: "No scanner found. Make sure it is turned on, connected, and set up (it should show up in the Windows Scan app, or its TWAIN / SANE driver should be installed)." }), ...notes);
        list.replaceChildren(h("div", { class: "card-box" }, ...r.scanners.map((s) => { const b = h("button", { class: "btn small" }, s.name + "  ·  " + s.kind); b.onclick = () => { chosen = s.id; [...list.querySelectorAll("button")].forEach((x) => x.classList.remove("primary")); b.classList.add("primary"); }; return b; })));
        if (notes.length) list.append(...notes);
        if (r.scanners.length === 1) { chosen = r.scanners[0].id; list.querySelector("button")?.classList.add("primary"); }
      } catch (e) { list.replaceChildren(h("div", { class: "warnbox", text: e.message })); } };
    refresh.click();
    const form = F.form([{ id: "mode", type: "select", label: "Colour", value: "color", options: [{ v: "color", l: "Colour" }, { v: "gray", l: "Grey" }, { v: "bw", l: "Black and white" }], tip: "Black and white gives the smallest file and is sharpest for plain text." },
      { id: "dpi", type: "select", label: "Quality", value: "300", options: [{ v: "150", l: "150 DPI — quick, for text" }, { v: "300", l: "300 DPI — good default" }, { v: "600", l: "600 DPI — sharp, bigger file" }], tip: "Higher numbers capture more detail but take longer and make a bigger file." },
      { id: "out", type: "select", label: "Save as", value: "jpg", options: [{ v: "jpg", l: "JPG" }, { v: "png", l: "PNG" }, { v: "pdf", l: "PDF" }] },
      { id: "ui", type: "check", label: "Show the scanner maker's own window (TWAIN only)", value: false, tip: "Opens the driver's own scan dialog so you can set the area, colour and more yourself. Ignored for WIA and SANE scanners." },
      { id: "pages", type: "check", label: "Scan every sheet in the feeder (TWAIN only)", value: false, tip: "For scanners with an automatic document feeder: keeps going until the feeder is empty, and saves all pages (as one PDF if you choose PDF)." }]);
    main.append(h("div", { class: "card-box" }, form.el));
    runBar(main, "Scan", "Starts the scanner and saves the page.", async () => { if (!chosen) { F.toast("Choose a scanner first."); return null; } const v = form.values(); return post("/api/lab/scanner/scan", { path: chosen, output: F.outputBody(), options: { dpi: +v.dpi, mode: v.mode, out: v.out, ui: !!v.ui, pages: !!v.pages } }); }, { noun: "page" });
  });

  // ---------------------------------------------------------------- sync
  reg({ id: "sync", group: "sync", icon: "🔄", label: "Sync", blurb: "Copy or mirror a folder to and from servers and clouds, many files at once, optionally encrypted before it leaves this PC.", files: false }, async (main) => {
    main.append(F.titleBlock("Network sync", "Send a folder from this PC to a server or cloud drive, or bring one back. Many files are copied at the same time in the background, unchanged files are skipped, and you can encrypt every file before it leaves this PC (AES-256 or ChaCha20) so even the server's owner cannot read it."));
    let kinds = {}; try { kinds = (await api("/api/lab/net/kinds")).kinds; } catch { kinds = { local: "This PC / USB drive" }; }
    const saved = F.load("net", {});
    const HOSTLAB = { smb: "Server name", nfs: "Server name (optional)", sftp: "Server address", ftp: "Server address", ftps: "Server address", webdav: "Web address (URL)", s3: "Custom endpoint (leave empty for Amazon)", azure: "Storage account name", gdrive: "rclone remote name", rclone: "rclone remote name", adb: "Phone serial (optional)", mtp: "Device name in Explorer" };
    const form = F.form([
      { id: "type", type: "select", label: "Where to", value: saved.type || "local", options: Object.entries(kinds).map(([v, l]) => ({ v, l })), tip: "The kind of place to connect to. Network drives that are already mounted as a folder can be used with 'This PC'." },
      { id: "host", type: "text", label: "Server", value: saved.host || "", show: (v) => v.type !== "local", placeholder: "", tip: "The name or address of the server. For clouds this is the account or remote name shown below the field name." },
      { id: "port", type: "number", label: "Port", value: saved.port || "", show: (v) => ["sftp", "ftp", "ftps"].includes(v.type), tip: "Leave empty for the usual port (22 for SFTP, 21 for FTP)." },
      { id: "user", type: "text", label: "User / access key", value: saved.user || "", show: (v) => !["local", "nfs", "adb", "mtp", "gdrive", "rclone"].includes(v.type) || v.type === "nfs" && false, tip: "Your user name. For Amazon S3 this is the access key ID." },
      { id: "password", type: "password", label: "Password / secret", value: "", show: (v) => !["local", "nfs", "adb", "mtp", "gdrive", "rclone"].includes(v.type), tip: "Not saved anywhere. For S3 this is the secret access key, for Azure the account key, for SFTP the key's passphrase when you use a key file." },
      { id: "key_file", type: "text", label: "SSH key file (optional)", value: saved.key_file || "", show: (v) => v.type === "sftp", tip: "A private key file instead of a password." },
      { id: "bucket", type: "text", label: "Bucket / container", value: saved.bucket || "", show: (v) => ["s3", "azure"].includes(v.type), tip: "The name of the bucket (S3) or container (Azure) to use." },
      { id: "region", type: "text", label: "Region", value: saved.region || "", show: (v) => v.type === "s3", tip: "For example us-east-1. Leave empty if unsure." },
      { id: "path", type: "text", label: "Folder on that place", value: saved.path || "", placeholder: "backup/photos", tip: "The folder on the remote place. For a Windows share this is the share name and folder, like Photos/2024. Leave empty for the top." },
    ], (v) => { hostLab(v); });
    const hostField = form.el.querySelectorAll(".field")[1];
    const hostLab = (v) => { const l = hostField && hostField.querySelector("label"); if (l) l.textContent = HOSTLAB[v.type] || "Server"; };
    const local = pathRow("Folder on this PC", "folder", "The folder on this computer that is sent, or that receives the files.", "");
    const opts = F.form([
      { id: "dir", type: "choice", label: "Direction", value: saved.dir || "up", options: [{ v: "up", l: "Send to the place", s: "this PC → remote", tip: "Copies files from your folder to the remote place." }, { v: "down", l: "Bring back", s: "remote → this PC", tip: "Copies files from the remote place into your folder." }] },
      { id: "threads", type: "range", label: "Files at the same time", min: 1, max: 16, value: saved.threads || 4, fmt: (v) => String(v), tip: "How many files are copied together.\nLow: gentle on the network and the server.\nHigh: much faster on fast connections and with many small files." },
      { id: "enc", type: "check", label: "Encrypt files before they leave this PC", value: !!saved.enc, tip: "On: every file is locked with your password and saved as .locked on the remote place. When bringing files back, they are unlocked again.\nOff: files are copied as they are." },
      { id: "algo", type: "select", label: "Encryption", value: "aes", show: (v) => v.enc, options: [{ v: "aes", l: "AES-256" }, { v: "chacha", l: "ChaCha20" }], tip: "Both are extremely strong." },
      { id: "epw", type: "password", label: "Encryption password", show: (v) => v.enc, tip: "Needed to bring the files back. If you forget it, the files cannot be recovered. Not saved." },
      { id: "skip", type: "check", label: "Skip files that are already there and unchanged", value: true, tip: "On: only new and changed files are copied. Much faster the second time.\nOff: everything is copied again." },
      { id: "mirror", type: "check", label: "Make the other side match exactly (delete extras)", value: false, tip: "On: files that exist only on the receiving side are removed (on this PC they go to the Recycle Bin).\nOff: nothing is ever deleted. This is the safe choice." },
      { id: "include", type: "text", label: "Only these names (optional)", placeholder: "*.jpg, *.png", tip: "Copy only files whose names match. Use * as a wildcard. Separate with commas." },
      { id: "exclude", type: "text", label: "Never these names (optional)", placeholder: "*.tmp, Thumbs.db", tip: "Skip files whose names match." },
      { id: "dry", type: "check", label: "Practice run (copy nothing)", value: false, tip: "On: shows what would be copied, without copying anything.\nOff: really copies." },
    ]);
    hostLab(form.values());
    const cfgOf = () => { const v = form.values(); return { type: v.type, host: v.host, port: v.port || undefined, user: v.user, password: v.password, key_file: v.key_file, bucket: v.bucket, region: v.region, path: v.path }; };
    const remember = () => { const v = form.values(), o = opts.values(); F.save("net", { type: v.type, host: v.host, port: v.port, user: v.user, key_file: v.key_file, bucket: v.bucket, region: v.region, path: v.path, dir: o.dir, threads: o.threads, enc: o.enc }); };
    const brow = h("div"); 
    const test = h("button", { class: "btn", tip: "Connects and shows what is in that folder, so you know the details are right." }, "Test connection");
    test.onclick = async () => { try { const r = await post("/api/lab/net/browse", { cfg: cfgOf(), path: "" }); brow.replaceChildren(h("div", { class: "card-box" }, h("b", { text: `Connected · ${r.count} item${r.count === 1 ? "" : "s"} here` }), h("div", { class: "tags" }, ...r.items.slice(0, 40).map((i) => h("span", { class: "tag fs", text: (i.dir ? "📁 " : "") + i.name }))))); } catch (e) { brow.replaceChildren(h("div", { class: "warnbox", text: e.message })); } };
    main.append(h("div", { class: "card-box" }, h("h3", { text: "The remote place" }), form.el, test), brow, h("div", { class: "card-box" }, h("h3", { text: "What to copy" }), local.el, opts.el));
    const res = h("div");
    runBar(main, "Start syncing", "Runs in the background. You can leave this page; progress is shown here.", async () => {
      const o = opts.values(); if (!local.get()) { F.toast("Choose the folder on this PC."); return null; }
      if (o.enc && !(o.epw || "").length) { F.toast("Type an encryption password, or switch encryption off."); return null; }
      if (o.mirror && !o.dry && !confirm("Delete files that exist only on the receiving side? " + (o.dir === "up" ? "Extra files on the remote place will be removed." : "Extra files in your folder will go to the Recycle Bin."))) return null;
      remember(); res.replaceChildren();
      return post("/api/lab/net/sync", { cfg: cfgOf(), action: o.dir, text: local.get(), path: form.values().path, options: { threads: o.threads, password: o.enc ? o.epw : "", algo: o.algo, skip_same: o.skip, mirror: o.mirror, include: o.include, exclude: o.exclude, dry: o.dry } });
    }, { noun: "file", onDone: (s) => { if (s.total === 0) res.replaceChildren(h("p", { class: "hint", text: "Everything is already up to date." })); else if (s.data && s.data.deleted) res.replaceChildren(h("p", { class: "hint", text: `${s.data.deleted} extra files removed.` })); } });
    main.append(res);
  });
})();
