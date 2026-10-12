/* The editor: open one file and change what is inside it. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  const post = (p, b) => api(p, { method: "POST", body: b });
  const KIND_LABEL = { text: "Text file", docx: "Word document", pptx: "PowerPoint", odf: "OpenDocument", xlsx: "Excel workbook", sqlite: "Database", pdf: "PDF", image: "Picture", binary: "Other file" };
  let st = null;                          // current file: {path, info, dirty, collect()}
  let ui = {};
  const dirty = (on = true) => { if (st) { st.dirty = on; ui.status && (ui.status.textContent = on ? "Unsaved changes" : ""); } };

  F.editFile = (p) => { F.pendingEdit = p; F.show("editor"); };

  F.addTool({ id: "editor", group: "edit", icon: "✏️", label: "Editor", blurb: "Open any file and change what is inside it: text and code, Word, PowerPoint, Excel cells, database rows, PDF text, and pictures (draw, write, blur, crop).", el: F.makeView("editor"),
    build: (sec) => {
      const view = F.standardView("editor", { files: true, output: true, hint: "Add a file, then press its ✏️ button, or choose it below." });
      sec.replaceWith(view.sec); const me = F.tools.find((x) => x.id === "editor"); me.el = view.sec; view.sec.classList.add("on");
      const main = view.main;
      main.append(F.titleBlock("Editor", "Open a file and change what is inside it. Text and code, Word, PowerPoint and OpenDocument paragraphs, Excel cells, database rows, the text in a PDF, or a picture (draw, write, box, blur, crop, turn). Saving makes a copy next to the original, or replaces the original (the old one goes to the Recycle Bin)."));
      const pick = h("select", { style: "min-width:220px;max-width:420px", tip: "The files you added on the left. Choose one to edit." });
      const open = h("button", { class: "primary", tip: "Opens the chosen file for editing." }, "Open");
      const browse = h("button", { class: "btn", tip: "Choose any file on this computer to edit.", onclick: async () => { const p = await F.pickOne("files"); if (p) load(p); } }, "Browse…");
      const info = h("span", { class: "chip", text: "No file open" });
      ui.status = h("span", { class: "hint", style: "margin:0 0 0 8px" });
      main.append(h("div", { class: "card-box", style: "margin-top:12px" }, h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;align-items:center" }, pick, open, browse, info, ui.status)));
      const body = h("div", { class: "edbody" }); main.append(body);
      const save = h("button", { class: "primary", tip: "Saves your changes as a new file next to the original (or in the folder chosen on the left). The original is not changed." }, "Save a copy");
      const over = h("button", { class: "btn warn", tip: "Saves your changes into the original file's place. The old version goes to the Recycle Bin so you can get it back." }, "Save over the original");
      const bar = h("div", { class: "row edsave", style: "margin-top:14px;gap:10px;position:sticky;bottom:0;padding:10px 0;background:linear-gradient(transparent,var(--bg) 40%)" }, save, over); bar.hidden = true;
      main.append(bar);
      const proofHost = h("div", { class: "card-box", style: "margin-top:12px" }); proofHost.hidden = true; main.append(proofHost);
      ui.body = body; ui.bar = bar; ui.info = info; ui.pick = pick;
      const fillPick = () => { const files = F.state.sources.filter((p) => /\.[A-Za-z0-9]{1,8}$/.test(F.baseName(p))); pick.replaceChildren(...(files.length ? files : []).map((p) => h("option", { value: p, text: F.baseName(p) })), ...(files.length ? [] : [h("option", { value: "", text: "(add a file on the left)" })])); if (st && files.includes(st.path)) pick.value = st.path; };
      const prev = F.onSourcesChanged; F.onSourcesChanged = () => { prev && prev(); fillPick(); };
      fillPick();
      open.onclick = () => pick.value && load(pick.value);
      async function doSave(replace) {
        if (!st) return;
        if (replace && !confirm("Save over the original file? The old version goes to the Recycle Bin.")) return;
        try {
          const payload = st.collect(); const r = await post("/api/editor/save", { path: st.path, kind: st.info.kind, payload, output: F.outputBody(), replace });
          proofHost.replaceChildren(); const pg = F.proofGallery(r.proof, { first: 4 }); proofHost.hidden = !pg; if (pg) proofHost.append(pg);
          dirty(false); F.toast(r.replaced ? "Saved over the original (old one is in the Recycle Bin)." : "Saved a copy."); ui.status.textContent = "Saved: " + F.baseName(r.path);
          if (r.replaced) { try { await load(st.path, true); } catch {} } else { ui.lastSaved = r.path; ui.status.replaceChildren(document.createTextNode("Saved: " + F.baseName(r.path) + "  "), h("button", { class: "btn small", tip: "Shows the saved copy in its folder.", onclick: () => F.reveal(r.path) }, "Show"), h("button", { class: "btn small", tip: "Opens the saved copy to keep editing it.", onclick: () => load(r.path, true) }, "Edit the copy")); }
        } catch (e) { F.toast(e.message); }
      }
      save.onclick = () => doSave(false); over.onclick = () => doSave(true);
      ui.load = load;
      async function load(path, force) {
        if (!force && st && st.dirty && !confirm("You have unsaved changes. Open another file anyway?")) return;
        body.replaceChildren(h("p", { class: "hint", text: "Opening…" })); bar.hidden = true; if (!force) { proofHost.hidden = true; proofHost.replaceChildren(); }
        try {
          const info = await post("/api/editor/open", { path });
          st = { path, info, dirty: false, collect: () => ({}) }; fillPick(); if (![...pick.options].some((o) => o.value === path)) pick.append(h("option", { value: path, text: F.baseName(path) })); pick.value = path;
          ui.info.textContent = `${F.baseName(path)}  ·  ${KIND_LABEL[info.kind] || info.kind}  ·  ${F.fmtBytes(info.size)}`; ui.status.textContent = "";
          body.replaceChildren(); const R = RENDER[info.kind]; if (!R) throw new Error("This kind of file cannot be edited here."); await R(body, info);
          bar.hidden = info.kind === "binary";
        } catch (e) { body.replaceChildren(h("div", { class: "warnbox", text: e.message })); st = null; }
      }
      if (F.pendingEdit) { const p = F.pendingEdit; F.pendingEdit = ""; load(p, true); }
    },
    onShow: () => { if (F.pendingEdit && ui.load) { const p = F.pendingEdit; F.pendingEdit = ""; ui.load(p); } } });

  const RENDER = {};

  // ================================================================== text
  RENDER.text = (body, info) => {
    const ta = h("textarea", { class: "edtext mono", spellcheck: "false", wrap: "off", tip: "Edit the text here. Everything is saved exactly as typed, using the file's own encoding and line endings." }); ta.value = info.text;
    const wrap = h("input", { type: "checkbox" }); wrap.onchange = () => ta.setAttribute("wrap", wrap.checked ? "soft" : "off");
    const f = h("input", { type: "text", placeholder: "Find…", tip: "Looks for this in the text." }), r = h("input", { type: "text", placeholder: "Replace with…", tip: "What to put instead." });
    const count = h("span", { class: "hint", style: "margin:0" });
    const stats = () => { count.textContent = `${ta.value.split("\n").length.toLocaleString()} lines · ${ta.value.length.toLocaleString()} characters · ${info.encoding} · ${info.newline === "crlf" ? "Windows" : "Unix"} line endings`; };
    const findNext = (dir = 1) => { if (!f.value) return; const t = ta.value.toLowerCase(), q = f.value.toLowerCase(); let i = dir > 0 ? t.indexOf(q, ta.selectionEnd) : t.lastIndexOf(q, ta.selectionStart - 1); if (i < 0) i = dir > 0 ? t.indexOf(q) : t.lastIndexOf(q); if (i < 0) return F.toast("Not found."); ta.focus(); ta.setSelectionRange(i, i + q.length); const line = ta.value.slice(0, i).split("\n").length; ta.scrollTop = Math.max(0, (line - 4) * 18); };
    const repl = () => { if (!f.value) return; const sel = ta.value.slice(ta.selectionStart, ta.selectionEnd); if (sel.toLowerCase() === f.value.toLowerCase()) { ta.setRangeText(r.value, ta.selectionStart, ta.selectionEnd, "end"); dirty(); stats(); } findNext(); };
    const replAll = () => { if (!f.value) return; const re = new RegExp(f.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"); let n = 0; ta.value = ta.value.replace(re, () => { n++; return r.value; }); F.toast(`${n} replaced`); dirty(); stats(); };
    body.append(h("div", { class: "card-box", style: "margin-top:12px" }, h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px" }, f, h("button", { class: "btn small", tip: "Jumps to the next place it appears.", onclick: () => findNext(1) }, "Next"), h("button", { class: "btn small", tip: "Jumps to the previous place.", onclick: () => findNext(-1) }, "Previous"), r, h("button", { class: "btn small", tip: "Replaces this one and moves on.", onclick: repl }, "Replace"), h("button", { class: "btn small", tip: "Replaces every one in the whole text.", onclick: replAll }, "Replace all"), h("label", { tip: "On: long lines wrap onto the next line.\nOff: long lines run off to the side." }, wrap, "Wrap lines")), ta, count));
    ta.addEventListener("input", () => { dirty(); stats(); }); stats();
    st.collect = () => ({ text: ta.value, encoding: info.encoding, newline: info.newline });
  };

  // ================================================================== paragraphs (Word, PowerPoint, OpenDocument)
  const paraEditor = (body, info) => {
    const parts = info.parts.map((p) => ({ name: p.name, label: p.label, items: p.items.map((x) => ({ i: x.i, text: x.text, orig: x.text })) }));
    const q = h("input", { type: "search", placeholder: "Show only paragraphs containing…", style: "max-width:360px", tip: "Hides the paragraphs that do not contain this, so you can find your place." });
    const host = h("div"); const LIMIT = 150;
    body.append(h("div", { class: "card-box", style: "margin-top:12px" }, q, h("p", { class: "hint", text: info.kind === "pptx" ? "Each box is one paragraph of a slide. ✕ removes it, ＋ adds a new one below." : "Each box is one paragraph. ✕ removes it, ＋ adds a new one below. Edited paragraphs keep their style (and the look of their first word)." })), host);
    const grow = (t) => { t.style.height = "auto"; t.style.height = Math.min(400, t.scrollHeight + 2) + "px"; };
    const draw = () => {
      const term = q.value.trim().toLowerCase(); host.replaceChildren();
      for (const part of parts) {
        const shown = part.items.filter((it) => !term || it.text.toLowerCase().includes(term));
        const card = h("div", { class: "card-box" }, h("h3", { text: part.label + (part.items.length ? `  (${part.items.length})` : "") })); let more = Math.min(LIMIT, shown.length);
        const list = h("div", { class: "plist" });
        const fillList = () => { list.replaceChildren(...shown.slice(0, more).map((it) => {
          const t = h("textarea", { class: "para", rows: 1, spellcheck: "true", tip: "Edit this paragraph." }); t.value = it.text; t.addEventListener("input", () => { it.text = t.value; grow(t); dirty(); });
          const row = h("div", { class: "prow" }, t, h("button", { class: "btn small", tip: "Deletes this paragraph.", onclick: () => { part.items.splice(part.items.indexOf(it), 1); dirty(); draw(); } }, "✕"), h("button", { class: "btn small", tip: "Adds a new empty paragraph below this one.", onclick: () => { part.items.splice(part.items.indexOf(it) + 1, 0, { i: -1, text: "", orig: "" }); dirty(); draw(); } }, "＋"));
          requestAnimationFrame(() => grow(t)); return row; }));
          if (more < shown.length) list.append(h("button", { class: "btn", tip: "Shows the next paragraphs.", onclick: () => { more += LIMIT; fillList(); } }, `Show more (${shown.length - more} left)`)); };
        fillList(); card.append(list);
        if (!part.items.length) card.append(h("button", { class: "btn small", tip: "Adds a first paragraph here.", onclick: () => { part.items.push({ i: -1, text: "", orig: "" }); dirty(); draw(); } }, "＋ Add a paragraph"));
        host.append(card);
      }
    };
    q.addEventListener("input", draw); draw();
    st.collect = () => ({ parts: parts.map((p) => ({ name: p.name, items: p.items.map((x) => ({ i: x.i, text: x.text })) })) });
  };
  RENDER.docx = paraEditor; RENDER.pptx = paraEditor; RENDER.odf = paraEditor;

  // ================================================================== Excel
  RENDER.xlsx = async (body, info) => {
    const cells = {}; let sheet = info.sheets[0] && info.sheets[0].name, r0 = 1, c0 = 1;
    const tabs = h("div", { class: "tabs2" }); const host = h("div", { class: "card-box edgrid" });
    body.append(h("div", { style: "margin-top:12px" }, tabs), host);
    const colName = (n) => { let s = ""; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; };
    async function draw() {
      [...tabs.children].forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.s === sheet)));
      const g = await post("/api/editor/sheet", { path: st.path, sheet, r0, c0 });
      const tbl = h("table", { class: "tbl grid" }, h("tr", {}, h("th", {}), ...g.cols.map((c) => h("th", { text: c }))));
      g.rows.forEach((row, ri) => { const rn = g.r0 + ri; tbl.append(h("tr", {}, h("th", { text: rn }), ...row.map((v, ci) => { const ref = colName(g.c0 + ci) + rn; const cur = cells[sheet] && cells[sheet][ref] !== undefined ? cells[sheet][ref] : v; const inp = h("input", { type: "text", value: cur, spellcheck: "false", class: cells[sheet] && cells[sheet][ref] !== undefined ? "chg" : "" }); inp.addEventListener("input", () => { (cells[sheet] = cells[sheet] || {})[ref] = inp.value; inp.classList.add("chg"); dirty(); }); return h("td", {}, inp); }))); });
      host.replaceChildren(h("div", { class: "row", style: "gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center" },
        h("button", { class: "btn small", tip: "Shows the rows above.", onclick: () => { r0 = Math.max(1, r0 - 100); draw(); } }, "▲ Rows"), h("button", { class: "btn small", tip: "Shows the next rows.", onclick: () => { if (r0 + 100 <= g.max_row) { r0 += 100; draw(); } } }, "▼ Rows"),
        h("button", { class: "btn small", tip: "Shows the columns to the left.", onclick: () => { c0 = Math.max(1, c0 - 26); draw(); } }, "◀ Columns"), h("button", { class: "btn small", tip: "Shows the columns to the right.", onclick: () => { if (c0 + 26 <= g.max_col) { c0 += 26; draw(); } } }, "Columns ▶"),
        h("span", { class: "hint", style: "margin:0", text: `Rows ${g.r0}–${Math.min(g.r0 + 99, g.max_row)} of ${g.max_row} · to put a formula type = first. Type into an empty cell to fill it. Charts and pictures in the workbook may not survive a save.` })), h("div", { style: "overflow:auto;max-height:60vh" }, tbl));
    }
    for (const s of info.sheets) tabs.append(h("button", { class: "choice", "data-s": s.name, tip: `Sheet "${s.name}" (${s.rows} rows, ${s.cols} columns).`, onclick: () => { sheet = s.name; r0 = 1; c0 = 1; draw(); } }, h("b", { text: s.name })));
    await draw();
    st.collect = () => ({ cells });
  };

  // ================================================================== database
  RENDER.sqlite = async (body, info) => {
    const edits = {}; let table = info.tables[0] && info.tables[0].name, off = 0;
    const tabs = h("div", { class: "tabs2" }); const host = h("div", { class: "card-box edgrid" });
    body.append(h("div", { style: "margin-top:12px" }, tabs), host);
    async function draw() {
      [...tabs.children].forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.s === table)));
      if (!table) return host.replaceChildren(h("p", { class: "hint", text: "This database has no tables." }));
      const g = await post("/api/editor/dbrows", { path: st.path, table, offset: off }); const tinfo = info.tables.find((t) => t.name === table);
      const e = (edits[table] = edits[table] || { cells: {}, delete: [] });
      const tbl = h("table", { class: "tbl grid" }, h("tr", {}, h("th", { text: "" }), ...g.columns.map((c) => h("th", { text: c })), h("th", { text: "" })));
      for (const r of g.rows) { const gone = e.delete.includes(r.rowid); tbl.append(h("tr", { class: gone ? "gone" : "" }, h("th", { text: r.rowid ?? "" }), ...r.values.map((v, ci) => { const col = g.columns[ci]; const cur = e.cells[r.rowid] && e.cells[r.rowid][col] !== undefined ? e.cells[r.rowid][col] : v; const inp = h("input", { type: "text", value: cur, disabled: r.blob[ci] || !g.has_rowid, spellcheck: "false", class: e.cells[r.rowid] && e.cells[r.rowid][col] !== undefined ? "chg" : "" }); inp.addEventListener("input", () => { (e.cells[r.rowid] = e.cells[r.rowid] || {})[col] = inp.value; inp.classList.add("chg"); dirty(); }); return h("td", {}, inp); }),
        h("td", {}, g.has_rowid ? h("button", { class: "btn small", tip: gone ? "Keeps this row after all." : "Marks this row to be deleted when you save.", onclick: () => { gone ? e.delete.splice(e.delete.indexOf(r.rowid), 1) : e.delete.push(r.rowid); dirty(); draw(); } }, gone ? "↩" : "✕") : null))); }
      host.replaceChildren(h("div", { class: "row", style: "gap:8px;margin-bottom:8px;align-items:center" }, h("button", { class: "btn small", tip: "The 100 rows before.", onclick: () => { off = Math.max(0, off - 100); draw(); } }, "◀"), h("button", { class: "btn small", tip: "The next 100 rows.", onclick: () => { if (off + 100 < tinfo.rows) { off += 100; draw(); } } }, "▶"), h("span", { class: "hint", style: "margin:0", text: `Rows ${off + 1}–${Math.min(off + 100, tinfo.rows)} of ${tinfo.rows.toLocaleString()}. Number columns are saved as numbers.` })), h("div", { style: "overflow:auto;max-height:60vh" }, tbl));
    }
    for (const t of info.tables) tabs.append(h("button", { class: "choice", "data-s": t.name, tip: `Table "${t.name}": ${t.rows} rows.`, onclick: () => { table = t.name; off = 0; draw(); } }, h("b", { text: t.name })));
    await draw();
    st.collect = () => ({ tables: Object.fromEntries(Object.entries(edits).map(([k, v]) => [k, { cells: v.cells, delete: v.delete }])) });
  };

  // ================================================================== PDF
  RENDER.pdf = (body, info) => {
    const changes = {};                                // "page:i" -> text
    body.append(h("p", { class: "hint", text: `${info.total} page${info.total === 1 ? "" : "s"}. Each box is one piece of text on a page. Edited text is rubbed out and typed again in the same place, in a matching standard font. To remove text, empty its box.` }));
    const q = h("input", { type: "search", placeholder: "Show only text containing…", style: "max-width:360px", tip: "Hides the other pieces of text so you can find your place." });
    body.append(q); const host = h("div"); body.append(host);
    const draw = () => { const term = q.value.trim().toLowerCase(); host.replaceChildren();
      for (const pg of info.pages) { const spans = pg.spans.filter((s) => s.text.trim() && (!term || s.text.toLowerCase().includes(term))); if (!spans.length) continue;
        host.append(h("div", { class: "card-box pdfpage" }, h("img", { class: "pdfthumb", src: F.thumbUrl(st.path, 260), alt: "", loading: "lazy", onerror: (e) => e.target.remove() }), h("div", { style: "flex:1;min-width:0" }, h("h3", { text: "Page " + pg.page }), ...spans.map((s) => { const key = pg.page + ":" + s.i; const t = h("input", { type: "text", spellcheck: "true", value: changes[key] !== undefined ? changes[key] : s.text, class: changes[key] !== undefined ? "chg" : "", style: "width:100%;margin-top:4px" }); t.addEventListener("input", () => { changes[key] = t.value; t.classList.add("chg"); dirty(); }); return t; })))); } };
    q.addEventListener("input", draw); draw();
    st.collect = () => ({ edits: Object.entries(changes).map(([k, text]) => { const [page, i] = k.split(":").map(Number); return { page, i, text }; }) });
  };

  // ================================================================== other
  RENDER.binary = (body, info) => {
    body.append(h("div", { class: "card-box", style: "margin-top:12px" }, h("p", { text: info.note || "This file has no text to edit." }), h("div", { class: "row", style: "gap:8px" },
      h("button", { class: "primary", tip: "Opens the raw bytes of this file in the Hex view, where you can search and make a patched copy.", onclick: () => { F.pendingHex = info.path; F.show("hex"); } }, "Open in Hex view"),
      h("button", { class: "btn", tip: "Replaces text hidden inside this kind of file (byte for byte).", onclick: () => F.show("replace") }, "Find & replace"))));
  };

  // ================================================================== pictures
  RENDER.image = async (body, info) => {
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error("This picture could not be opened.")); img.src = `/api/editor/image?path=${encodeURIComponent(info.path)}&t=${encodeURIComponent(F.TOKEN)}&n=${Date.now()}`; });
    const cv = h("canvas", { class: "edcanvas" }); cv.width = img.naturalWidth; cv.height = img.naturalHeight;
    const ctx = cv.getContext("2d"); ctx.drawImage(img, 0, 0);
    const ov = h("canvas", { class: "edover" }); ov.width = cv.width; ov.height = cv.height; const octx = ov.getContext("2d");
    const hist = []; const snap = () => { hist.push(ctx.getImageData(0, 0, cv.width, cv.height)); if (hist.length > 15) hist.shift(); };
    let tool = "pen", color = "#e03131", size = 6, fill = true, txt = "Text", start = null, last = null;
    const tools = [["pen", "✏️ Pen", "Draw freehand."], ["text", "🔤 Text", "Type the words below, then click on the picture where they go."], ["rect", "▭ Box", "Drag to draw a box."], ["blur", "▦ Blur", "Drag over a face, number or name to pixelate it."], ["black", "⬛ Black out", "Drag to cover something with solid black."], ["crop", "✂️ Crop", "Drag the part to keep."]];
    const tbar = h("div", { class: "tabs2" }, tools.map(([k, l, tp]) => h("button", { class: "choice", "data-k": k, tip: tp, "aria-pressed": k === tool, onclick: () => { tool = k; [...tbar.children].forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === k))); } }, h("b", { text: l }))));
    const colorIn = h("input", { type: "color", value: color, tip: "The colour to draw with." }); colorIn.oninput = () => (color = colorIn.value);
    const sizeIn = h("input", { type: "range", min: 1, max: 80, value: size, tip: "How thick the pen is, or how big the text is." }); sizeIn.oninput = () => (size = +sizeIn.value);
    const fillIn = h("input", { type: "checkbox", checked: true }); fillIn.onchange = () => (fill = fillIn.checked);
    const txtIn = h("input", { type: "text", value: txt, placeholder: "Words to add", tip: "The words to place when you click on the picture with the Text tool." }); txtIn.oninput = () => (txt = txtIn.value);
    const doRotate = (deg) => { snap(); const t = document.createElement("canvas"); const w = cv.width, hh = cv.height; t.width = hh; t.height = w; const c = t.getContext("2d"); c.translate(hh / 2, w / 2); c.rotate(deg * Math.PI / 180); c.drawImage(cv, -w / 2, -hh / 2); cv.width = ov.width = hh; cv.height = ov.height = w; ctx.drawImage(t, 0, 0); dirty(); };
    const doFlip = (h2) => { snap(); const t = document.createElement("canvas"); t.width = cv.width; t.height = cv.height; t.getContext("2d").drawImage(cv, 0, 0); ctx.save(); ctx.clearRect(0, 0, cv.width, cv.height); if (h2) { ctx.translate(cv.width, 0); ctx.scale(-1, 1); } else { ctx.translate(0, cv.height); ctx.scale(1, -1); } ctx.drawImage(t, 0, 0); ctx.restore(); dirty(); };
    const undo = () => { const s = hist.pop(); if (!s) return F.toast("Nothing to undo."); cv.width = ov.width = s.width; cv.height = ov.height = s.height; ctx.putImageData(s, 0, 0); dirty(); };
    const pos = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; };
    const rectOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
    ov.addEventListener("pointerdown", (e) => { ov.setPointerCapture(e.pointerId); const p = pos(e);
      if (tool === "text") { if (!txt) return; snap(); ctx.fillStyle = color; ctx.font = `${Math.max(10, size * 4)}px "Segoe UI", Arial, sans-serif`; ctx.textBaseline = "top"; ctx.fillText(txt, p[0], p[1]); dirty(); return; }
      start = p; last = p; if (tool === "pen") { snap(); ctx.strokeStyle = color; ctx.lineWidth = size; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(p[0] + 0.01, p[1]); ctx.stroke(); } });
    ov.addEventListener("pointermove", (e) => { if (!start) return; const p = pos(e);
      if (tool === "pen") { ctx.beginPath(); ctx.moveTo(last[0], last[1]); ctx.lineTo(p[0], p[1]); ctx.stroke(); last = p; }
      else { octx.clearRect(0, 0, ov.width, ov.height); const [x, y, w, hh] = rectOf(start, p); octx.strokeStyle = tool === "crop" ? "#ffffff" : "#7c6cff"; octx.lineWidth = Math.max(2, cv.width / 400); octx.setLineDash([8, 6]); octx.strokeRect(x, y, w, hh); } });
    const finish = (e) => { if (!start) return; const p = pos(e); const s0 = start; start = null; octx.clearRect(0, 0, ov.width, ov.height);
      if (tool === "pen") { dirty(); return; }
      const [x, y, w, hh] = rectOf(s0, p); if (w < 3 || hh < 3) return; snap();
      if (tool === "rect") { ctx.fillStyle = ctx.strokeStyle = color; ctx.lineWidth = Math.max(1, size); fill ? ctx.fillRect(x, y, w, hh) : ctx.strokeRect(x, y, w, hh); }
      else if (tool === "black") { ctx.fillStyle = "#000"; ctx.fillRect(x, y, w, hh); }
      else if (tool === "blur") { const b = Math.max(6, Math.round(Math.min(w, hh) / 6)); const t = document.createElement("canvas"); t.width = Math.max(1, Math.round(w / b)); t.height = Math.max(1, Math.round(hh / b)); const tc = t.getContext("2d"); tc.imageSmoothingEnabled = true; tc.drawImage(cv, x, y, w, hh, 0, 0, t.width, t.height); ctx.imageSmoothingEnabled = false; ctx.drawImage(t, 0, 0, t.width, t.height, x, y, w, hh); ctx.imageSmoothingEnabled = true; }
      else if (tool === "crop") { const d = ctx.getImageData(x, y, w, hh); cv.width = ov.width = Math.round(w); cv.height = ov.height = Math.round(hh); ctx.putImageData(d, 0, 0); }
      dirty(); };
    ov.addEventListener("pointerup", finish); ov.addEventListener("pointercancel", finish);
    body.append(h("div", { class: "card-box", style: "margin-top:12px" }, tbar, h("div", { class: "row", style: "gap:12px;flex-wrap:wrap;align-items:center;margin-top:10px" }, h("label", {}, "Colour ", colorIn), h("label", {}, "Size ", sizeIn), h("label", { tip: "On: boxes are solid.\nOff: boxes are only an outline." }, fillIn, "Filled box"), txtIn,
      h("button", { class: "btn small", tip: "Turns the picture a quarter turn to the left.", onclick: () => doRotate(-90) }, "↺"), h("button", { class: "btn small", tip: "Turns the picture a quarter turn to the right.", onclick: () => doRotate(90) }, "↻"), h("button", { class: "btn small", tip: "Mirrors the picture left to right.", onclick: () => doFlip(true) }, "⇋"), h("button", { class: "btn small", tip: "Mirrors the picture top to bottom.", onclick: () => doFlip(false) }, "⇅"), h("button", { class: "btn small", tip: "Takes back the last change.", onclick: undo }, "Undo")),
      h("div", { class: "edstage" }, cv, ov), h("p", { class: "hint", text: `${img.naturalWidth} × ${img.naturalHeight} pixels. For brightness, sharpening and many pictures at once use "Touch up".` })));
    st.collect = () => ({ data: cv.toDataURL("image/png") });
  };
})();
