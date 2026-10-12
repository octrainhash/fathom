/* Drives: every drive with its file system, health and actions; where the space went; will my files fit; speed-ups; which format to choose. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  const post = (p, b) => api(p, { method: "POST", body: b });
  const reg = (t, build) => F.addTool({ ...t, el: F.makeView(t.id, false), build: (sec) => { const v = F.standardView(t.id, { files: !!t.files, output: !!t.output }); sec.replaceWith(v.sec); F.tools.find((x) => x.id === t.id).el = v.sec; v.sec.classList.add("on"); build(v.main, v); } });
  const FSTIP = { NTFS: "The normal Windows format.", exFAT: "Works on Windows, Mac and Linux with no 4 GB limit.", FAT32: "Works almost everywhere, but files over 4 GB do not fit.", ReFS: "A newer Windows server format." };
  let FS = null;
  const fsInfo = async () => FS || (FS = ((await api("/api/drives/advise", { method: "POST", body: { uses: [], number: 0, flag: false } })).table || []));

  // ------------------------------------------------------------ overview
  reg({ id: "drives", group: "drives", icon: "💾", label: "Overview", blurb: "Every drive: size, free space, format (NTFS, exFAT, FAT32, APFS…), health. Check, repair, optimise, format.", files: false }, (main) => {
    main.append(F.titleBlock("Your drives", "Every drive in or attached to this computer, with its format, free space and health. Actions that change a drive ask Windows for administrator permission. Drives that hold Windows or Fathom are protected and cannot be formatted from here."));
    const grid = h("div", { class: "drives" }); const jobHost = h("div"); const panel = new F.JobPanel(jobHost, { noun: "step", summary: false, renderItem: () => document.createComment(""), onDone: (s) => { const d = s.data && s.data.details; const res = (s.results[0] && (s.results[0].error || s.results[0].note)) || ""; jobHost.querySelector(".dres")?.remove(); jobHost.append(h("div", { class: "card-box dres" }, h("b", { text: res || "Finished." }), d ? h("pre", { class: "mono", style: "white-space:pre-wrap;max-height:260px;overflow:auto", text: d }) : null)); load(); } });
    const top = h("div", { class: "row" }, h("button", { class: "btn small", tip: "Reads the list of drives again.", onclick: () => load() }, "Refresh"));
    main.append(top, grid, jobHost);
    const act = async (kind, letter, params = {}) => { try { jobHost.querySelector(".dres")?.remove(); const r = await post("/api/drives/action", { kind, letter, params }); panel.start(r.job); } catch (e) { F.toast(e.message); } };
    async function load() {
      let r; try { r = await api("/api/drives"); } catch (e) { return grid.replaceChildren(h("p", { class: "hint", text: e.message })); }
      grid.replaceChildren(...r.drives.map((d) => card(d)));
      if (r.unreadable && r.unreadable.length) grid.append(h("div", { class: "warnbox", text: "Not readable by Windows: " + r.unreadable.map((u) => `${u.name} (${u.fs})`).join(", ") + ". These use a Mac or Linux format. Copy files off them on that system, or use a free driver." }));
    }
    function card(d) {
      const pct = d.size ? Math.round((d.used / d.size) * 100) : 0;
      const tags = [d.fs && h("span", { class: "tag fs", tip: FSTIP[d.fs] || "The file system: how the drive stores files.", text: d.fs }), d.kind && h("span", { class: "tag", text: d.kind }), d.bus && h("span", { class: "tag", text: d.bus }), d.health && h("span", { class: "tag " + (/healthy|ok/i.test(d.health) ? "ok" : "bad"), text: d.health }), d.bitlocker && h("span", { class: "tag", tip: "Encrypted with BitLocker.", text: "BitLocker " + d.bitlocker }), d.protected && h("span", { class: "tag", tip: "Holds Windows or Fathom, so formatting is blocked.", text: "protected" }), d.readonly && h("span", { class: "tag", text: "read-only" })].filter(Boolean);
      const acts = h("div", { class: "row" });
      if (d.ready && d.type !== "Disc") {
        acts.append(h("button", { class: "btn small", tip: "Looks for errors without changing anything (chkdsk).", onclick: () => act("scan", d.letter) }, "Check"),
          h("button", { class: "btn small", tip: "Repairs file system errors. The drive may be unavailable for a while.", onclick: () => confirm(`Repair drive ${d.letter}?`) && act("repair", d.letter) }, "Repair"),
          h("button", { class: "btn small", tip: "SSDs get a TRIM (keeps them fast). Hard drives get defragmented. Fathom picks the right one.", onclick: () => act("optimize", d.letter, { mode: "auto" }) }, "Optimise"),
          h("button", { class: "btn small", tip: "Changes the drive's name.", onclick: () => { const n = prompt("New name for the drive:", d.label || ""); if (n !== null) act("label", d.letter, { label: n }); } }, "Rename"));
        if (/^FAT/i.test(d.fs || "")) acts.append(h("button", { class: "btn small", tip: "Changes FAT or FAT32 into NTFS without erasing anything. Cannot be undone without formatting.", onclick: () => confirm(`Convert ${d.letter} to NTFS? Files are kept.`) && act("to_ntfs", d.letter) }, "Convert to NTFS"));
        if (d.type === "Removable") acts.append(h("button", { class: "btn small", tip: "Safely prepares the drive so you can unplug it.", onclick: () => act("eject", d.letter) }, "Eject"));
        acts.append(h("button", { class: "btn small", tip: "Overwrites the free space so deleted files can no longer be recovered. Your files stay.", onclick: () => confirm(`Wipe free space on ${d.letter}? This can take hours on big drives.`) && act("wipe", d.letter) }, "Wipe free space"));
        if (!d.protected) acts.append(h("button", { class: "btn small danger", tip: "Erases the whole drive and sets it up again with the format you choose.", onclick: () => formatDialog(d) }, "Format…"));
      }
      return h("div", { class: "drive" }, h("div", { class: "dh" }, h("b", { text: `${d.letter}  ${d.label || ""}` }), h("small", { text: d.type + (d.disk_name ? " · " + d.disk_name : "") })),
        h("div", { class: "usage", tip: "The filled part is used space." }, h("i", { style: `width:${pct}%` })), h("small", { text: d.ready ? `${F.fmtBytes(d.used)} used of ${F.fmtBytes(d.size)} · ${F.fmtBytes(d.free)} free` : "Not ready" }), h("div", { class: "tags" }, ...tags), acts);
    }
    function formatDialog(d) {
      const box = h("div", { class: "card-box dangerbox" });
      const fs = h("select", {}, ...["exFAT", "NTFS", "FAT32", "ReFS"].map((x) => h("option", { value: x, text: x })));
      F.tip(fs, (() => `exFAT: Windows, Mac and Linux, no 4 GB limit.\nNTFS: Windows only, safest and fullest.\nFAT32: works on everything (TVs, cameras), but no file over 4 GB, and at most 32 GB here.\nReFS: Windows server format.`)());
      const lab = h("input", { type: "text", value: d.label || "", maxlength: 32 }); const conf = h("input", { type: "text", placeholder: d.letter, style: "width:70px" }); const full = h("input", { type: "checkbox" });
      F.tip(conf, "A safety check: type the drive letter to prove you mean it."); F.tip(full, "On: also writes over every sector (slow, thorough).\nOff: quick format (seconds).");
      box.append(h("h3", { text: `Format drive ${d.letter}` }), h("p", { text: "Everything on the drive will be erased." }), h("div", { class: "field" }, h("label", { text: "New format" }), fs), h("div", { class: "field" }, h("label", { text: "Name" }), lab), h("label", {}, full, "Full format (slow, writes everywhere)"), h("div", { class: "field" }, h("label", { text: `Type the drive letter (${d.letter}) to confirm` }), conf),
        h("div", { class: "row" }, h("button", { class: "primary warn", onclick: () => { act("format", d.letter, { fs: fs.value, label: lab.value, confirm: conf.value, full: full.checked }); box.remove(); } }, "Erase and format"), h("button", { class: "btn", onclick: () => box.remove() }, "Cancel")));
      grid.before(box);
    }
    load();
  });

  // ------------------------------------------------------------ space map
  reg({ id: "space", group: "drives", icon: "🗺", label: "Space map", blurb: "See what takes up the room on a drive or in a folder: biggest folders, biggest files, kinds of files and wasted space.", files: false }, (main) => {
    main.append(F.titleBlock("Space map", "Measures a drive or folder and shows where the room went: the biggest folders and files, which kinds of files fill it, and 'slack' (room lost because drives store files in fixed-size blocks)."));
    const box = h("input", { type: "text", placeholder: "C:\\   or any folder", style: "flex:1" }); F.tip(box, "The drive or folder to measure.");
    const pick = h("button", { class: "btn small", onclick: async () => { const p = await F.pickOne("folder"); if (p) box.value = p; } }, "Browse…");
    const out = h("div"); const host = h("div");
    const go = h("button", { class: "primary", tip: "Measures everything inside. Big drives take a few minutes." }, "Measure");
    main.append(h("div", { class: "row" }, box, pick, go), host, out);
    const panel = new F.JobPanel(host, { noun: "step", summary: false, renderItem: () => document.createComment(""), onDone: (s) => draw(s.data) });
    go.onclick = async () => { if (!box.value.trim()) return F.toast("Choose a folder or drive."); out.replaceChildren(); try { panel.start((await post("/api/drives/space", { path: box.value.trim() })).job); } catch (e) { F.toast(e.message); } };
    function draw(d) {
      if (!d || !d.children) return;
      const max = Math.max(1, ...d.children.map((c) => c.bytes));
      out.append(h("div", { class: "card-box" }, h("h3", { text: `${d.files.toLocaleString()} files · ${F.fmtBytes(d.total)}` }), h("p", { class: "hint", text: `Wasted to block rounding (slack): about ${F.fmtBytes(d.slack)}` + (d.denied ? ` · ${d.denied} folders could not be read` : "") })),
        h("div", { class: "card-box" }, h("h3", { text: "Biggest folders" }), ...d.children.slice(0, 25).map((c) => h("div", { class: "treerow" }, h("div", { class: "tb", style: `width:${Math.max(2, c.bytes / max * 100)}%` }), h("span", { text: `${F.baseName(c.path)}  ·  ${F.fmtBytes(c.bytes)}`, title: c.path })))),
        h("div", { class: "card-box" }, h("h3", { text: "Kinds of files" }), h("div", { class: "tags" }, ...d.types.map((t) => h("span", { class: "tag fs", text: `${(F.CAT_LABEL && F.CAT_LABEL[t.category]) || t.category} · ${F.fmtBytes(t.bytes)}` })))),
        h("div", { class: "card-box" }, h("h3", { text: "Biggest files" }), h("table", { class: "tbl" }, ...d.biggest.slice(0, 30).map((f) => h("tr", {}, h("td", {}, h("button", { class: "link", onclick: () => F.reveal(f.path) }, F.baseName(f.path))), h("td", { text: F.fmtBytes(f.bytes) }), h("td", { class: "hint", text: f.path }))))));
    }
  });

  // ------------------------------------------------------------ compatibility
  reg({ id: "compat", group: "drives", icon: "🧪", label: "Will it fit?", blurb: "Check your files against a format (FAT32, exFAT, NTFS, APFS, ext4) before copying, and fix names that would fail.", files: true, hint: "Add the files or folders you plan to copy." }, async (main) => {
    main.append(F.titleBlock("Will my files work there?", "Different drive formats have different rules: FAT32 cannot hold files over 4 GB, and Windows formats reject some characters and names. Check before you copy, then let Fathom fix names that would fail (it keeps a list so you can undo)."));
    const form = F.form([{ id: "fs", type: "select", label: "Drive format to check against", value: "exFAT", options: [{ v: "FAT32", l: "FAT32" }, { v: "exFAT", l: "exFAT" }, { v: "NTFS", l: "NTFS" }, { v: "APFS", l: "APFS (Mac)" }, { v: "ext4", l: "ext4 (Linux)" }], tip: "The format of the drive you want to copy to." }]);
    main.append(h("div", { class: "card-box" }, form.el));
    const out = h("div"), host = h("div"); let id = null;
    const go = h("button", { class: "primary", tip: "Looks at every file name and size. Nothing is changed." }, "Check my files");
    main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host, out);
    const panel = new F.JobPanel(host, { noun: "step", summary: false, renderItem: () => document.createComment(""), onDone: (s) => { id = s.id; draw(s.data); } });
    go.onclick = async () => { if (!F.needFiles()) return; out.replaceChildren(); try { panel.start((await post("/api/drives/compat", { paths: F.state.sources, fs: form.values().fs })).job); } catch (e) { F.toast(e.message); } };
    function draw(d) {
      const iss = d.issues || [];
      if (!iss.length) return out.replaceChildren(h("div", { class: "card-box" }, h("b", { text: `All ${d.checked} items fit.` })));
      out.replaceChildren(h("div", { class: "card-box" }, h("h3", { text: `${iss.length} problem${iss.length === 1 ? "" : "s"} in ${d.checked} items` }), d.fixable ? h("button", { class: "primary", tip: "Renames the files that have bad characters or names so they fit. Use Undo at the top to take it back.", onclick: async () => { try { const r = await post("/api/drives/compat/fix", { job: id }); F.toast(`Fixed ${r.fixed ?? r.renamed ?? ""} names`); F.refreshUndo && F.refreshUndo(); out.replaceChildren(); } catch (e) { F.toast(e.message); } } }, `Fix ${d.fixable} names`) : null,
        h("table", { class: "tbl" }, h("tr", {}, ["Name", "Problem", "Would become"].map((x) => h("th", { text: x }))), ...iss.slice(0, 500).map((i) => h("tr", {}, h("td", { text: i.name, title: i.path }), h("td", { text: i.problem }), h("td", { text: i.new || (i.fixable ? "" : "can't be fixed by renaming") }))))));
    }
  });

  // ------------------------------------------------------------ speed-ups
  reg({ id: "tune", group: "drives", icon: "⚡", label: "Speed up", blurb: "Safe NTFS tweaks, folder compression and mounting disk images.", files: false }, async (main) => {
    main.append(F.titleBlock("Speed up and save space", "Windows only. These are well-known, safe settings. Each one shows whether it is already on. Changing them asks for administrator permission."));
    const list = h("div", { class: "card-box" }); const comp = h("div", { class: "card-box" }); const img = h("div", { class: "card-box" });
    main.append(list, comp, img);
    async function load() {
      const r = await api("/api/drives/tune");
      if (!r.windows) return list.replaceChildren(h("p", { class: "hint", text: "These tweaks are for Windows (NTFS) drives." }));
      const boxes = r.items.map((i) => { const c = h("input", { type: "checkbox" }); c.checked = i.tuned; c.disabled = i.tuned || !i.known; return [i, c]; });
      list.replaceChildren(h("h3", { text: "NTFS settings" }), ...boxes.map(([i, c]) => h("label", { style: "display:block;padding:3px 0", tip: i.text }, c, ` ${i.text}`, h("small", { text: i.tuned ? "  ✓ already on" : "" }))),
        h("button", { class: "primary", style: "margin-top:10px", tip: "Applies the ticked settings. A restart may be needed.", onclick: async () => { const keys = boxes.filter(([i, c]) => c.checked && !i.tuned).map(([i]) => i.key); if (!keys.length) return F.toast("Nothing new ticked."); try { const x = await post("/api/drives/tune", { keys }); F.toast("Applied. Restart Windows for all changes to take effect."); load(); } catch (e) { F.toast(e.message); } } }, "Apply ticked"));
    }
    const folder = h("input", { type: "text", placeholder: "folder to compress", style: "flex:1" }), fb = h("button", { class: "btn small", onclick: async () => { const p = await F.pickOne("folder"); if (p) folder.value = p; } }, "Browse…");
    const strength = h("select", {}, ...[["light", "Light (fast)"], ["balanced", "Balanced"], ["max", "Smallest (slow)"]].map(([v, l]) => h("option", { value: v, text: l }))); strength.value = "balanced"; F.tip(strength, "Light: quick, saves a little.\nSmallest: saves the most, uses more of the processor.");
    comp.append(h("h3", { text: "Compress a folder in place" }), h("p", { class: "hint", text: "Windows shrinks the files on the drive itself. They still open normally. Good for folders you rarely change." }), h("div", { class: "row" }, folder, fb, strength),
      h("div", { class: "row" }, h("button", { class: "btn", tip: "Compresses the folder using NTFS compression.", onclick: async () => { try { const r = await post("/api/drives/compress", { path: folder.value, flag: false, text: strength.value }); runJob(r.job, comp); } catch (e) { F.toast(e.message); } } }, "Compress"), h("button", { class: "btn", tip: "Turns compression off again for the folder.", onclick: async () => { try { const r = await post("/api/drives/compress", { path: folder.value, flag: true }); runJob(r.job, comp); } catch (e) { F.toast(e.message); } } }, "Undo compression")));
    const imgp = h("input", { type: "text", placeholder: "ISO / VHD / VHDX file", style: "flex:1" }), ib = h("button", { class: "btn small", onclick: async () => { const p = await F.pickOne("files"); if (p) imgp.value = p; } }, "Browse…");
    img.append(h("h3", { text: "Mount a disk image" }), h("p", { class: "hint", text: "Makes an ISO, VHD or VHDX appear as a drive in Windows. To just copy files out without mounting, use Lab → Disk images." }), h("div", { class: "row" }, imgp, ib),
      h("div", { class: "row" }, h("button", { class: "btn", onclick: async () => { try { runJob((await post("/api/drives/image", { path: imgp.value, flag: true })).job, img); } catch (e) { F.toast(e.message); } } }, "Mount"), h("button", { class: "btn", onclick: async () => { try { runJob((await post("/api/drives/image", { path: imgp.value, flag: false })).job, img); } catch (e) { F.toast(e.message); } } }, "Unmount")));
    function runJob(id, where) { const host = h("div"); where.append(host); const p = new F.JobPanel(host, { noun: "step", summary: false, onDone: () => load() }); p.start(id); }
    load().catch((e) => list.replaceChildren(h("p", { class: "hint", text: e.message })));
  });

  // ------------------------------------------------------------ Linux file systems (only where the system can really make them)
  reg({ id: "fsother", group: "drives", icon: "🐧", label: "Linux formats", blurb: "Make ext4, Btrfs, XFS, F2FS or ZFS, only on systems that can really do it (Linux, or a disk image through WSL on Windows).", files: false, output: true }, async (main) => {
    main.append(F.titleBlock("Linux file systems", "ext2/3/4, Btrfs, XFS, F2FS and ZFS. Windows cannot make these itself, and neither can macOS, so Fathom only offers what your system can really do: on Linux it can format a disk partition or make a disk image file; on Windows it can make a formatted disk image file through WSL (Windows Subsystem for Linux), if that is installed. Formats your system cannot make are greyed out with the reason."));
    let caps; try { caps = await api("/api/drives/fs/caps"); } catch (e) { return main.append(h("p", { class: "hint", text: e.message })); }
    const any = caps.formats.some((f) => f.available);
    main.append(h("div", { class: "card-box" }, h("b", { text: `This computer: ${caps.platform === "windows" ? "Windows" + (caps.wsl ? " with WSL" : " without WSL") : caps.platform === "mac" ? "macOS" : "Linux"}` }), h("div", { class: "tags" }, ...caps.formats.map((f) => h("span", { class: "tag " + (f.available ? "ok" : ""), tip: f.available ? "Available here." : f.why, text: (f.available ? "✓ " : "✗ ") + f.label })))));
    if (!any) return main.append(h("div", { class: "warnbox", text: caps.formats[0].why }));
    const canDev = caps.platform === "linux";
    const form = F.form([
      { id: "kind", type: "choice", label: "Make", value: "image", options: [{ v: "image", l: "A disk image file", s: "safe, nothing is erased", tip: "Creates a new .img file that is already formatted. It takes almost no space until it is filled. You can mount it in Linux or WSL." }, ...(canDev ? [{ v: "device", l: "Format a real disk", s: "erases it, Linux only", tip: "Erases a disk partition and sets it up with the new format. Needs root. Only unmounted partitions are offered." }] : [])] },
      { id: "fs", type: "select", label: "File system", value: (caps.formats.find((f) => f.available) || {}).id, options: caps.formats.filter((f) => f.available).map((f) => ({ v: f.id, l: f.label })), tip: "ext4: the normal Linux format.\nBtrfs: snapshots and checksums.\nXFS: very large files and servers.\nF2FS: made for flash drives.\nZFS: pools for storage servers (real disks only)." },
      { id: "name", type: "text", label: "Image file name", placeholder: "my-disk", show: (v) => v.kind === "image", tip: "The name of the new image file." },
      { id: "size", type: "number", label: "Image size", value: 512, min: 8, unit: "MB", show: (v) => v.kind === "image", tip: "How big the disk image is. It only takes real room as files are added.\nLow: small, fills quickly.\nHigh: more room." },
      { id: "dev", type: "select", label: "Partition", value: "", show: (v) => v.kind === "device", options: [{ v: "", l: "Choose…" }, ...caps.devices.map((d) => ({ v: d.path, l: `${d.path}  ·  ${F.fmtBytes(d.size)}  ${d.fs ? "· " + d.fs : ""} ${d.label || ""}` }))], tip: "Only unmounted partitions that are not used by the system are listed." },
      { id: "label", type: "text", label: "Name of the disk (optional)", tip: "A short name shown when the disk is mounted." },
      { id: "confirm", type: "text", label: "Type the partition name to confirm", placeholder: "/dev/sdb1", show: (v) => v.kind === "device", tip: "A safety check so a disk can never be erased by accident. Type it exactly." }]);
    main.append(h("div", { class: "card-box" }, form.el));
    const host = h("div"); const go = h("button", { class: "primary", tip: "Makes the image or formats the disk." }, "Go"); main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
    const panel = new F.JobPanel(host, { noun: "step", onDone: () => (go.disabled = false) });
    go.onclick = async () => { const v = form.values(); if (v.kind === "device" && !confirm(`Erase ${v.dev} and format it as ${v.fs}? This cannot be undone.`)) return;
      try { go.disabled = true; const r = await post("/api/drives/fs/format", { text: v.fs, action: v.kind, number: +v.size || 0, path: v.dev || "", output: F.outputBody(), options: { name: v.name || "", label: v.label || "", confirm: v.confirm || "" } }); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); } };
  });

  // ------------------------------------------------------------ guide
  reg({ id: "fsguide", group: "drives", icon: "📚", label: "Which format?", blurb: "Answer a few questions and get the right drive format, with a plain comparison of NTFS, exFAT, FAT32, APFS and more.", files: false }, async (main) => {
    main.append(F.titleBlock("Which format should I use?", "Tick everything the drive will be used with. Fathom suggests the best format and explains why."));
    const form = F.form([{ id: "uses", type: "multi", label: "The drive will be used with", value: ["windows"], options: [{ v: "windows", l: "Windows PCs" }, { v: "mac", l: "Macs" }, { v: "linux", l: "Linux" }, { v: "tv", l: "A TV" }, { v: "camera", l: "A camera" }, { v: "console", l: "A game console" }, { v: "car", l: "A car stereo" }, { v: "internal", l: "Only as a fixed drive inside this PC" }, { v: "ssd", l: "It is an SSD" }] },
      { id: "size", type: "number", label: "Drive size", value: 128, unit: "GB", tip: "FAT32 cannot be created above 32 GB in Windows." }, { id: "big", type: "check", label: "I have single files over 4 GB (videos, disk images)", value: false, tip: "FAT32 cannot store a single file over 4 GB." }]);
    const out = h("div"); main.append(h("div", { class: "card-box" }, form.el, h("button", { class: "primary", onclick: ask }, "Suggest a format")), out);
    async function ask() { const v = form.values(); try { const r = await post("/api/drives/advise", { uses: v.uses, number: +v.size || 0, flag: v.big }); out.replaceChildren(h("div", { class: "card-box" }, h("h3", { text: "Use " + r.best }), h("p", { text: r.info.simple }), h("ul", {}, ...r.reasons.map((x) => h("li", { text: x }))), r.alternative ? h("p", { class: "hint", text: "Other option: " + r.alternative }) : null), table(r.table)); } catch (e) { F.toast(e.message); } }
    function table(t) { return h("div", { class: "card-box" }, h("h3", { text: "All formats side by side" }), h("table", { class: "tbl" }, h("tr", {}, ["Format", "Windows", "Mac", "Linux", "TVs and cameras", "Biggest file"].map((x) => h("th", { text: x }))), ...t.map((i) => h("tr", {}, h("td", {}, h("b", { text: i.name }), h("div", { class: "hint", text: i.best })), h("td", { text: i.windows }), h("td", { text: i.mac }), h("td", { text: i.linux }), h("td", { text: i.tv }), h("td", { text: i.max_file }))))); }
    ask();
  });
})();
