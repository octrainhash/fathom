/* Everyday extras: Compare, QR codes, Picture touch-up, Hex view, Redact. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  const post = (p, b) => api(p, { method: "POST", body: b });
  const reg = (t, build) => F.addTool({ ...t, el: F.makeView(t.id), build: (sec) => { const v = F.standardView(t.id, { files: !!t.files, output: !!t.output, hint: t.hint }); sec.replaceWith(v.sec); F.tools.find((x) => x.id === t.id).el = v.sec; v.sec.classList.add("on"); build(v.main, v); } });
  function runBar(main, label, tipText, start, panelOpts = {}) {
    const go = h("button", { class: "primary", tip: tipText }, label); const host = h("div");
    const panel = new F.JobPanel(host, { ...panelOpts, onDone: (s, items) => { go.disabled = false; panelOpts.onDone && panelOpts.onDone(s, items); } });
    main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
    go.onclick = async () => { try { go.disabled = true; const r = await start(); if (r) panel.start(r.job); else go.disabled = false; } catch (e) { go.disabled = false; F.toast(e.message); } };
    return { go, panel, host };
  }
  /** a text box with Browse buttons for a file and/or folder */
  function pathPick(label, tipText, { file = true, folder = false } = {}) {
    const box = h("input", { type: "text", placeholder: "Choose…", spellcheck: "false", style: "flex:1;min-width:200px" }); F.tip(box, tipText);
    const row = h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, box);
    if (file) row.append(h("button", { class: "btn small", tip: "Choose a file.", onclick: async () => { const p = await F.pickOne("files"); if (p) box.value = p; } }, "File…"));
    if (folder) row.append(h("button", { class: "btn small", tip: "Choose a folder.", onclick: async () => { const p = await F.pickOne("folder"); if (p) box.value = p; } }, "Folder…"));
    return { el: h("div", { class: "field" }, h("div", { class: "lab", text: label }), row), get: () => box.value.trim(), set: (v) => (box.value = v) };
  }
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // ================================================================== COMPARE
  reg({ id: "compare", group: "tidy", icon: "⚖️", label: "Compare", blurb: "See exactly what is different between two files or two folders: changed words, changed pictures, changed bytes.", files: false, output: false }, (main) => {
    main.append(F.titleBlock("Compare", "Choose two files (or two folders). For text and documents Fathom shows which lines were added and removed. For pictures it highlights what changed. For any other file it shows where the first difference is. For folders it lists what is only on one side and what differs."));
    const a = pathPick("First (left)", "The original or older one.", { file: true, folder: true }), b = pathPick("Second (right)", "The new one to compare it with.", { file: true, folder: true });
    const form = F.form([{ id: "ignore_space", type: "check", label: "Ignore extra spaces", value: false, tip: "On: lines that differ only in spaces count as the same.\nOff: every space matters." }]);
    main.append(h("div", { class: "card-box" }, a.el, b.el, form.el));
    const out = h("div");
    const r = runBar(main, "Compare", "Compares the two choices. Nothing is changed.", async () => { if (!a.get() || !b.get()) { F.toast("Choose both."); return null; } out.replaceChildren(); return post("/api/tools/compare", { a: a.get(), b: b.get(), options: form.values() }); },
      { noun: "comparison", summary: false, renderItem: () => document.createComment(""), onDone: (s) => draw(s.data && s.data.result) });
    main.append(out);
    function list(title, arr, cls) { return arr.length ? h("div", { class: "card-box" }, h("h3", { text: `${title} (${arr.length})` }), h("div", { class: "mono smalllist " + (cls || "") }, arr.slice(0, 300).map((x) => h("div", { text: typeof x === "string" ? x : `${x.path}   (${F.fmtBytes(x.size_a)} → ${F.fmtBytes(x.size_b)}, newer: ${x.newer === "a" ? "left" : "right"})` })))) : null; }
    function draw(res) {
      if (!res) return;
      const box = h("div", {}, h("div", { class: "card-box" }, h("h3", { text: res.same ? "✅ Identical" : "Result" }), h("p", { text: res.summary })));
      if (res.kind === "text" && res.lines && res.lines.length) box.append(h("div", { class: "card-box" }, h("div", { class: "diff mono" }, res.lines.map((l) => h("div", { class: l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : "", text: l || " " }))), res.truncated ? h("p", { class: "hint", text: "Only the first part is shown." }) : null));
      if (res.kind === "image" && res.diff) box.append(h("div", { class: "card-box" }, h("img", { src: res.diff, alt: "differences", style: "max-width:100%;border-radius:10px" })));
      if (res.kind === "folders") box.append(list("Only on the left", res.only_a), list("Only on the right", res.only_b), list("Different", res.different));
      out.replaceChildren(box);
    }
  });

  // ================================================================== QR
  reg({ id: "qr", group: "edit", icon: "▦", label: "QR codes", blurb: "Make a QR code (a link, text, or Wi-Fi login) or read the QR codes in pictures.", files: true, output: true, hint: "To READ QR codes, add pictures here." }, (main) => {
    main.append(F.titleBlock("QR codes", "Make a QR code to scan with a phone, or read the QR codes hiding in pictures (add them on the left and press 'Read QR codes')."));
    const form = F.form([
      { id: "kind", type: "choice", label: "What should it say?", value: "text", options: [{ v: "text", l: "Link or text", tip: "Any web address or text." }, { v: "wifi", l: "Wi-Fi login", tip: "Phones that scan it join the Wi-Fi without typing the password." }] },
      { id: "text", type: "textarea", label: "Text or link", rows: 3, placeholder: "https://example.com", show: (v) => v.kind === "text", tip: "What the code says when it is scanned." },
      { id: "ssid", type: "text", label: "Wi-Fi name", show: (v) => v.kind === "wifi", tip: "The name of the Wi-Fi network." },
      { id: "pw", type: "text", label: "Wi-Fi password", show: (v) => v.kind === "wifi", tip: "The Wi-Fi password." },
      { id: "sec", type: "select", label: "Security", value: "WPA", show: (v) => v.kind === "wifi", options: [{ v: "WPA", l: "WPA / WPA2 / WPA3" }, { v: "WEP", l: "WEP" }, { v: "nopass", l: "No password" }], tip: "Almost every home network is WPA." },
      { id: "ecc", type: "select", label: "Error correction", value: "M", options: [{ v: "L", l: "Low (smallest)" }, { v: "M", l: "Medium" }, { v: "Q", l: "High" }, { v: "H", l: "Highest (works even if damaged)" }], tip: "Higher: the code still works when scratched or partly covered, but it is denser." },
      { id: "dark", type: "select", label: "Colour", value: "#000000", options: [{ v: "#000000", l: "Black" }, { v: "#1f2a6b", l: "Navy" }, { v: "#0b6b3a", l: "Green" }, { v: "#7a1f1f", l: "Dark red" }], tip: "Keep it dark on a light background so phones can read it." }], () => preview());
    const img = h("img", { alt: "QR code", style: "max-width:260px;background:#fff;border-radius:10px;display:none" });
    const text = (v) => (v.kind === "wifi" ? `WIFI:T:${v.sec};S:${v.ssid.replace(/([\\;,:"])/g, "\\$1")};P:${v.pw.replace(/([\\;,:"])/g, "\\$1")};;` : v.text);
    let seq = 0, timer;
    const preview = () => { clearTimeout(timer); timer = setTimeout(async () => { const v = form.values(); const t = text(v); if (!t.trim() || (v.kind === "wifi" && !v.ssid)) { img.style.display = "none"; return; } const my = ++seq; try { const r = await post("/api/tools/qr/make", { text: t, options: { scale: 8, ecc: v.ecc, dark: v.dark } }); if (my === seq) { img.src = r.png; img.style.display = ""; } } catch (e) { img.style.display = "none"; } }, 300); };
    main.append(h("div", { class: "card-box" }, h("h3", { text: "Make a QR code" }), form.el, h("div", { style: "margin-top:12px" }, img)));
    runBar(main, "Save the QR code", "Saves the QR code as a picture in the folder chosen on the left.", async () => { const v = form.values(); const t = text(v); if (!t.trim()) { F.toast("Type what it should say."); return null; } return post("/api/tools/qr/save", { text: t, name: "QR code", options: { scale: 12, ecc: v.ecc, dark: v.dark }, output: F.outputBody() }); }, { noun: "file" });
    const rd = h("div", { class: "card-box" }, h("h3", { text: "Read QR codes" }), h("p", { class: "hint", text: "Add pictures (photos or screenshots) on the left, then press the button." })); main.append(rd);
    runBar(main, "Read QR codes", "Looks for QR codes in every picture on the left and shows what they say.", async () => (F.needFiles() ? post("/api/tools/qr/read", { paths: F.state.sources, recursive: true }) : null), { noun: "picture", renderItem: (r) => { const codes = (r.extra && r.extra.codes) || []; return h("div", { class: "job " + (codes.length ? "done" : "skipped") }, h("div", { class: "ico", text: "▦" }), h("div", { class: "t" }, h("b", { text: r.name }), ...(codes.length ? codes.map((c) => h("div", { class: "snip" }, h("span", { class: "mono", text: c }), " ", h("button", { class: "btn small", tip: "Copies what the QR code says.", onclick: () => F.copy(c) }, "Copy"))) : [h("small", { text: r.note })]))); } });
  });

  // ================================================================== TOUCH-UP
  reg({ id: "touchup", group: "edit", icon: "🎨", label: "Touch up", blurb: "Quick fixes for many pictures at once: crop to a shape, brighten, sharpen, black and white, add a border, round the corners.", files: true, output: true, hint: "Add the pictures to touch up." }, (main) => {
    main.append(F.titleBlock("Touch up pictures", "Choose what you want and Fathom applies it to every picture on the left. Your originals are not changed; the new pictures end in _touched."));
    const form = F.form([
      { id: "ratio", type: "select", label: "Crop to a shape", value: "", options: [{ v: "", l: "Keep the shape" }, { v: "1:1", l: "Square (1:1)" }, { v: "4:3", l: "4:3" }, { v: "3:2", l: "3:2 (photo)" }, { v: "16:9", l: "16:9 (screen)" }, { v: "9:16", l: "9:16 (phone, tall)" }, { v: "3:4", l: "3:4 (tall)" }, { v: "2:3", l: "2:3 (tall photo)" }, { v: "5:4", l: "5:4" }, { v: "A4", l: "A4 page (tall)" }, { v: "A4 wide", l: "A4 page (wide)" }], tip: "Cuts the picture to this shape, keeping the middle." },
      { id: "trim", type: "range", label: "Trim the edges", min: 0, max: 40, value: 0, fmt: (v) => v + "% off each side", tip: "Cuts a slice off every edge. 0 keeps everything." },
      { id: "auto", type: "check", label: "Fix the lighting automatically", value: false, tip: "On: stretches the dark and bright parts so flat, hazy pictures get more punch." },
      { id: "brightness", type: "range", label: "Brightness", min: -80, max: 80, value: 0, fmt: (v) => (v > 0 ? "+" : "") + v, tip: "Negative: darker.\nPositive: brighter." },
      { id: "contrast", type: "range", label: "Contrast", min: -80, max: 80, value: 0, fmt: (v) => (v > 0 ? "+" : "") + v, tip: "Negative: softer, flatter.\nPositive: darks darker and lights lighter." },
      { id: "saturation", type: "range", label: "Colour strength", min: -100, max: 100, value: 0, fmt: (v) => (v > 0 ? "+" : "") + v, tip: "Negative: paler colours.\nPositive: richer colours." },
      { id: "sharpen", type: "range", label: "Sharpen", min: 0, max: 100, value: 0, fmt: (v) => v, tip: "Higher makes edges crisper. Too much looks harsh." },
      { id: "look", type: "select", label: "Look", value: "", options: [{ v: "", l: "As it is" }, { v: "gray", l: "Black and white photo" }, { v: "bw", l: "Pure black and white" }, { v: "sepia", l: "Old brown photo" }, { v: "invert", l: "Negative (inverted)" }], tip: "Changes the colours of the whole picture." },
      { id: "border", type: "number", label: "Border", value: 0, min: 0, max: 400, unit: "pixels", tip: "Adds a frame around the picture. 0 for none." },
      { id: "border_color", type: "select", label: "Border colour", value: "#ffffff", show: (v) => v.border > 0, options: [{ v: "#ffffff", l: "White" }, { v: "#000000", l: "Black" }, { v: "#f4e3c1", l: "Cream" }, { v: "#7c6cff", l: "Violet" }], tip: "The colour of the frame." },
      { id: "round", type: "range", label: "Round the corners", min: 0, max: 100, value: 0, fmt: (v) => (v ? v + "%" : "off"), tip: "Higher: rounder corners. 100 makes a circle on a square picture. Saved as PNG-friendly see-through corners (JPEG pictures get white corners)." }]);
    main.append(h("div", { class: "card-box" }, form.el));
    const lp = F.livePreview({ tool: "touchup", options: () => form.values() }); main.append(lp.el); form.el.addEventListener("input", lp.update); form.el.addEventListener("change", lp.update); form.el.addEventListener("click", () => setTimeout(lp.update, 0));
    runBar(main, "Touch up", "Makes a touched-up copy of every picture on the left.", async () => (F.needFiles() ? post("/api/tools/touchup", { paths: F.state.sources, recursive: true, options: form.values(), output: F.outputBody() }) : null), { noun: "picture" });
  });

  // ================================================================== HEX
  reg({ id: "hex", group: "lab", icon: "🔢", label: "Hex view", blurb: "Look at the raw bytes of any file, search for bytes or words, and make a patched copy.", files: false, output: true }, (main) => {
    main.append(F.titleBlock("Hex view", "Every file is just bytes. See them in hex and as text, jump to a place, search, and make a patched COPY with the bytes you choose (the original is never changed, and the file's length never changes)."));
    const f = pathPick("File", "The file to look inside.", { file: true });
    const off = h("input", { type: "number", value: 0, min: 0, style: "width:140px", tip: "Where to start looking, counted in bytes from the start of the file. Use the search to find a place." });
    const go = h("button", { class: "primary", tip: "Shows the bytes from this place." }, "Show");
    const prev = h("button", { class: "btn small", tip: "The 4,096 bytes before." }, "◀ Previous"), next = h("button", { class: "btn small", tip: "The next 4,096 bytes." }, "Next ▶");
    const q = h("input", { type: "text", placeholder: "text or hex bytes (4D 5A)", style: "flex:1;min-width:180px", tip: "What to search for." });
    const qm = h("select", { tip: "Whether the search box holds text or hex bytes." }, h("option", { value: "text", text: "Text" }), h("option", { value: "hex", text: "Hex bytes" }));
    const findBtn = h("button", { class: "btn small", tip: "Finds the next places where it appears." }, "Find");
    const info = h("p", { class: "hint" }); const table = h("div", { class: "hexrows mono" }); const hits = h("div", { class: "hint" });
    main.append(h("div", { class: "card-box" }, f.el, h("div", { class: "row", style: "gap:8px;flex-wrap:wrap" }, h("label", {}, "Start at byte ", off), go, prev, next), h("div", { class: "row", style: "gap:8px;margin-top:8px;flex-wrap:wrap" }, q, qm, findBtn), hits), info, h("div", { class: "card-box" }, table));
    let size = 0;
    async function view(o) { if (!f.get()) return F.toast("Choose a file."); try { const r = await post("/api/tools/hex/view", { path: f.get(), number: Math.max(0, o), length: 4096 }); size = r.size; off.value = r.offset; info.textContent = `${r.size.toLocaleString()} bytes in this file. Showing from byte ${r.offset.toLocaleString()} (0x${r.offset.toString(16).toUpperCase()}).`;
      table.replaceChildren(...r.rows.map((x) => h("div", { class: "hexrow" }, h("span", { class: "ofs", text: x.offset.toString(16).toUpperCase().padStart(8, "0") }), h("span", { class: "hx", text: x.hex.padEnd(47, " ") }), h("span", { class: "tx", text: x.text })))); } catch (e) { F.toast(e.message); } }
    const me = F.tools.find((x) => x.id === "hex"); me.onShow = () => { if (F.pendingHex) { f.set(F.pendingHex); F.pendingHex = ""; view(0); } }; if (F.pendingHex) me.onShow();
    go.onclick = () => view(+off.value); prev.onclick = () => view(+off.value - 4096); next.onclick = () => view(+off.value + 4096);
    findBtn.onclick = async () => { if (!f.get() || !q.value) return F.toast("Choose a file and type what to find."); try { const r = await post("/api/tools/hex/find", { path: f.get(), text: q.value, mode: qm.value, number: 0 }); hits.replaceChildren(r.hits.length ? document.createTextNode(`${r.hits.length >= 200 ? "200+" : r.hits.length} found at: `) : document.createTextNode("Not found."), ...r.hits.slice(0, 60).map((o) => h("a", { href: "#", class: "mono", style: "margin-right:8px", tip: "Shows the bytes at this place.", onclick: (e) => { e.preventDefault(); view(Math.max(0, o - 32)); } }, "0x" + o.toString(16).toUpperCase()))); } catch (e) { F.toast(e.message); } };
    // patch
    const po = h("input", { type: "text", placeholder: "byte number, e.g. 16 or 0x10", style: "width:200px", tip: "Where to change, counted in bytes from the start. You can type 0x… for hex." });
    const pv = h("input", { type: "text", placeholder: "new bytes, e.g. FF 00 2A", style: "flex:1;min-width:180px", tip: "The new bytes in hex. They replace the same number of bytes there; the file never gets longer or shorter." });
    const patches = []; const plist = h("div", { class: "hint" });
    const add = h("button", { class: "btn small", tip: "Adds this change to the list." }, "Add change");
    add.onclick = () => { const o = /^0x/i.test(po.value.trim()) ? parseInt(po.value, 16) : parseInt(po.value, 10); if (!Number.isFinite(o) || !pv.value.trim()) return F.toast("Type the byte number and the new bytes."); patches.push({ offset: o, hex: pv.value }); po.value = ""; pv.value = ""; plist.replaceChildren(...patches.map((p) => h("div", { class: "mono", text: `0x${p.offset.toString(16).toUpperCase()}  ←  ${p.hex}` }))); };
    main.append(h("div", { class: "card-box" }, h("h3", { text: "Make a patched copy" }), h("div", { class: "row", style: "gap:8px;flex-wrap:wrap" }, po, pv, add), plist));
    runBar(main, "Save the patched copy", "Makes a copy of the file with your changes. The original stays exactly as it was.", async () => { if (!f.get() || !patches.length) { F.toast("Choose a file and add a change first."); return null; } return post("/api/tools/hex/patch", { path: f.get(), items: patches, output: F.outputBody() }); }, { noun: "file" });
  });

  // ================================================================== REDACT
  reg({ id: "redact", group: "protect", icon: "⬛", label: "Redact", blurb: "Permanently black out private details (emails, phone numbers, card numbers, names you choose) in documents, PDFs, text files and pictures.", files: true, output: true, hint: "Add the files to clean." }, (main) => {
    main.append(F.titleBlock("Redact", "Hide private details for good before you share a file. Tick what to hide, add your own words, press Preview to see what would be hidden, then Redact. In Word, Excel, PowerPoint, text and other files the details are replaced with ████ (the real text is gone, not just covered). In PDFs a black box is drawn and the text underneath is removed. In pictures the words found are painted black. Your originals are not changed."));
    const KINDS = [
      { v: "email", l: "Email addresses", p: "[\\w.+-]+@[\\w-]+(?:\\.[\\w-]+)+", tip: "Things like name@example.com." },
      { v: "phone", l: "Phone numbers", p: "(?<!\\d)(?:\\+?\\d{1,3}[\\s.-]?)?(?:\\(?\\d{3}\\)?[\\s.-]?)\\d{3}[\\s.-]?\\d{4}(?!\\d)", tip: "Phone numbers in common layouts." },
      { v: "card", l: "Card numbers", p: "(?<!\\d)(?:\\d[ -]?){13,16}(?!\\d)", tip: "13 to 16 digit payment card numbers." },
      { v: "ssn", l: "Social security numbers (US)", p: "(?<!\\d)\\d{3}-\\d{2}-\\d{4}(?!\\d)", tip: "Numbers like 123-45-6789." },
      { v: "iban", l: "Bank account numbers (IBAN)", p: "\\b[A-Z]{2}\\d{2}[A-Z0-9]{11,30}\\b", tip: "International bank account numbers." },
      { v: "ip", l: "IP addresses", p: "\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b", tip: "Addresses like 192.168.0.1." },
      { v: "url", l: "Web links", p: "https?://[^\\s<>\"]+", tip: "Anything starting with http:// or https://." },
      { v: "date", l: "Dates", p: "\\b\\d{1,4}[-/.]\\d{1,2}[-/.]\\d{1,4}\\b", tip: "Dates like 2024-05-17 or 17/05/2024." }];
    const form = F.form([{ id: "kinds", type: "multi", label: "Hide these kinds of details", options: KINDS.map((k) => ({ v: k.v, l: k.l, tip: k.tip })), value: ["email", "phone"] },
      { id: "words", type: "textarea", label: "Also hide these exact words (one on each line)", rows: 3, placeholder: "a name, a project, an address…", tip: "Every time one of these appears it is blacked out. Upper and lower case do not matter." },
      { id: "pages", type: "pages", label: "Only on these PDF pages", value: "", tip: "For PDFs: only these pages are checked and blacked out. Empty = every page. Other kinds of file are always fully checked." }]);
    main.append(h("div", { class: "card-box" }, form.el));
    const pairs = () => { const v = form.values(); const p = KINDS.filter((k) => v.kinds.includes(k.v)).map((k) => ({ find: k.p, replace: "" })); for (const w of (v.words || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean)) p.push({ find: esc(w), replace: "" }); return p; };
    const body = (dry) => { const p = pairs(); if (!p.length) { F.toast("Choose what to hide first."); return null; } if (!F.needFiles()) return null; return { paths: F.state.sources, recursive: true, options: { pairs: p, regex: true, redact: true, binary: false, legacy: true, dry, pages: form.values().pages || "" }, output: F.outputBody() }; };
    const sample = (s) => h("div", { class: "snip" }, h("span", { class: "mono", text: "…" + s.before }), h("mark", { text: s.match }), h("span", { class: "mono", text: s.after + "…" }));
    const pv = runBar(main, "Preview what would be hidden", "Shows what would be blacked out in each file. Nothing is changed.", async () => { const b = body(true); return b ? post("/api/tools/replace", b) : null; },
      { noun: "file", renderItem: (r) => { const c = (r.extra && r.extra.count) || 0; return h("div", { class: "job " + (r.status === "error" ? "error" : c ? "done" : "skipped") }, h("div", { class: "ico", text: c ? "🔎" : "➖" }), h("div", { class: "t" }, h("b", { text: r.name }), h("small", { text: r.status === "error" ? r.error : r.note }), ...(((r.extra && r.extra.samples) || []).map(sample)), (r.extra && r.extra.proof && r.extra.proof.length) ? F.proofGallery(r.extra.proof, { first: 2 }) : null)); } });
    pv.go.className = "btn";
    const hostGo = h("div"); const panel = new F.JobPanel(hostGo, { noun: "file", onDone: () => { go.disabled = false; } });
    const go = h("button", { class: "primary warn", tip: "Makes a redacted copy of each file. The originals are not changed." }, "Redact now");
    pv.go.parentElement.append(go); main.append(hostGo);
    go.onclick = async () => { const b = body(false); if (!b) return; try { go.disabled = true; const r = await post("/api/tools/replace", b); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); } };
  });
})();
