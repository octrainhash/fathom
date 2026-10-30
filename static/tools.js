/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* Every file tool gets its own section: merge, split, cut, rotate, PDF pages, pictures out, page scanner, pack, lock, PDF password,
   shredder, checksums, duplicates, inspect, hidden details, photo details, dates, permissions, rename, organise, empty folders,
   data finder, encodings. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api, $ = F.$;
  const post = (path, body) => api(path, { method: "POST", body });
  let META = null;
  const meta = async () => META || (META = await api("/api/tools/meta-info"));

  F.refreshUndo = async () => { try { const u = await api("/api/tools/undo"); $("undo").hidden = !u.available; if (u.available) $("undo").textContent = `Undo ${u.kind.replace("-", " ")} (${u.count})`; } catch { /* ignore */ } };
  $("undo").onclick = async () => {
    try { const r = await post("/api/tools/undo"); F.toast(`Put ${r.restored} file${r.restored === 1 ? "" : "s"} back` + (r.failed.length ? `, ${r.failed.length} could not be restored` : "")); } catch (e) { F.toast(e.message); }
    F.refreshUndo();
  };

  /** "Presets": the tool's ready-made choices plus the ones the person saves, remembered per tool. */
  function presetBar(t, specs, form) {
    const key = "presets." + t.id; let mine = F.load(key, {}) || {};
    const sel = h("select", { tip: "Pick a saved set of choices and every setting below is filled in for you." });
    const fill = () => {
      sel.replaceChildren(h("option", { value: "", text: "Settings: as they are now" }));
      if ((t.presets || []).length) sel.append(h("optgroup", { label: "Ready-made" }, t.presets.map((p, i) => h("option", { value: "b" + i, text: p.name }))));
      if (Object.keys(mine).length) sel.append(h("optgroup", { label: "Mine" }, Object.keys(mine).map((n) => h("option", { value: "m" + n, text: n }))));
    };
    const apply = (vals) => { for (const [k, v] of Object.entries(vals || {})) { try { form.set(k, v); } catch (e) { /* field not shown */ } } };
    sel.onchange = () => { const v = sel.value; if (!v) return; apply(v[0] === "b" ? t.presets[+v.slice(1)].values : mine[v.slice(1)]); del.hidden = v[0] !== "m"; };
    const save = h("button", { class: "btn small", tip: "Remember the settings below under a name, to use again in one click.", onclick: () => { const n = (prompt("Name for this set of settings:") || "").trim().slice(0, 40); if (!n) return; mine[n] = form.values(); F.save(key, mine); fill(); sel.value = "m" + n; del.hidden = false; F.toast("Saved. Find it in the Settings list."); } }, "Save these settings");
    const del = h("button", { class: "btn small danger", hidden: true, tip: "Forget this saved set.", onclick: () => { const v = sel.value; if (v[0] !== "m") return; delete mine[v.slice(1)]; F.save(key, mine); fill(); del.hidden = true; } }, "Delete");
    fill();
    return h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px" }, sel, save, del);
  }

  /** Registers a tool whose page is: title, a form card, a Run button and a job panel. */
  function jobTool(t) {
    (F.jobTools = F.jobTools || {})[t.id] = t;
    F.addTool({
      id: t.id, group: t.group, icon: t.icon, label: t.label, blurb: t.blurb, el: F.makeView(t.id),
      build: async (sec) => {
        const view = F.standardView(t.id, { output: t.output !== false, files: t.files !== false, hint: t.hint });
        sec.replaceWith(view.sec); F.tools.find((x) => x.id === t.id).el = view.sec; view.sec.classList.add("on");
        const main = view.main;
        main.append(F.titleBlock(t.title, t.sub));
        const specs = typeof t.fields === "function" ? await t.fields() : (t.fields || []);
        const form = F.form(specs);
        if (specs.length) main.append(h("div", { class: "card-box" }, presetBar(t, specs, form), form.el));
        if (t.extra) main.append(...[].concat(t.extra(form, view)));
        const go = h("button", { class: t.danger ? "primary warn" : "primary", tip: t.runTip }, t.run || "Start");
        const host = h("div"); const panel = new F.JobPanel(host, { noun: t.noun || "file", renderItem: t.renderItem, onDone: (s, items) => { go.disabled = false; t.done && t.done(s, items, panel); F.refreshUndo(); } });
        main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
        go.onclick = async () => {
          if (t.needsFiles !== false && !F.needFiles()) return;
          const v = form.values();
          const bad = t.validate && t.validate(v); if (bad) return F.toast(bad);
          if (t.confirm && !confirm(t.confirm(v))) return;
          try { go.disabled = true; const r = await post(t.endpoint, t.body(v)); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); }
        };
        t.after && t.after(main, form, panel);
      },
    });
  }
  const base = (v, extra = {}) => ({ paths: F.state.sources, recursive: true, output: F.outputBody(), ...extra });
  F.jobTool = jobTool; F.baseBody = base;
  const PDF_NOTE = "Works on PDF files. ";

  // =========================================================== EDIT
  jobTool({ id: "merge", group: "edit", icon: "🧩", label: "Merge", blurb: "Join several files into one, in the order shown in your list: PDFs and pictures into one PDF, videos or songs into one, text or table files into one.",
    title: "Merge files", sub: "Join files into one, in the order of your list on the left (use the little arrows to change the order). PDFs and pictures become one PDF, videos and songs are joined end to end, text and CSV files are stacked.",
    fields: [{ id: "kind", type: "select", label: "Make a…", value: "auto", options: [
      { v: "auto", l: "Choose for me", tip: "Fathom looks at your files and picks the right kind of merge." }, { v: "pdf", l: "One PDF", tip: "PDFs and pictures are put together as pages of one PDF." },
      { v: "video", l: "One video", tip: "Videos are joined one after the other. Different sizes are fitted onto a matching frame." }, { v: "audio", l: "One audio file", tip: "Songs and sounds are joined one after the other." },
      { v: "table", l: "One CSV table", tip: "CSV or TSV files are stacked into one table." }, { v: "text", l: "One text file", tip: "Text files are joined one after the other." }], tip: "What kind of file the merged result should be." }],
    extra: () => { const host = h("div", { class: "card-box" }); const rows = new Map();
      const draw = () => { const pdfs = F.state.sources.filter((p) => F.ext(p) === "pdf"); host.replaceChildren(h("h3", { text: "Which pages of each PDF" }), pdfs.length ? h("p", { class: "hint", text: "Leave a box empty to use the whole PDF. Type pages like 1-3, last, odd, every 2 …" }) : h("p", { class: "hint", text: "Add PDFs on the left to choose pages from each. (Folders: every PDF inside is merged whole.)" }),
        ...pdfs.map((p) => { let inp = rows.get(p); if (!inp) { inp = h("input", { type: "text", placeholder: "all pages", tip: "Only these pages of this PDF are put in the merged file. Empty = all." }); rows.set(p, inp); } return h("div", { class: "field" }, h("label", { text: F.baseName(p) }), inp); })); host.hidden = !pdfs.length; };
      F.watchSources(draw); draw(); host.pagesFor = () => Object.fromEntries([...rows].filter(([p, i]) => i.value.trim() && F.state.sources.includes(p)).map(([p, i]) => [p, i.value.trim()])); mergePages = host; return host; },
    endpoint: "/api/tools/merge", body: (v) => base(v, { kind: v.kind, options: { file_pages: mergePages ? mergePages.pagesFor() : {} } }), run: "Merge", validate: () => (F.state.sources.length < 2 ? "Add at least two files to merge." : null), noun: "merge",
    runTip: "Joins the files in the order shown on the left. Your originals are not changed." });

  jobTool({ id: "split", group: "edit", icon: "✂️", label: "Split", blurb: "Cut one file into several: a PDF by page, a video or song into pieces of equal length, or any big file into parts of a set size.",
    title: "Split a file", sub: "Cut a file into pieces. PDFs by pages, video and audio by time, and any file by size (handy for upload limits).",
    fields: [{ id: "mode", type: "choice", label: "Split by", value: "each", options: [
        { v: "each", l: "Every page", s: "PDF", tip: "A PDF becomes one small PDF per page." }, { v: "every", l: "Every N pages", s: "PDF", tip: "A PDF is cut into pieces that each hold the number of pages you type." },
        { v: "ranges", l: "Page ranges", s: "PDF", tip: "Choose exact pages, like 1-3;4-9;10-end. Each range becomes its own PDF." },
        { v: "seconds", l: "Every N seconds", s: "Video, audio", tip: "A video or song is cut into pieces of the length you type." }, { v: "size", l: "Parts of a size", s: "Any file", tip: "Any file is cut into parts of the size you type. Join them again with the 'Join parts' tool." }] },
      { id: "value", type: "text", label: "Number", placeholder: "e.g. 5", show: (v) => v.mode !== "each", tip: "Pages per piece, or seconds per piece, or the size of each part in MB, or page ranges like 1-3;4-9, depending on what you picked above." },
      { id: "exact", type: "check", label: "Cut exactly on the second", small: "(slower)", show: (v) => v.mode === "seconds", value: false, tip: "On: every piece is re-encoded so it starts exactly where it should. Slower.\nOff: pieces are cut without re-encoding (fast), starting at the nearest safe point, so lengths can be a little off." }],
    endpoint: "/api/tools/split", body: (v) => base(v, { mode: v.mode, value: String(v.value || ""), options: { exact: v.exact } }), run: "Split", noun: "file", runTip: "Cuts each file into pieces. The pieces are saved in a new folder." });

  jobTool({ id: "join", group: "edit", icon: "🔗", label: "Join parts", blurb: "Put split parts back together (files ending in .part001, .part002 …).",
    title: "Join parts", sub: "Add the part files (like movie.mp4.part001, movie.mp4.part002) or the folder that holds them. Fathom puts them back together into the original file.",
    fields: [], endpoint: "/api/tools/join", body: () => ({ paths: F.state.sources, output: F.outputBody() }), run: "Join", noun: "file" });

  jobTool({ id: "cut", group: "edit", icon: "🎬", label: "Cut", blurb: "Keep just part of a video or song: choose where it starts and ends.",
    title: "Cut a video or song", sub: "Keep only the part you want. Type times as seconds (90) or minutes and seconds (1:30).",
    fields: [{ id: "start", type: "text", label: "Start at", placeholder: "0:00", tip: "Where the piece you keep begins. Leave empty to start at the beginning." },
      { id: "end", type: "text", label: "End at", placeholder: "end of the file", tip: "Where the piece you keep ends. Leave empty to keep everything until the end." },
      { id: "exact", type: "check", label: "Cut exactly", small: "(slower)", value: false, tip: "On: the file is re-encoded so it starts and ends at exactly the times you typed. Slower.\nOff: it is cut without re-encoding, which is very fast and keeps full quality, but may start a moment early." }],
    endpoint: "/api/tools/trim", body: (v) => base(v, { text: v.start || "", text2: v.end || "", flag: v.exact }), run: "Cut", noun: "file" });

  let mergePages = null;
  let rotPP = null, rotForm = null;
  const rotLook = () => {
    const before = h("img", { alt: "", class: "rot-img" }), after = h("img", { alt: "", class: "rot-img" }); const cap = h("p", { class: "hint", style: "text-align:center;margin:6px 0 0" });
    const update = () => {
      if (!rotPP || !rotForm) return; const v = rotForm.values(), st = rotPP.state; const src = rotPP.stage.querySelector(".pvbase");
      const has = st.path && src && src.src; before.hidden = after.hidden = !has; if (!has) { cap.textContent = "Add a file to see the turn on a real page."; return; }
      before.src = after.src = src.src;
      let on = true; const pk = rotForm.pagesPicker; if (pk && st.pages > 1) on = pk.includes(st.page);
      const portrait = st.h >= st.w; if (v.orient === "portrait" && !portrait) on = false; if (v.orient === "landscape" && portrait) on = false;
      const ang = on ? +v.angle || 0 : 0; const sx = on && (v.flip === "h" || v.flip === "both") ? -1 : 1, sy = on && (v.flip === "v" || v.flip === "both") ? -1 : 1;
      after.style.transform = `scaleX(${sx}) scaleY(${sy}) rotate(${ang}deg)`;
      cap.textContent = on ? `Page ${st.page + 1} of this file would be changed like this.` : `Page ${st.page + 1} is not one of the pages you chose (or is the other way round), so it stays as it is.`;
    };
    return { box: h("div", { class: "rot-pair" }, h("figure", {}, before, h("figcaption", { text: "Before" })), h("figure", {}, after, h("figcaption", { text: "After" }))), cap, update };
  };
  const rotView = rotLook();
  jobTool({ id: "rotate", group: "edit", icon: "↻", label: "Rotate / flip", blurb: "Turn pictures, PDF pages and videos, or mirror them. For PDFs you choose which pages.",
    title: "Rotate and flip", sub: "Turn pictures, PDF pages and videos. You can also mirror them left to right or upside down. For a PDF, choose exactly which pages are turned, and see the result on a real page of your file first.",
    fields: () => { rotPP = F.previewPicker({ label: "Preview on", size: 600, onChange: () => rotView.update() });
      return [{ id: "angle", type: "choice", label: "Turn", value: 90, options: [{ v: 0, l: "Don't turn", tip: "Keep the angle as it is. Use this if you only want to flip." }, { v: 90, l: "90° right", s: "clockwise", tip: "Turns it a quarter turn to the right." }, { v: 180, l: "180°", s: "upside down", tip: "Turns it upside down." }, { v: 270, l: "90° left", s: "counter-clockwise", tip: "Turns it a quarter turn to the left." }] },
      { id: "flip", type: "select", label: "Mirror", value: "", options: [{ v: "", l: "No mirror" }, { v: "h", l: "Left to right", tip: "Like looking in a mirror." }, { v: "v", l: "Top to bottom", tip: "Flips it upside down like a reflection in water." }, { v: "both", l: "Both", tip: "Mirrors both ways." }], tip: "Mirrors the picture without turning it." },
      { id: "pages", type: "pages", label: "Which pages (PDFs and multi-page pictures)", value: "", source: rotPP, tip: "Only these pages are turned. Empty = every page. Type numbers (1,3), ranges (5-8), 'odd', 'even', 'end', 'every 3', '!2' (not page 2) or click the pages." },
      { id: "orient", type: "select", label: "Only pages that are", value: "any", options: [{ v: "any", l: "Any shape" }, { v: "portrait", l: "Upright (portrait)" }, { v: "landscape", l: "Sideways (landscape)" }], tip: "Handy for scans: turn only the sideways pages, for example." }]; },
    extra: (form) => { rotForm = form; rotForm.pagesPicker = form.pagePicker && form.pagePicker("pages"); form.el.addEventListener("input", () => rotView.update()); form.el.addEventListener("click", () => setTimeout(rotView.update, 0)); setTimeout(rotView.update, 400);
      return h("div", { class: "card-box" }, h("h3", { text: "What it will look like" }), rotPP.el, rotView.box, rotView.cap); },
    endpoint: "/api/tools/rotate", body: (v) => base(v, { number: +v.angle, mode: v.flip, options: { pages: v.pages || "", orient: v.orient || "any" } }), run: "Rotate", noun: "file" });

  // ---- visual page organiser: drag the pages into a new order, turn, copy, delete, add blank pages
  function pageOrganiser(specField) {
    const pp = F.previewPicker({ label: "Pages of", size: 200, onChange: () => load() });
    let model = [], total = 0, path = "", dragFrom = -1;                        // model: [{p: index|null (blank), rot}]
    const grid = h("div", { class: "org-grid" }); const note = h("p", { class: "hint" });
    const spec = () => { const out = []; let i = 0; while (i < model.length) { const m = model[i]; if (m.p == null) { out.push("blank"); i++; continue; } let j = i; while (j + 1 < model.length && model[j + 1].p === model[j].p + 1 && model[j + 1].rot === m.rot) j++; const r = m.rot ? "r" + m.rot : ""; out.push(i === j ? `${m.p + 1}${r}` : `${m.p + 1}-${model[j].p + 1}${r}`); i = j + 1; } return out.join(","); };
    const push = () => { specField.set(spec()); specField.changed && specField.changed(); draw(); };
    const thumb = (pi) => `/api/pdf/page?path=${encodeURIComponent(path)}&page=${pi}&size=140&t=${encodeURIComponent(F.TOKEN)}`;
    function draw() {
      grid.replaceChildren(); note.textContent = path ? `${model.length} page${model.length === 1 ? "" : "s"} in the new PDF (from ${total}).` : "Add a PDF to arrange its pages.";
      model.forEach((m, idx) => {
        const card = h("div", { class: "org-card", draggable: "true", tip: "Drag to move this page. The buttons turn, copy or remove it." },
          m.p == null ? h("div", { class: "org-blank", text: "blank" }) : h("img", { src: thumb(m.p), alt: "", loading: "lazy", draggable: "false", style: `transform:rotate(${m.rot}deg)` }),
          h("span", { class: "org-n", text: m.p == null ? "new" : String(m.p + 1) }),
          h("div", { class: "org-btns" },
            h("button", { type: "button", tip: "Turns this page a quarter turn to the right.", onclick: () => { m.rot = (m.rot + 90) % 360; push(); } }, "↻"),
            h("button", { type: "button", tip: "Makes a copy of this page right after it.", onclick: () => { model.splice(idx + 1, 0, { ...m }); push(); } }, "⧉"),
            h("button", { type: "button", tip: "Puts an empty page after this one.", onclick: () => { model.splice(idx + 1, 0, { p: null, rot: 0 }); push(); } }, "＋"),
            h("button", { type: "button", tip: "Takes this page out of the new PDF.", onclick: () => { model.splice(idx, 1); push(); } }, "✕")));
        card.addEventListener("dragstart", (e) => { dragFrom = idx; e.dataTransfer.effectAllowed = "move"; card.classList.add("drag"); });
        card.addEventListener("dragend", () => card.classList.remove("drag"));
        card.addEventListener("dragover", (e) => { e.preventDefault(); card.classList.add("over"); }); card.addEventListener("dragleave", () => card.classList.remove("over"));
        card.addEventListener("drop", (e) => { e.preventDefault(); card.classList.remove("over"); if (dragFrom < 0 || dragFrom === idx) return; const [mv] = model.splice(dragFrom, 1); model.splice(idx, 0, mv); dragFrom = -1; push(); });
        grid.append(card);
      });
    }
    function load() { const s = pp.state; if (!s.path || !/\.pdf$/i.test(s.path)) { path = ""; model = []; total = 0; draw(); return; } if (s.path === path && total === s.pages) return; path = s.path; total = s.pages; model = [...Array(total).keys()].slice(0, 2000).map((p) => ({ p, rot: 0 })); draw(); }
    const tools = h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin:8px 0" },
      h("button", { class: "btn small", type: "button", tip: "Starts again with every page in its first order.", onclick: () => { const s = path; path = ""; total = 0; load(); void s; } }, "Start again"),
      h("button", { class: "btn small", type: "button", tip: "Puts the last page first and the first page last.", onclick: () => { model.reverse(); push(); } }, "Reverse the order"),
      h("button", { class: "btn small", type: "button", tip: "Turns every page a quarter turn to the right.", onclick: () => { model.forEach((m) => (m.rot = (m.rot + 90) % 360)); push(); } }, "Turn all"),
      h("button", { class: "btn small", type: "button", tip: "For a double-sided stack scanned in two passes: front pages 1,2,3 then back pages 3,2,1 become 1,front... Takes the first half and the reversed second half and weaves them.", onclick: () => { const n = model.length, half = Math.ceil(n / 2), a = model.slice(0, half), b = model.slice(half).reverse(); const w = []; for (let i = 0; i < half; i++) { w.push(a[i]); if (b[i]) w.push(b[i]); } model = w; push(); } }, "Weave two scans"));
    // typing a list updates the pictures
    const fromText = (txt) => { if (!path) return; try { const out = []; for (const part of (txt || "").split(/[;,\s]+/).filter(Boolean)) { const m = part.toLowerCase().match(/^(\d+|end|last)(?:-(\d+|end|last))?(?:r(90|180|270))?$/); if (part.toLowerCase() === "blank") { out.push({ p: null, rot: 0 }); continue; } if (!m) throw 0; const n = (x) => (x === "end" || x === "last" ? total : +x); const a = n(m[1]), b = m[2] ? n(m[2]) : a; if (a < 1 || b < 1 || a > total || b > total) throw 0; const rot = m[3] ? +m[3] : 0; if (a <= b) for (let i = a; i <= b; i++) out.push({ p: i - 1, rot }); else for (let i = a; i >= b; i--) out.push({ p: i - 1, rot }); } if (out.length) { model = out; draw(); } } catch { /* not a full list yet */ } };
    return { el: h("div", { class: "card-box" }, h("h3", { text: "Arrange the pages" }), pp.el, tools, note, grid), fromText };
  }
  let orgView = null;
  jobTool({ id: "pages", group: "edit", icon: "📑", label: "PDF pages", blurb: "Drag the pages of a PDF into a new order, turn, copy, delete them or add blank pages.",
    title: "PDF pages", sub: PDF_NOTE + "Drag the page pictures into the order you want. Use the small buttons to turn, copy, add a blank page after, or remove a page. Or type the list below: 3,1,2,5-8,end — add r90 to turn (3r90) and write blank for an empty page.",
    fields: [{ id: "spec", type: "text", label: "Pages in the new order", placeholder: "e.g. 3,1,2r90,blank,5-8,end", tip: "Numbers separated by commas. 1-4 means pages 1 to 4. 8-5 means 8, 7, 6, 5. 'end' means the last page. 3r90 turns page 3. 'blank' adds an empty page. Leave the box empty to keep all pages as they are (useful with Rotate below). The pictures above stay in step with this box." },
      { id: "rot", type: "select", label: "Also turn every page", value: "0", options: [{ v: "0", l: "No" }, { v: "90", l: "90° right" }, { v: "180", l: "180°" }, { v: "270", l: "90° left" }], tip: "Turns all pages of the new PDF (on top of any turns you set above)." }],
    extra: (form) => { const fld = { set: (v) => form.set("spec", v), changed: null }; orgView = pageOrganiser(fld); const inp = form.el.querySelector("input[type=text]"); if (inp) inp.addEventListener("input", () => orgView.fromText(inp.value)); return orgView.el; },
    endpoint: "/api/tools/arrange", body: (v) => ({ paths: F.state.sources, text: v.spec, number: +v.rot, output: F.outputBody() }), run: "Make the new PDF", noun: "PDF" });

  jobTool({ id: "extract", group: "edit", icon: "🖼", label: "Pictures out", blurb: "Pull the pictures out of a PDF, Word, PowerPoint or e-book, or grab frames from a video.",
    title: "Pictures out", sub: "Save the pictures that are inside a PDF, a Word or PowerPoint file or an e-book, or take a picture from a video every few seconds.",
    fields: [{ id: "what", type: "choice", label: "Take pictures from", value: "images", options: [{ v: "images", l: "Documents", s: "PDF, Word, PowerPoint, e-book", tip: "Saves every picture that is embedded in the document, at its original quality." }, { v: "frames", l: "Videos", s: "a frame every few seconds", tip: "Saves a still picture from the video at regular intervals." }] },
      { id: "pages", type: "pages", label: "Only from these PDF pages", value: "", show: (v) => v.what === "images", tip: "Empty = every page. For PDFs only." },
      { id: "every", type: "number", label: "One picture every", value: 5, min: 0.1, step: "any", unit: "seconds", show: (v) => v.what === "frames", tip: "Low: many pictures, close together.\nHigh: few pictures, far apart." },
      { id: "fmt", type: "select", label: "Save as", value: "jpg", show: (v) => v.what === "frames", options: [{ v: "jpg", l: "JPG (smaller)" }, { v: "png", l: "PNG (sharper)" }], tip: "JPG makes smaller files. PNG keeps every detail but files are bigger." }],
    endpoint: "/api/tools/extract", body: (v) => base(v, { mode: v.what, number: +v.every || 1, value: v.fmt, options: { pages: v.pages || "" } }), run: "Get the pictures", noun: "file" });

  jobTool({ id: "scan", group: "edit", icon: "📷", label: "Scan pages", blurb: "Turn a phone photo or a scan of a page into a clean, flat, readable page: finds the paper, straightens it, removes shadows.",
    title: "Scan pages", sub: "Turn photos of paper (taken with a phone) or messy scans into clean, flat pages. Fathom finds the paper's corners, straightens the page, removes shadows and sharpens the text.",
    fields: [{ id: "mode", type: "choice", label: "Look", value: "magic", options: [{ v: "magic", l: "Magic colour", s: "Best for most", tip: "Keeps colour but evens out the light, removes shadows and makes the page look fresh." }, { v: "color", l: "Colour", s: "Natural", tip: "Removes shadows but keeps the colours as they were." }, { v: "gray", l: "Grey", s: "Smaller files", tip: "Black, white and shades of grey. Smaller files." }, { v: "bw", l: "Black and white", s: "Like a photocopy", tip: "Pure black text on white, like a photocopier. Smallest files, best for text." }, { v: "original", l: "Only straighten", s: "No changes to look", tip: "Only finds and straightens the page. Colours and light are not changed." }] },
      { id: "crop", type: "check", label: "Find the page and straighten it", value: true, tip: "On: Fathom finds the four corners of the paper, cuts away the table around it and un-tilts the page.\nOff: the whole picture is kept as it is." },
      { id: "sharpen", type: "check", label: "Sharpen the text", value: true, tip: "On: makes letters crisper and easier to read.\nOff: leaves the sharpness alone. Choose this if the result looks too harsh." },
      { id: "out", type: "select", label: "Save as", value: "jpg", options: [{ v: "jpg", l: "JPG pictures", tip: "One picture per page." }, { v: "png", l: "PNG pictures", tip: "One sharper, bigger picture per page." }, { v: "pdf_each", l: "One PDF for each photo", tip: "Every photo becomes its own PDF." }, { v: "pdf_one", l: "One PDF with all pages", tip: "All your photos become pages of a single PDF, in the order of your list." }], tip: "The kind of file you get." }],
    extra: (form) => { const lp = F.livePreview({ tool: "scan", kinds: ["image", "pdf"], options: () => { const v = form.values(); return { mode: v.mode, crop: v.crop, sharpen: v.sharpen }; } }); form.el.addEventListener("input", lp.update); form.el.addEventListener("change", lp.update); form.el.addEventListener("click", () => setTimeout(lp.update, 0)); return lp.el; },
    endpoint: "/api/tools/scan", body: (v) => base(v, { mode: v.mode, flag: v.crop, kind: v.out, options: { sharpen: v.sharpen } }), run: "Clean the pages", noun: "page",
    hint: "Add your photos or scans of pages (pictures or PDFs)." });

  // =========================================================== SIZE: pack
  jobTool({ id: "pack", group: "size", icon: "🗜", label: "Pack", blurb: "Put files and folders into one archive (ZIP, 7z, TAR…), with a password, in several parts, or as a self-opening .exe.",
    title: "Pack into an archive", sub: "Put the files and folders on the left into one archive. To open archives, use Convert and choose 'Folder' as the type. Fathom opens ZIP, RAR, 7z, TAR, ISO and many more.",
    fields: [{ id: "fmt", type: "select", label: "Archive type", value: "zip", options: [{ v: "zip", l: "ZIP", tip: "Opens everywhere, on every computer." }, { v: "7z", l: "7z", tip: "Smaller than ZIP. Needs 7-Zip (or a similar program) to open." }, { v: "tar.gz", l: "TAR.GZ", tip: "Common on Mac and Linux." }, { v: "tar.xz", l: "TAR.XZ", tip: "Very small, slow to make. Common on Linux." }, { v: "tar.bz2", l: "TAR.BZ2", tip: "Small, a bit slow." }, { v: "tar", l: "TAR", tip: "Joins files without making them smaller." }, { v: "sfx", l: "Self-opening .exe", tip: "A program that unpacks itself when double-clicked, so the other person needs nothing installed. Windows only." }], tip: "The kind of archive to make." },
      { id: "name", type: "text", label: "Name", placeholder: "Archive", tip: "The name of the new archive, without its ending." },
      { id: "level", type: "range", label: "Squeeze", min: 1, max: 9, value: 9, fmt: (v) => (v <= 3 ? `${v} fast` : v >= 8 ? `${v} smallest` : String(v)), tip: "How hard Fathom tries to make the archive small.\nLow: quick, bigger archive.\nHigh: slower, smallest archive." },
      { id: "password", type: "password", label: "Password", placeholder: "none", show: (v) => ["zip", "7z", "sfx"].includes(v.fmt), tip: "Locks the archive so only people with the password can open it. Leave empty for no password. If you forget it, nobody can open it." },
      { id: "volume", type: "number", label: "Split into parts of", min: 0, value: 0, unit: "MB (0 = one file)", show: (v) => ["zip", "7z", "sfx"].includes(v.fmt), tip: "0 makes one archive. A number like 100 splits it into several 100 MB parts, which helps when a site or email has a size limit. Needs 7-Zip." }],
    endpoint: "/api/tools/pack", body: (v) => ({ paths: F.state.sources, value: v.fmt, text: v.name || "", password: v.password || "", number: +v.level, options: { volume_mb: +v.volume || 0 }, output: F.outputBody() }), run: "Make the archive", noun: "archive" });

  // =========================================================== PROTECT
  jobTool({ id: "lock", group: "protect", icon: "🔐", label: "Lock files", blurb: "Lock files with a password so nobody without it can read them (AES-256 or ChaCha20). Unlock them again here.",
    title: "Lock and unlock files", sub: "Scramble files with a strong password. Nobody, including Fathom, can open a locked file without the password. Locked files end in .locked. Everything happens on this PC.",
    fields: [{ id: "dir", type: "choice", label: "What to do", value: "lock", options: [{ v: "lock", l: "Lock", s: "make unreadable", tip: "Turns each file into a scrambled .locked file. The original is left as it is, so delete it yourself when you are sure." }, { v: "unlock", l: "Unlock", s: "make readable again", tip: "Turns .locked files back into normal files. You need the same password." }] },
      { id: "algo", type: "select", label: "Method", value: "aes", show: (v) => v.dir === "lock", options: [{ v: "aes", l: "AES-256", tip: "The standard used by banks and governments. A very safe choice." }, { v: "chacha", l: "ChaCha20", tip: "Also very strong, and fast on computers without special AES hardware." }], tip: "The kind of scrambling used. Both are extremely strong, and Fathom detects the right one when unlocking." },
      { id: "pw", type: "password", label: "Password", tip: "A long password is safer. Use a sentence or several words. If you forget it, the files cannot be recovered by anyone." },
      { id: "pw2", type: "password", label: "Type it again", show: (v) => v.dir === "lock", tip: "Typing it twice makes sure you did not make a typing mistake. A mistake here would lock you out of your own files." }],
    validate: (v) => (v.dir === "lock" && v.pw !== v.pw2 ? "The two passwords are not the same." : !v.pw ? "Type a password." : null),
    endpoint: "/api/tools/lock", body: (v) => base(v, { password: v.pw, flag: v.dir === "unlock", mode: v.algo || "aes" }), run: "Go", noun: "file" });

  jobTool({ id: "pdflock", group: "protect", icon: "📕", label: "PDF password", blurb: "Add a password to a PDF so it asks for it when opened, or remove a password you know.",
    title: "PDF password", sub: PDF_NOTE + "Add a password that any PDF reader will ask for, or remove one if you know it.",
    fields: [{ id: "dir", type: "choice", label: "What to do", value: "protect", options: [{ v: "protect", l: "Add a password", tip: "The new PDF asks for the password when it is opened, in any PDF reader." }, { v: "remove", l: "Remove the password", tip: "Makes a copy of the PDF that opens without a password. You must know the current password." }] },
      { id: "pw", type: "password", label: "Password", tip: "The password to set, or the password the PDF has now." }],
    validate: (v) => (!v.pw ? "Type a password." : null), endpoint: "/api/tools/pdflock", body: (v) => base(v, { password: v.pw, flag: v.dir === "remove" }), run: "Go", noun: "PDF" });

  jobTool({ id: "shred", group: "protect", icon: "🔥", label: "Shredder", blurb: "Overwrite files so they can never be recovered, then delete them. Several official standards.", danger: true,
    title: "Shredder", sub: "Deleting a file normally only hides it, and recovery programs can bring it back. The shredder overwrites the file's data again and again, then deletes it. This cannot be undone.",
    fields: async () => { const m = await meta(); return [
      { id: "method", type: "select", label: "Method", value: "dod3", options: Object.entries(m.shred).map(([v, l]) => ({ v, l, tip: ({ nist: "One pass of random data. Enough for modern drives, according to the US standard NIST 800-88.", hmg: "Three passes: zeros, ones, random.", dod3: "Three passes: zeros, ones, random. The well-known US defence method.", dod7: "Seven passes. Slower, very thorough.", vsitr: "Seven passes, the German government method.", gutmann: "35 passes. The slowest and most extreme. More than modern drives need." })[v] })), tip: "How many times, and with what patterns, the file's data is overwritten. More passes take longer.\nLow (1 pass): quick, enough for modern drives.\nHigh (35 passes): very slow, extremely thorough." },
      { id: "note", type: "note", label: "", cls: "warnbox" },
      { id: "confirm", type: "text", label: "Type SHRED to confirm", placeholder: "SHRED", tip: "A safety check so you cannot do this by accident. Shredded files do not go to the Recycle Bin and cannot be recovered." }]; },
    after: (main) => main.querySelector(".warnbox") && (main.querySelector(".warnbox").innerHTML = "<b>Know the limits.</b> Overwriting works on normal hard drives. On SSDs, USB sticks and cloud-synced folders the drive may keep old copies somewhere else, so for those use the drive's own secure erase, or full-disk encryption."),
    validate: (v) => (String(v.confirm).trim().toUpperCase() !== "SHRED" ? "Type SHRED in the box to confirm." : null),
    confirm: () => "Permanently destroy the listed files and folders? This cannot be undone.", endpoint: "/api/tools/shred", body: (v) => ({ paths: F.state.sources, recursive: true, mode: v.method, text: v.confirm }), run: "Shred for good", noun: "file", output: false });

  jobTool({ id: "hash", group: "protect", icon: "🧬", label: "Checksums", blurb: "Create a fingerprint of a file (MD5, SHA-256…) or check a download is exactly the file it should be.",
    title: "Checksums", sub: "A checksum is a short code made from a file's contents. If even one byte changes, the code changes, so it proves a file is complete and untouched. Paste the code a website gave you to check your download.",
    fields: async () => [{ id: "algos", type: "multi", label: "Kinds", value: ["sha256"], options: [["md5", "MD5", "Old and fast. Fine for catching download errors, not for security."], ["sha1", "SHA-1", "Old. Fine for checking downloads, not for security."], ["sha256", "SHA-256", "The most common today. A good default."], ["sha512", "SHA-512", "Longer and stronger."], ["sha3_256", "SHA3-256", "The newest SHA family."], ["blake2b", "BLAKE2b", "Fast and strong."], ["crc32", "CRC32", "A tiny code that catches accidental damage. Used by ZIP files."], ["adler32", "Adler-32", "A very small, very fast code."]].map(([v, l, tip]) => ({ v, l, tip })) },
      { id: "expect", type: "text", label: "Code to compare with (optional)", placeholder: "paste the code from the website", tip: "If you paste a code, Fathom tells you whether it matches the file. Matching means the file is exactly what the publisher made." }],
    endpoint: "/api/tools/hash", body: (v) => base(v, { algos: v.algos, text: v.expect || "" }), run: "Make checksums", noun: "file", output: false,
    renderItem: (r) => { const ex = r.extra || {}; const keys = Object.keys(ex).filter((k) => k !== "match");
      return h("div", { class: "job " + r.status }, h("div", { class: "ico", text: ex.match === true ? "✅" : ex.match === false ? "❌" : "🧬" }),
        h("div", { class: "t" }, h("b", { text: r.name }), r.error ? h("small", { text: r.error }) : null, r.note ? h("small", { class: ex.match ? "okc" : "badc", text: r.note }) : null,
          keys.map((k) => h("small", { class: "mono" }, h("b", { text: k.toUpperCase() + "  " }), ex[k], " ", h("button", { class: "link", tip: "Copies this code.", onclick: () => F.copy(ex[k]) }, "copy")))), h("div")); } });

  // =========================================================== TIDY
  F.addTool({ id: "dups", group: "tidy", icon: "👯", label: "Duplicates", blurb: "Find files that are exactly the same, even with different names, and clear out the extra copies safely.", el: F.makeView("dups"),
    build: (sec) => {
      const view = F.standardView("dups", { output: false }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "dups").el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock("Duplicate files", "Finds files with exactly the same contents, byte for byte, even when their names differ. You choose which copies go. At least one copy of each file always stays, and removed copies go to the Recycle Bin."));
      const form = F.form([{ id: "min", type: "number", label: "Ignore files smaller than", value: 1, min: 0, unit: "KB", tip: "Tiny files are often meaningless duplicates (like empty files).\nLow: everything is compared.\nHigh: only bigger files are compared, which is faster." }]);
      main.append(h("div", { class: "card-box" }, form.el));
      const go = h("button", { class: "primary", tip: "Looks through everything on the left for identical files. Nothing is deleted yet." }, "Find duplicates"); const host = h("div");
      main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
      const panel = new F.JobPanel(host, { noun: "step", summary: false, renderItem: () => document.createComment(""), onDone: (s) => { go.disabled = false; render(s.id, s.data); } });
      const result = h("div"); host.append(result);
      go.onclick = async () => { if (!F.needFiles()) return; result.replaceChildren(); try { go.disabled = true; const r = await post("/api/tools/dups", base(0, { number: Math.max(1, (+form.values().min || 0) * 1024) })); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); } };
      function render(jobId, data) {
        const groups = (data && data.groups) || [];
        if (!groups.length) { result.append(h("div", { class: "card-box" }, h("b", { text: "No duplicates found." }), h("p", { class: "hint", text: "Every file is different." }))); return; }
        const checks = [];
        const sel = h("span", { class: "hint" }); const upd = () => { const picked = checks.filter((c) => c.input.checked); sel.textContent = `${picked.length} selected · frees ${F.fmtBytes(picked.reduce((s, c) => s + c.size, 0))}`; };
        const top = h("div", { class: "card-box" }, h("h3", { text: `${groups.length} sets of identical files · ${F.fmtBytes(data.wasted)} could be freed` }),
          h("div", { class: "row", style: "margin-top:10px" },
            h("button", { class: "btn small", tip: "Ticks every copy except the oldest one in each set (the oldest is usually the original).", onclick: () => { checks.forEach((c) => (c.input.checked = !c.keep)); upd(); } }, "Keep oldest"),
            h("button", { class: "btn small", tip: "Ticks every copy except the newest one in each set.", onclick: () => { checks.forEach((c) => (c.input.checked = !c.newest)); upd(); } }, "Keep newest"),
            h("button", { class: "btn small", tip: "Unticks everything.", onclick: () => { checks.forEach((c) => (c.input.checked = false)); upd(); } }, "Clear"), sel));
        result.append(top);
        for (const g of groups.slice(0, 300)) {
          const box = h("div", { class: "dupgroup" }, h("b", { text: `${F.fmtBytes(g.size)} each · ${g.files.length} copies` }));
          g.files.forEach((f, i) => { const input = h("input", { type: "checkbox" }); input.checked = i > 0; input.addEventListener("change", upd); checks.push({ input, path: f.path, size: g.size, keep: i === 0, newest: i === g.files.length - 1 }); box.append(h("label", {}, input, f.path, h("small", { text: `  ${new Date(f.mtime * 1000).toLocaleDateString()}` }))); });
          result.append(box);
        }
        upd();
        const doit = async (action) => {
          const remove = checks.filter((c) => c.input.checked).map((c) => c.path); if (!remove.length) return F.toast("Tick the copies you want to get rid of.");
          let dest = ""; if (action === "move") { dest = await F.pickOne("outfolder"); if (!dest) return; }
          try { const r = await post("/api/tools/dups/apply", { job: jobId, mode: action, remove, value: dest }); F.toast(`${r.done} copies ${action === "move" ? "moved" : "sent to the Recycle Bin"} · ${F.fmtBytes(r.freed)} freed` + (r.failed.length ? `, ${r.failed.length} failed` : "")); result.replaceChildren(); } catch (e) { F.toast(e.message); }
        };
        result.append(h("div", { class: "row", style: "margin-top:14px" },
          h("button", { class: "primary warn", tip: "Sends the ticked copies to the Recycle Bin. You can still restore them from there.", onclick: () => doit("recycle") }, "Recycle selected"),
          h("button", { class: "btn", tip: "Moves the ticked copies into a folder you choose instead of deleting them.", onclick: () => doit("move") }, "Move selected to a folder…")));
      }
    } });

  F.addTool({ id: "inspect", group: "tidy", icon: "🔍", label: "Inspect", blurb: "See what a file really is, whatever its name says, and fix files with the wrong ending.", el: F.makeView("inspect"),
    build: (sec) => {
      const view = F.standardView("inspect", { output: false }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "inspect").el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock("Inspect files", "Fathom reads the inside of each file to tell what it really is. A picture called 'invoice.pdf', or a video with no ending, is spotted at once, and you can fix the name with one click."));
      const go = h("button", { class: "primary", tip: "Looks inside every file on the left. Nothing is changed." }, "Inspect"); const fix = h("button", { class: "btn", hidden: true, tip: "Gives every file whose ending does not match its contents the right ending. You can undo it from the Undo button at the top." }, "Fix wrong endings"); const out = h("div");
      main.append(h("div", { class: "row", style: "margin-top:16px" }, go, fix), out);
      go.onclick = async () => { if (!F.needFiles()) return; try { const { files } = await post("/api/tools/info", { paths: F.state.sources }); const bad = files.filter((f) => f.mismatch); fix.hidden = !bad.length;
        out.replaceChildren(h("table", { class: "tbl" }, h("tr", {}, ["Name", "Really is", "Ending says", "Size", "Last changed"].map((x) => h("th", { text: x }))), ...files.map((f) => h("tr", {}, h("td", { text: f.name }), h("td", { class: f.mismatch ? "badc" : "", text: f.error || (f.folder ? `Folder · ${f.files} files` : f.type) }), h("td", { text: f.ext ? "." + f.ext + (f.mismatch ? "  ⚠ wrong" : "") : "none" }), h("td", { text: f.bytes != null ? F.fmtBytes(f.bytes) : "" }), h("td", { text: f.modified ? new Date(f.modified * 1000).toLocaleString() : "" }))))); } catch (e) { F.toast(e.message); } };
      fix.onclick = async () => { try { const r = await post("/api/tools/fixext", { paths: F.state.sources }); F.toast(`Fixed ${r.fixed.length} file${r.fixed.length === 1 ? "" : "s"}`); F.refreshUndo(); go.onclick(); } catch (e) { F.toast(e.message); } };
    } });

  F.addTool({ id: "rename", group: "tidy", icon: "🏷", label: "Rename", blurb: "Rename lots of files at once: find and replace, numbering, dates, cases and more, with a preview first.", el: F.makeView("rename"),
    build: (sec) => {
      const view = F.standardView("rename", { output: false }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "rename").el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock("Rename many files", "Set the rules, look at the preview, then apply. Nothing changes until you press Apply, and Undo puts every name back."));
      const form = F.form([
        { id: "find", type: "text", label: "Find", placeholder: "text to replace", tip: "Part of the name to change. Leave empty to skip this step." },
        { id: "replace", type: "text", label: "Replace with", placeholder: "new text", tip: "What the found text becomes. Leave empty to delete the found text." },
        { id: "regex", type: "check", label: "Find is a pattern (advanced)", value: false, tip: "On: 'Find' is read as a regular expression pattern.\nOff: 'Find' is matched as plain text." },
        { id: "case_sensitive", type: "check", label: "Capitals matter when finding", value: false, tip: "On: 'IMG' will not match 'img'.\nOff: both match." },
        { id: "remove_chars", type: "text", label: "Remove these characters", placeholder: "e.g. ()[]", tip: "Every one of these characters is deleted from the names." },
        { id: "spaces", type: "select", label: "Spaces become", value: "keep", options: [{ v: "keep", l: "Keep as they are" }, { v: "underscore", l: "_ (underscore)" }, { v: "dash", l: "- (dash)" }, { v: "dot", l: ". (dot)" }, { v: "none", l: "Nothing (remove them)" }], tip: "What to do with spaces in the names." },
        { id: "case", type: "select", label: "Letters", value: "keep", options: [{ v: "keep", l: "Keep as they are" }, { v: "lower", l: "all lowercase" }, { v: "upper", l: "ALL CAPITALS" }, { v: "title", l: "Each Word Capitalised" }, { v: "sentence", l: "First letter only" }], tip: "Changes capital and small letters in the names." },
        { id: "pattern", type: "text", label: "New name pattern", value: "{name}", tip: "Build the whole name from pieces: {name} the old name, {n} a counter (use {n:03} for 001, 002), {date} and {time} of the file, {year}, {parent} the folder name. Example: Holiday {n:03} - {name}." },
        { id: "start", type: "number", label: "Counter starts at", value: 1, tip: "The first number used for {n}." },
        { id: "step", type: "number", label: "Counter goes up by", value: 1, tip: "How much {n} grows each time." },
        { id: "sort", type: "select", label: "Number the files in order of", value: "name", options: [{ v: "name", l: "name" }, { v: "date", l: "date" }, { v: "size", l: "size" }], tip: "Decides which file gets number 1, 2, 3." },
        { id: "new_ext", type: "text", label: "New file ending", placeholder: "keep", tip: "Changes the ending of every file (for example jpg). This does NOT convert the file. It only renames it. Use Convert to really change the type." },
        { id: "ext_case", type: "select", label: "Ending letters", value: "keep", options: [{ v: "keep", l: "Keep" }, { v: "lower", l: "lowercase (.jpg)" }, { v: "upper", l: "UPPERCASE (.JPG)" }], tip: "Makes endings all small or all capital." },
      ]);
      main.append(h("div", { class: "card-box" }, form.el));
      const prev = h("button", { class: "primary", tip: "Shows the old and new names side by side. Nothing is renamed yet." }, "Preview"); const apply = h("button", { class: "btn", hidden: true, tip: "Renames the files as shown in the preview." }, "Apply these names"); const out = h("div"); let rows = [];
      main.append(h("div", { class: "row", style: "margin-top:16px" }, prev, apply), out);
      prev.onclick = async () => { if (!F.needFiles()) return; try { const r = await post("/api/tools/rename/preview", { paths: F.state.sources, recursive: true, rules: form.values() }); rows = r.rows; apply.hidden = !r.changes; apply.textContent = `Apply to ${r.changes} file${r.changes === 1 ? "" : "s"}`;
        out.replaceChildren(h("table", { class: "tbl" }, h("tr", {}, ["Now", "Will become", ""].map((x) => h("th", { text: x }))), ...rows.map((x) => h("tr", {}, h("td", { text: x.old }), h("td", { class: x.status === "same" ? "" : "okc", text: x.new }), h("td", { class: "hint", text: x.status === "renumbered" ? "name was taken, number added" : x.status === "invalid" ? "empty name" : x.status === "same" ? "no change" : "" }))))); } catch (e) { F.toast(e.message); } };
      apply.onclick = async () => { try { const r = await post("/api/tools/rename/apply", { rows }); F.toast(`Renamed ${r.renamed} file${r.renamed === 1 ? "" : "s"}` + (r.failed.length ? `, ${r.failed.length} failed` : "")); F.refreshUndo(); apply.hidden = true; out.replaceChildren(); } catch (e) { F.toast(e.message); } };
    } });

  F.addTool({ id: "organize", group: "tidy", icon: "🗂", label: "Organise", blurb: "Sort a messy folder into tidy subfolders by type, date, size or first letter.", el: F.makeView("organize"),
    build: (sec) => {
      const view = F.standardView("organize", { output: false }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "organize").el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock("Organise files", "Sort a messy folder into neat subfolders. You see exactly what will move before anything happens, and Undo puts everything back."));
      let dest = "";
      const form = F.form([
        { id: "how", type: "select", label: "Sort by", value: "type", options: [{ v: "type", l: "Kind of file (Pictures, Videos, Documents…)", tip: "Fathom looks inside each file to decide if it is a picture, video, document and so on." }, { v: "extension", l: "File ending (JPG, PDF, MP3…)", tip: "One folder per ending." }, { v: "year", l: "Year", tip: "One folder per year the file was last changed." }, { v: "month", l: "Year and month", tip: "Folders like 2024 / 2024-05." }, { v: "size", l: "Size", tip: "Tiny, small, large and huge." }, { v: "initial", l: "First letter of the name", tip: "A folder for A, one for B, and so on." }], tip: "The rule used to decide which subfolder each file goes into." },
        { id: "copy", type: "check", label: "Copy instead of move", value: false, tip: "On: the originals stay where they are and organised copies are made. Uses more disk space.\nOff: files are moved into the new folders." }]);
      const pickBtn = h("button", { class: "btn small", tip: "Choose where the sorted folders are created. If you do not choose, they are created inside the folder you added." }, "Choose a destination…"); const destTxt = h("span", { class: "hint", text: "Inside the folder you added" });
      pickBtn.onclick = async () => { const p = await F.pickOne("outfolder"); if (p) { dest = p; destTxt.textContent = p; } };
      main.append(h("div", { class: "card-box" }, form.el, h("div", { class: "field" }, h("div", { class: "lab", text: "Destination" }), h("div", { class: "inline" }, pickBtn, destTxt))));
      const prev = h("button", { class: "primary", tip: "Shows where each file will go. Nothing moves yet." }, "Preview"); const apply = h("button", { class: "btn", hidden: true }, "Apply"); const out = h("div"); let rows = [];
      main.append(h("div", { class: "row", style: "margin-top:16px" }, prev, apply), out);
      prev.onclick = async () => { if (!F.needFiles()) return; try { const v = form.values(); const r = await post("/api/tools/organize/preview", { paths: F.state.sources, recursive: true, mode: v.how, value: dest, flag: !!v.copy }); rows = r.rows; apply.hidden = !rows.length; apply.textContent = `${v.copy ? "Copy" : "Move"} ${rows.length} file${rows.length === 1 ? "" : "s"}`;
        const byFolder = {}; rows.forEach((x) => (byFolder[x.folder] = (byFolder[x.folder] || 0) + 1));
        out.replaceChildren(rows.length ? h("div", { class: "card-box" }, h("h3", { text: "Folders that will be created" }), h("div", { class: "tags" }, Object.entries(byFolder).map(([k, n]) => h("span", { class: "tag fs", text: `${k} · ${n}` })))) : h("p", { class: "hint", text: "Everything is already where it should be." }),
          rows.length ? h("table", { class: "tbl" }, h("tr", {}, ["File", "Goes to"].map((x) => h("th", { text: x }))), ...rows.slice(0, 400).map((x) => h("tr", {}, h("td", { text: F.baseName(x.path) }), h("td", { text: x.to })))) : null); } catch (e) { F.toast(e.message); } };
      apply.onclick = async () => { try { const r = await post("/api/tools/organize/apply", { rows, flag: !!form.values().copy }); F.toast(`${r.done} file${r.done === 1 ? "" : "s"} organised` + (r.failed.length ? `, ${r.failed.length} failed` : "")); F.refreshUndo(); apply.hidden = true; out.replaceChildren(); } catch (e) { F.toast(e.message); } };
    } });

  F.addTool({ id: "empty", group: "tidy", icon: "🫥", label: "Empty folders", blurb: "Find folders with nothing inside and remove them.", el: F.makeView("empty"),
    build: (sec) => {
      const view = F.standardView("empty", { output: false, hint: "Add the folders to look through." }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "empty").el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock("Empty folders", "Finds folders that hold nothing at all, and lets you remove them. Folders with even one file are never touched."));
      const go = h("button", { class: "primary", tip: "Looks for empty folders inside the folders on the left." }, "Find empty folders"); const out = h("div"); main.append(h("div", { class: "row", style: "margin-top:16px" }, go), out);
      go.onclick = async () => { if (!F.needFiles()) return; try { const { folders } = await post("/api/tools/emptyfolders", { paths: F.state.sources });
        if (!folders.length) return out.replaceChildren(h("p", { class: "hint", text: "No empty folders." }));
        const checks = folders.map((f) => { const i = h("input", { type: "checkbox" }); i.checked = true; return [i, f]; });
        out.replaceChildren(h("div", { class: "card-box" }, h("h3", { text: `${folders.length} empty folder${folders.length === 1 ? "" : "s"}` }), ...checks.map(([i, f]) => h("label", { style: "display:block;padding:2px 0" }, i, f)),
          h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "primary warn", tip: "Deletes the ticked empty folders. They hold nothing, so nothing is lost.", onclick: async () => { const r = await post("/api/tools/emptyfolders/remove", { remove: checks.filter(([i]) => i.checked).map(([, f]) => f) }); F.toast(`Removed ${r.removed} folder${r.removed === 1 ? "" : "s"}`); out.replaceChildren(); } }, "Remove ticked folders")))); } catch (e) { F.toast(e.message); } };
    } });

  // =========================================================== PROTECT: hidden details, photo details, dates, permissions
  F.addTool({ id: "meta", group: "protect", icon: "🕵️", label: "Hidden details", blurb: "See the details hidden inside files (where a photo was taken, who wrote a document) and remove them for privacy.", el: F.makeView("meta"),
    build: (sec) => {
      const view = F.standardView("meta", { output: true }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "meta").el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock("Hidden details", "Photos, documents and videos carry hidden notes: the place a photo was taken, the camera, the author of a document. See them here, and make a clean copy with all of it removed before you share a file."));
      const look = h("button", { class: "btn", tip: "Shows the hidden details stored in each file. Nothing is changed." }, "Look inside"); const strip = h("button", { class: "primary", tip: "Makes a clean copy of each file with its hidden details removed. Photos are cleaned without changing the picture's quality. The original is not touched." }, "Make clean copies");
      const out = h("div"); const host = h("div"); const panel = new F.JobPanel(host, { noun: "file", onDone: () => (strip.disabled = false) });
      main.append(h("div", { class: "row", style: "margin-top:16px" }, look, strip), out, host);
      look.onclick = async () => { if (!F.needFiles()) return; try { const { files } = await post("/api/tools/meta", { paths: F.state.sources });
        out.replaceChildren(...files.map((f) => h("div", { class: "card-box" }, h("h3", { text: f.name }), h("small", { class: "hint", text: f.type }),
          f.gps ? h("div", { class: "dangerbox", text: `📍 This file reveals a location: ${f.gps.lat?.toFixed ? f.gps.lat.toFixed(5) : f.gps.lat}, ${f.gps.lon?.toFixed ? f.gps.lon.toFixed(5) : f.gps.lon}` }) : null,
          f.private && f.private.length ? h("p", { class: "warnc", text: "Private details found: " + f.private.join(", ") }) : null,
          h("table", { class: "tbl" }, ...f.fields.map(([k, v]) => h("tr", {}, h("td", { text: k }), h("td", { class: "mono", text: v }))))))); } catch (e) { F.toast(e.message); } };
      strip.onclick = async () => { if (!F.needFiles()) return; try { strip.disabled = true; const r = await post("/api/tools/meta/strip", base(0)); panel.start(r.job); } catch (e) { strip.disabled = false; F.toast(e.message); } };
    } });

  jobTool({ id: "hand", group: "search", icon: "✍️", label: "Read handwriting", blurb: "Turn handwritten notes, letters, forms and scans (even very messy writing) into typed text you can search and edit.",
    title: "Read handwriting", sub: "Add photos or scans of handwriting (pictures or PDFs). Fathom straightens the page, removes the ruled lines, finds every line of writing and reads it. You get a text file, and a proof picture that numbers each line it read, so you can check it against the page.",
    fields: [
      { id: "engine", type: "select", label: "Reader", value: "auto", options: [{ v: "auto", l: "Best available", tip: "Uses your AI model when a key is set (best for messy writing), otherwise the offline reader if installed, otherwise the basic reader." }, { v: "ai", l: "AI (best for messy writing)", tip: "Your AI model looks at the whole page and every line close up, then takes a second, slower look at the hard ones. The pictures are sent to that service." },
        { v: "trocr", l: "Offline on this PC", tip: "A handwriting model that runs on your PC. Nothing leaves your PC. Needs the one-time install below." }, { v: "enhanced", l: "Basic (neat writing only)", tip: "The normal text reader on a cleaned-up copy. Fast, but only good for neat, print-like writing." }], tip: "Which reader does the reading." },
      { id: "careful", type: "check", label: "Take a second, closer look at hard lines", value: true, show: (v) => v.engine === "ai" || v.engine === "auto", tip: "Lines the reader is unsure about are read again, larger, with the rest of the page as context. Slower, much better on messy writing." },
      { id: "pages", type: "pages", label: "Which pages (PDFs)", value: "", tip: "Only these pages of each PDF are read. Empty = all pages." },
      { id: "format", type: "select", label: "Save as", value: "txt", options: [{ v: "txt", l: "Text (.txt)", tip: "Plain text." }, { v: "docx", l: "Word (.docx)", tip: "A Word document you can edit." }, { v: "md", l: "Markdown (.md)", tip: "Plain text with simple headings per page." }, { v: "html", l: "Web page (.html)", tip: "A web page." }], tip: "What kind of file the typed text is saved as." },
    ],
    extra: () => { const status = h("p", { class: "hint", text: "Checking which readers are ready…" }); const host = h("div");
      const draw = async () => { try { const i = await api("/api/handwriting/info"); status.textContent = `AI reader: ${i.ai ? "ready (" + i.model + ")" : "no key set yet (Assistant > Settings)"}.   Offline reader: ${i.trocr ? "installed" : "not installed"}.   Will use: ${({ ai: "AI", trocr: "offline reader", enhanced: "basic reader" })[i.chosen]}.`; } catch { status.textContent = ""; } };
      const btn = h("button", { class: "btn small", tip: "Downloads the offline handwriting model (a few GB) and the engine it needs. Needs internet once. Afterwards nothing leaves your PC.", onclick: async () => { try { btn.disabled = true; const r = await post("/api/handwriting/install", {}); const p = new F.JobPanel(host, { noun: "step", summary: false, onDone: () => { btn.disabled = false; draw(); } }); p.start(r.job); } catch (e) { btn.disabled = false; F.toast(e.message); } } }, "Install the offline reader");
      draw(); return h("div", { class: "card-box" }, h("h3", { text: "Readers" }), status, btn, host); },
    endpoint: "/api/tools/handwriting", body: (v) => base(v, { options: { engine: v.engine, careful: v.careful, pages: v.pages, format: v.format } }), run: "Read it", noun: "file",
    runTip: "Reads the handwriting in every added picture and PDF and saves it as typed text. Your originals are not changed." });
  jobTool({ id: "exif", group: "protect", icon: "📍", label: "Photo details", blurb: "Edit a photo's hidden details: remove its location, fix the date taken, set the author, without touching the picture itself.",
    title: "Photo details", sub: "Change the notes stored inside JPEG photos without re-saving the picture, so there is no quality loss. Remove the location, fix a wrong date, add your name and copyright.",
    fields: [{ id: "remove_gps", type: "check", label: "Remove the location", value: true, tip: "On: the place where the photo was taken is erased from the new copy.\nOff: the location is left as it is." },
      { id: "date", type: "datetime", label: "Date taken", tip: "Sets when the photo was taken. Leave empty to keep the date that is stored." },
      { id: "artist", type: "text", label: "Photographer", placeholder: "keep", tip: "The name of the person who took the picture. Leave empty to keep what is stored." },
      { id: "copyright", type: "text", label: "Copyright", placeholder: "keep", tip: "A copyright note, like '© 2024 Your Name'." },
      { id: "description", type: "text", label: "Description", placeholder: "keep", tip: "A short caption stored inside the photo." }],
    endpoint: "/api/tools/exif", body: (v) => base(v, { options: { remove_gps: v.remove_gps, date: v.date || "", artist: v.artist || "", copyright: v.copyright || "", description: v.description || "" } }), run: "Make edited copies", noun: "photo" });

  jobTool({ id: "times", group: "protect", icon: "🕰", label: "Dates", blurb: "Change a file's created, modified or opened dates: set an exact time, shift them, or match them to the date a photo was taken.",
    title: "File dates", sub: "Every file remembers when it was created, changed and last opened. Change them here, for example to put scanned photos in the right order. This changes the files themselves.",
    output: false,
    fields: [{ id: "mode", type: "choice", label: "How", value: "set", options: [{ v: "set", l: "Set a date", s: "exact time", tip: "Every selected file gets exactly the date and time you choose." }, { v: "shift", l: "Move by an amount", s: "earlier or later", tip: "Every file's date is moved forward or back by the same amount. Good for a camera with the wrong clock." }, { v: "taken", l: "Match 'date taken'", s: "photos", tip: "A photo's file date is set to the day the camera recorded when the photo was taken." }] },
      { id: "when", type: "datetime", label: "Date and time", show: (v) => v.mode === "set", tip: "The date and time to give the files." },
      { id: "shift", type: "number", label: "Move by", value: 60, show: (v) => v.mode === "shift", unit: "minutes (negative = earlier)", tip: "How many minutes to move. 60 is one hour later. -1440 is one day earlier." },
      { id: "which", type: "multi", label: "Which dates", value: ["modified"], options: [{ v: "modified", l: "Last changed", tip: "The 'date modified' shown in folders." }, { v: "created", l: "Created", tip: "The 'date created'. Windows only." }, { v: "accessed", l: "Last opened", tip: "The 'date accessed'." }] }],
    confirm: () => "Change the dates of these files? The files are changed in place.", endpoint: "/api/tools/times", body: (v) => ({ paths: F.state.sources, recursive: true, mode: v.mode, text: String(v.when || "").replace("T", " "), number: +v.shift || 0, algos: v.which }), run: "Change dates", noun: "file" });

  F.addTool({ id: "perms", group: "protect", icon: "🛂", label: "Permissions", blurb: "See and change who can read, change or run a file: read-only and hidden flags, Windows access rules, or Mac and Linux modes.", el: F.makeView("perms"),
    build: (sec) => {
      const view = F.standardView("perms", { output: false }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "perms").el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock("Permissions", "See who is allowed to do what with a file, and change it. Make files read-only so they cannot be changed by mistake, hide them, or set Windows access rules or Mac and Linux modes."));
      const form = F.form([
        { id: "readonly", type: "select", label: "Read-only", value: "", options: [{ v: "", l: "Leave as is" }, { v: "on", l: "Make read-only" }, { v: "off", l: "Allow changes" }], tip: "On: the file cannot be changed or deleted by accident.\nOff: it can be edited normally." },
        { id: "hidden", type: "select", label: "Hidden", value: "", options: [{ v: "", l: "Leave as is" }, { v: "on", l: "Hide" }, { v: "off", l: "Show" }], tip: "On: the file does not show in folders unless 'show hidden files' is switched on.\nOff: it shows normally." },
        { id: "acl", type: "select", label: "Windows access rule", value: "", options: [{ v: "", l: "No change" }, { v: "grant", l: "Allow a user or group" }, { v: "deny", l: "Block a user or group" }, { v: "remove", l: "Remove a user or group's rule" }, { v: "reset", l: "Reset to the folder's default" }], tip: "Changes who may open the file on Windows (NTFS drives). Reset puts the rules back to what the folder says." },
        { id: "principal", type: "text", label: "User or group", placeholder: "Everyone, Users, or a name", show: (v) => ["grant", "deny", "remove"].includes(v.acl), tip: "The person or group the rule is about. For example Everyone, Users or Administrators." },
        { id: "rights", type: "select", label: "Allowed to", value: "R", show: (v) => ["grant", "deny"].includes(v.acl), options: [{ v: "R", l: "Read" }, { v: "RX", l: "Read and run" }, { v: "W", l: "Write" }, { v: "M", l: "Change" }, { v: "F", l: "Full control" }], tip: "How much power the rule gives or blocks." },
        { id: "mode", type: "text", label: "Mac / Linux mode", placeholder: "e.g. 644 or 755", tip: "A three-digit code. Each digit is for owner, group and everyone else: 4 means read, 2 write, 1 run, added together. 644 means the owner can edit and others can only read. 755 is the same but everyone can run it. Used on Mac and Linux." }]);
      main.append(h("div", { class: "card-box" }, form.el));
      const look = h("button", { class: "btn", tip: "Shows the current permissions of each file." }, "Look"); const apply = h("button", { class: "primary", tip: "Applies the changes above to every file on the left." }, "Apply changes"); const out = h("div"); const host = h("div"); const panel = new F.JobPanel(host, { noun: "file", onDone: () => (apply.disabled = false) });
      main.append(h("div", { class: "row", style: "margin-top:16px" }, look, apply), out, host);
      look.onclick = async () => { if (!F.needFiles()) return; try { const { files } = await post("/api/tools/perms", { paths: F.state.sources });
        out.replaceChildren(h("table", { class: "tbl" }, h("tr", {}, ["Name", "Details"].map((x) => h("th", { text: x }))), ...files.map((f) => h("tr", {}, h("td", { text: f.name }), h("td", { class: "mono", text: f.error || (f.acl ? `${f.readonly ? "read-only " : ""}${f.hidden ? "hidden " : ""}${f.system ? "system " : ""}\n${f.acl}` : `mode ${f.mode} · owner ${f.owner} · group ${f.group}`) }))))); } catch (e) { F.toast(e.message); } };
      apply.onclick = async () => { if (!F.needFiles()) return; try { apply.disabled = true; const r = await post("/api/tools/perms/apply", { paths: F.state.sources, recursive: true, options: form.values() }); panel.start(r.job); } catch (e) { apply.disabled = false; F.toast(e.message); } };
    } });

  // =========================================================== SEARCH: data finder
  F.addTool({ id: "scrape", group: "search", icon: "🧲", label: "Data finder", blurb: "Scan whole folders for emails, phone numbers, passwords, keys, card numbers and more, and list every one found.", el: F.makeView("scrape"),
    build: async (sec) => {
      const view = F.standardView("scrape", { output: true }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "scrape").el = view.sec; view.sec.classList.add("on");
      const m = await meta(); const main = view.main;
      main.append(F.titleBlock("Data finder", "Scans documents, PDFs, spreadsheets, code, logs and (if you want) pictures for patterns like email addresses, phone numbers, IP addresses, passwords and secret keys. Use it to clean up leaks in your own files or to collect contact details. Card and bank numbers are checked so only real-looking ones are listed."));
      const tips = { email: "Finds addresses like name@site.com.", phone: "Finds phone numbers in many styles.", ipv4: "Finds addresses like 192.168.1.1.", ipv6: "Finds long IPv6 addresses.", mac: "Finds device hardware addresses like 00:1A:2B:3C:4D:5E.", url: "Finds web addresses starting with http.", card: "Finds payment card numbers. Each one is checked with the card check-digit test, so random numbers are ignored.", ssn: "Finds US social security numbers.", iban: "Finds bank account numbers (IBAN) and checks their check digits.", aws: "Finds Amazon cloud access keys.", google: "Finds Google API keys.", github: "Finds GitHub access tokens.", slack: "Finds Slack tokens.", stripe: "Finds live Stripe payment keys.", jwt: "Finds login tokens (JWT).", privkey: "Finds private key blocks.", password: "Finds lines like password = something." };
      const form = F.form([{ id: "kinds", type: "multi", label: "Look for", value: ["email", "phone", "ipv4", "card", "aws", "password"], options: Object.entries(m.patterns).map(([v, l]) => ({ v, l, tip: tips[v] })) },
        { id: "custom", type: "text", label: "Your own pattern (optional)", placeholder: "a regular expression", tip: "Advanced: a regular expression for anything else you want to find. For example \\bINV-\\d{6}\\b finds invoice numbers like INV-123456." },
        { id: "ocr", type: "check", label: "Also read text inside pictures", value: false, tip: "On: pictures and screenshots are read with OCR too. Much slower.\nOff: only real text is searched." },
        { id: "binary", type: "check", label: "Also look inside programs and other binary files", value: false, tip: "On: readable text hidden inside programs and databases is searched too.\nOff: those files are skipped." }]);
      main.append(h("div", { class: "card-box" }, form.el));
      const go = h("button", { class: "primary", tip: "Starts looking through every file on the left." }, "Find data"); const host = h("div"); const res = h("div");
      let jobData = null, jobId = null, reveal = false, filter = "";
      const panel = new F.JobPanel(host, { noun: "file", summary: false, renderItem: () => document.createComment(""), onDone: (s) => { go.disabled = false; jobData = s.data; jobId = s.id; draw(); } });
      main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host, res);
      function draw() {
        const all = (jobData && jobData.findings) || [];
        if (!all.length) { res.replaceChildren(h("div", { class: "card-box" }, h("b", { text: "Nothing found." }))); return; }
        const counts = {}; all.forEach((f) => (counts[f.kind] = (counts[f.kind] || 0) + 1));
        const chips = h("div", { class: "chips" }, h("button", { "aria-pressed": !filter, onclick: () => { filter = ""; draw(); } }, "All", h("b", { text: all.length })), ...Object.entries(counts).map(([k, n]) => h("button", { "aria-pressed": filter === k, onclick: () => { filter = k; draw(); } }, (jobData.labels[k] || "Your pattern").split(" (")[0], h("b", { text: n }))));
        const rev = h("input", { type: "checkbox" }); rev.checked = reveal; rev.onchange = () => { reveal = rev.checked; draw(); };
        const rows = all.filter((f) => !filter || f.kind === filter);
        res.replaceChildren(h("div", { class: "card-box" }, h("h3", { text: `${all.length} found` }), chips,
          h("div", { class: "row", style: "margin-top:10px" }, h("label", { tip: "On: secrets such as passwords and card numbers are shown in full on this screen.\nOff: they are partly hidden (••••). The list you export can be hidden or full, as you choose." }, rev, "Show hidden values in full"),
            h("button", { class: "btn small", tip: "Saves every result into a spreadsheet file (CSV) in your chosen save location.", onclick: async () => { try { const r = await post("/api/tools/scrape/export", { job: jobId, output: F.outputBody(), flag: reveal }); F.toast("Saved " + F.baseName(r.path)); F.reveal(r.path); } catch (e) { F.toast(e.message); } } }, "Export to CSV")),
          h("table", { class: "tbl" }, h("tr", {}, ["Type", "Value", "File", "Where"].map((x) => h("th", { text: x }))), ...rows.slice(0, 1500).map((f) => h("tr", {}, h("td", { text: (jobData.labels[f.kind] || "Your pattern").split(" (")[0] }), h("td", { class: "mono", text: reveal ? f.value : f.masked }), h("td", { text: F.baseName(f.file), title: f.file }), h("td", { text: f.where }))))));
      }
      go.onclick = async () => { if (!F.needFiles()) return; const v = form.values(); res.replaceChildren(); try { go.disabled = true; const r = await post("/api/tools/scrape", { paths: F.state.sources, recursive: true, algos: v.kinds, text: v.custom || "", options: { ocr: v.ocr, binary: v.binary } }); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); } };
    } });

  // =========================================================== CONVERT: encodings
  jobTool({ id: "codec", group: "convert", icon: "🔣", label: "Encodings", blurb: "Fix garbled text by changing its character encoding, or turn any file into Base64, Hex, Base32… text and back.",
    title: "Encodings", sub: "Two jobs. Change a text file's character encoding (so old files with strange symbols read properly), or turn any file into plain text like Base64 or Hex, and turn that text back into the file.",
    fields: async () => { const m = await meta(); const encs = m.encodings.map((e) => ({ v: e, l: e })); return [
      { id: "kind", type: "choice", label: "What to do", value: "text", options: [{ v: "text", l: "Change text encoding", s: "UTF-8, UTF-16, Windows-1252…", tip: "Rewrites a text file in a different character encoding, so letters like é, ü or Arabic and Chinese characters show correctly in other programs." }, { v: "binary", l: "File ⇄ text coding", s: "Base64, Hex, Base32…", tip: "Turns any file into letters and numbers that can be pasted anywhere, or turns that text back into the original file." }] },
      { id: "source", type: "select", label: "Current encoding", value: "auto", show: (v) => v.kind === "text", options: [{ v: "auto", l: "Detect for me", tip: "Fathom works out the encoding by looking at the file. Best choice when you are not sure." }, ...encs], tip: "How the file's text is stored right now." },
      { id: "target", type: "select", label: "Change to", value: "utf-8", show: (v) => v.kind === "text", options: encs, tip: "The encoding to save the new copy in. UTF-8 is the modern standard that works almost everywhere. Old types like ASCII or Latin-1 cannot hold all characters; the missing ones become ?." },
      { id: "newline", type: "select", label: "Line endings", value: "keep", show: (v) => v.kind === "text", options: [{ v: "keep", l: "Keep" }, { v: "lf", l: "LF (Mac, Linux)" }, { v: "crlf", l: "CRLF (Windows)" }, { v: "cr", l: "CR (very old Macs)" }], tip: "Windows, Mac and Linux mark the end of a line differently. This makes them all match." },
      { id: "op", type: "choice", label: "Direction", value: "encode", show: (v) => v.kind === "binary", options: [{ v: "encode", l: "File → text", tip: "Turns the file into text." }, { v: "decode", l: "Text → file", tip: "Turns coded text back into the original file." }] },
      { id: "codec", type: "select", label: "Coding", value: "base64", show: (v) => v.kind === "binary", options: Object.entries(m.codecs).map(([v, l]) => ({ v, l, tip: ({ base64: "The most common. Used in emails and web pages.", base32: "Like Base64 but only capital letters and digits. Easier to read aloud.", hex: "Each byte as two characters 0-9 and A-F.", binary: "Each byte as eight 0s and 1s.", ascii85: "More compact than Base64.", base85: "More compact than Base64 (Git style).", base58: "Used for crypto addresses. Avoids look-alike characters.", uuencode: "An old coding from early email.", "quoted-printable": "Used in emails, keeps normal text readable." })[v] })), tip: "The kind of text coding to use." }]; },
    endpoint: "/api/tools/codec", body: (v) => base(v, { kind: v.kind, mode: v.op || "encode", value: v.codec || "", text: v.source || "auto", text2: v.target || "utf-8", options: { newline: v.newline || "keep" } }), run: "Convert", noun: "file" });

  // ---- more PDF tools: pages per sheet / booklet, properties + bookmarks, form filling
  try {
  jobTool({ id: "nup", group: "edit", icon: "🗂", label: "Pages per sheet", blurb: "Print 2, 4, 6 or 9 PDF pages on one sheet, or make a folded booklet.",
    title: "Pages per sheet", sub: PDF_NOTE + "Puts several small pages on each sheet to save paper, or arranges the pages for a folded booklet (print on both sides, flip on the short edge, fold in half).",
    fields: [{ id: "mode", type: "choice", label: "Make", value: "nup", options: [{ v: "nup", l: "Several pages per sheet", tip: "Shrinks the pages and places them in a grid." }, { v: "booklet", l: "A booklet", s: "2 pages per side", tip: "Puts the pages in booklet order so folding the printed sheets gives the right page order. Empty pages are added at the end when needed." }] },
      { id: "per", type: "select", label: "Pages on each sheet", value: "4", show: (v) => v.mode === "nup", options: [{ v: "2", l: "2" }, { v: "4", l: "4" }, { v: "6", l: "6" }, { v: "9", l: "9" }], tip: "More pages per sheet means smaller pages." },
      { id: "sheet", type: "select", label: "Sheet size", value: "same", options: [{ v: "same", l: "Same as the first page" }, { v: "a4", l: "A4" }, { v: "letter", l: "US Letter" }], tip: "The paper the new PDF is made for. Wide layouts turn the sheet sideways." }],
    endpoint: "/api/tools/nup", body: (v) => ({ paths: F.state.sources, number: v.mode === "booklet" ? 2 : +v.per, flag: v.mode === "booklet", mode: v.sheet, output: F.outputBody() }), run: "Make the new PDF", noun: "PDF" });

  jobTool({ id: "pdfprops", group: "edit", icon: "🔖", label: "PDF properties", blurb: "Set a PDF's title, author and keywords and write its bookmarks (the clickable table of contents).",
    title: "PDF properties and bookmarks", sub: PDF_NOTE + "Change the title, author, subject and keywords stored inside the PDF, and write bookmarks: one per line, the page number first, then the title. Indent a line (two spaces) to make it a sub-item. Press “Load from the PDF” to start from what is already there. Empty boxes are left unchanged.",
    fields: [{ id: "Title", type: "text", label: "Title" }, { id: "Author", type: "text", label: "Author" }, { id: "Subject", type: "text", label: "Subject" }, { id: "Keywords", type: "text", label: "Keywords", tip: "Separate with commas." },
      { id: "bookmarks", type: "textarea", label: "Bookmarks", rows: 6, placeholder: "1 Introduction\n  2 Background\n5 Results", tip: "One per line: page number, a space, then the title. Two spaces in front make a sub-item. If you type anything here, the old bookmarks are replaced." },
      { id: "clear", type: "check", label: "Remove all existing bookmarks", value: false, tip: "Takes out the old bookmarks and does not add new ones when the box above is empty." }],
    extra: (form) => h("div", { class: "row" }, h("button", { class: "btn small", type: "button", tip: "Reads the first PDF on the left and fills the boxes above with what it already has.", onclick: async () => { try { const r = await post("/api/tools/pdfprops-view", { paths: F.state.sources }); for (const k of ["Title", "Author", "Subject", "Keywords", "bookmarks"]) form.set(k, r[k] || ""); F.toast(`Loaded from ${r.name} (${r.pages} pages).`); } catch (e) { F.toast(e.message); } } }, "Load from the PDF")),
    endpoint: "/api/tools/pdfprops", body: (v) => ({ paths: F.state.sources, options: { Title: v.Title || "", Author: v.Author || "", Subject: v.Subject || "", Keywords: v.Keywords || "" }, text: v.bookmarks || "", flag: !!v.clear, output: F.outputBody() }), run: "Save the changes", noun: "PDF" });

  jobTool({ id: "pdfform", group: "edit", icon: "📝", label: "Fill a PDF form", blurb: "Fill in the fields of a fillable PDF form (names, dates, tick boxes) and save a copy.",
    title: "Fill a PDF form", sub: PDF_NOTE + "Add a fillable PDF form and press “Show the fields” to see each field's exact name. Then type one line per field: Field name = what to put in it. For a tick box type Yes or Off. Your original is not changed.",
    fields: [{ id: "values", type: "textarea", label: "Field values", rows: 8, placeholder: "Full name = Ada Lovelace\nCity = London", tip: "One line per field: the exact field name, an equals sign, then the value." },
      { id: "flatten", type: "check", label: "Make the fields read-only afterwards", value: false, tip: "On: the filled form can no longer be edited by mistake.\nOff: the fields stay fillable." }],
    extra: (form) => { const out = h("div", { class: "hint" }); return h("div", {}, h("div", { class: "row" }, h("button", { class: "btn small", type: "button", tip: "Lists the fields found in the first PDF on the left.", onclick: async () => { try { const r = await post("/api/tools/pdfform-fields", { paths: F.state.sources }); if (!r.fields.length) { out.textContent = `${r.name} has no fillable fields.`; return; } out.replaceChildren(h("b", { text: `${r.name}: ${r.fields.length} field${r.fields.length === 1 ? "" : "s"}` }), h("ul", {}, ...r.fields.map((f) => h("li", { text: `${f.name}  (${f.kind}${f.value ? ", now: " + f.value : ""})` })))); form.set("values", r.fields.map((f) => f.name + " = " + f.value).join("\n")); } catch (e) { F.toast(e.message); } } }, "Show the fields")), out); },
    endpoint: "/api/tools/pdfform-fill", body: (v) => ({ paths: F.state.sources, text: v.values || "", flag: !!v.flatten, output: F.outputBody() }), run: "Fill in the form", noun: "PDF" });

  F.addTool({ id: "smartrename", group: "tidy", icon: "✨", label: "Smart rename", blurb: "Your local AI reads each file and suggests a clear name. You check and edit the names before anything changes.", el: F.makeView("smartrename"),
    build: (sec) => {
      const view = F.standardView("smartrename", { output: false }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "smartrename").el = view.sec; view.sec.classList.add("on");
      const main = view.main;
      main.append(F.titleBlock("Smart rename", "Needs the local AI (set up in AI settings). It reads text files, the first pages of PDFs and small copies of pictures, all on this computer. Files it cannot read are left alone. Nothing is renamed until you press Apply, and Undo puts the names back."));
      const form = F.form([
        { id: "style", type: "select", label: "Name style", value: "words", options: [{ v: "words", l: "Normal words" }, { v: "dash", l: "lowercase-with-dashes" }, { v: "snake", l: "lowercase_with_underscores" }], tip: "How the suggested names are written." },
        { id: "words", type: "number", label: "Longest name (words)", value: 6, tip: "The AI is asked to keep names to this many words." },
        { id: "pictures", type: "check", label: "Look at pictures too", value: true, tip: "On: the AI looks at a small copy of each picture. Needs a vision model (the default one can).\nOff: pictures are skipped." }]);
      main.append(h("div", { class: "card-box" }, form.el));
      const go = h("button", { class: "primary", tip: "Asks the AI for a name for every file on the left. Nothing is renamed yet." }, "Suggest names");
      const apply = h("button", { class: "btn", hidden: true, tip: "Renames the files as shown in the table." }, "Apply these names");
      const box = h("div"), tbl = h("div");
      main.append(h("div", { class: "row", style: "margin-top:16px" }, go, apply), box, tbl);
      let rows = [];
      const panel = new F.JobPanel(box, { noun: "file", summary: false });
      panel.onDone = async () => {
        go.disabled = false;
        try {
          const r = await api(`/api/tools/smartrename/${panel.id}/rows`); rows = r.rows;
          if (!rows.length) { tbl.replaceChildren(h("div", { class: "hint", text: "No names were suggested. Check that the local AI is running." })); return; }
          apply.hidden = false; apply.textContent = `Apply to ${rows.length} file${rows.length === 1 ? "" : "s"}`;
          tbl.replaceChildren(h("table", { class: "tbl" }, h("tr", {}, ["Now", "Suggested name (you can edit)"].map((x) => h("th", { text: x }))),
            ...rows.map((x) => { const inp = h("input", { type: "text", value: x.new, style: "width:100%", "aria-label": "New name for " + x.old }); inp.oninput = () => { x.new = inp.value.trim() || x.old; x.status = x.new === x.old ? "same" : "ok"; }; return h("tr", {}, h("td", { text: x.old }), h("td", {}, inp)); })));
        } catch (e) { F.toast(e.message); }
      };
      go.onclick = async () => { if (!F.needFiles()) return; go.disabled = true; apply.hidden = true; tbl.replaceChildren(); try { const r = await post("/api/tools/smartrename", { paths: F.state.sources, recursive: true, options: form.values() }); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); } };
      apply.onclick = async () => { try { const r = await post("/api/tools/rename/apply", { rows }); F.toast(`Renamed ${r.renamed} file${r.renamed === 1 ? "" : "s"}` + (r.failed.length ? `, ${r.failed.length} failed` : "")); F.refreshUndo(); apply.hidden = true; tbl.replaceChildren(); } catch (e) { F.toast(e.message); } };
    } });

  F.addTool({ id: "semsearch", group: "search", icon: "🧭", label: "Search by meaning", blurb: "Find notes and documents by what they are about, not the exact words. Every setting is yours. Runs on this computer.", el: F.makeView("semsearch"),
    build: (sec) => {
      const view = F.standardView("semsearch", { output: false }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "semsearch").el = view.sec; view.sec.classList.add("on");
      const main = view.main;
      main.append(F.titleBlock("Search by meaning", "Step 1: add your folders on the left and press “Learn these files”. Step 2: describe what you want in your own words. Every result comes with a picture: the best sentence is highlighted, circled and pointed at. Needs one small model, once: in a terminal run  ollama pull nomic-embed-text . Nothing leaves this computer."));
      const learnForm = F.form([
        { id: "groups", type: "multi", label: "Kinds of files to learn", value: ["notes", "data", "web", "code", "pdf"], options: [{ v: "notes", l: "Notes (txt, md, rtf, tex)" }, { v: "data", l: "Data and subtitles (csv, json, xml, yaml, log, srt)" }, { v: "web", l: "Web pages (html)" }, { v: "code", l: "Code (py, js)" }, { v: "pdf", l: "PDF documents" }], tip: "Only the ticked kinds are read when you press Learn. Scanned PDFs have no text; run them through OCR first." },
        { id: "size", type: "choice", label: "Passage size", value: "medium", options: [{ v: "small", l: "Small", s: "pin-points one idea", tip: "About 500 characters per passage. Best for exact facts in long files." }, { v: "medium", l: "Medium", s: "a good balance", tip: "About 900 characters per passage." }, { v: "large", l: "Large", s: "keeps more context", tip: "About 1500 characters per passage. Best for essays and reports." }] },
        { id: "max_chunks", type: "number", label: "Passages remembered per file", value: 10, tip: "Longer files are read up to this many passages. More means better coverage and a bigger memory file." },
        { id: "pdf_pages", type: "number", label: "PDF pages to read", value: 12, tip: "Only the first pages of each PDF are learned. Raise it for long books." },
        { id: "model", type: "text", label: "Embedding model", value: "", placeholder: "nomic-embed-text", tip: "The Ollama model that turns text into numbers. Leave empty for the default. If you change it, files are learned again." }]);
      const searchForm = F.form([
        { id: "limit", type: "number", label: "Most results to show", value: 12, tip: "Between 1 and 100." },
        { id: "min", type: "range", label: "Smallest match to show", min: 0, max: 95, value: 30, fmt: (v) => v + "%", tip: "Low: shows even loose matches.\nHigh: shows only close matches." },
        { id: "per_file", type: "select", label: "Matches per file", value: "best", options: [{ v: "best", l: "Only the best one" }, { v: "top3", l: "Up to three" }], tip: "Up to three lets one long file show several places." },
        { id: "gf", type: "multi", label: "Only look in", value: ["notes", "data", "web", "code", "pdf"], options: [{ v: "notes", l: "Notes" }, { v: "data", l: "Data" }, { v: "web", l: "Web pages" }, { v: "code", l: "Code" }, { v: "pdf", l: "PDFs" }], tip: "Untick a kind to leave it out of this search." },
        { id: "name_contains", type: "text", label: "File name must contain", placeholder: "optional, e.g. invoice", tip: "Narrows the search to files whose name has this text." },
        { id: "proofs", type: "number", label: "Proof pictures (0 = none)", value: 6, tip: "How many of the top results get a picture. Each one marks the best sentence." },
        { id: "arrows", type: "check", label: "Point at the match with an arrow", value: true },
        { id: "highlight", type: "color", label: "Highlight colour", value: "#ffeb3b", options: [{ v: "#ffeb3b", l: "Yellow" }, { v: "#7cf29a", l: "Green" }, { v: "#7dd3fc", l: "Sky" }, { v: "#ffb4e6", l: "Pink" }, { v: "#ffb347", l: "Orange" }], tip: "The colour painted behind the best sentence." },
        { id: "circle", type: "color", label: "Circle and arrow colour", value: "#e83e28", options: [{ v: "#e83e28", l: "Red" }, { v: "#2563eb", l: "Blue" }, { v: "#16a34a", l: "Green" }, { v: "#9333ea", l: "Purple" }, { v: "#111111", l: "Black" }], tip: "The colour of the circle and the arrow." }]);
      main.append(h("div", { class: "card-box" }, h("h3", { text: "1. What to learn" }), learnForm.el), h("div", { class: "card-box", style: "margin-top:16px" }, h("h3", { text: "2. How to show the results" }), searchForm.el));
      const learn = h("button", { class: "btn", tip: "Reads the files on the left and remembers what they are about. Run it again later: only new or changed files are done." }, "Learn these files");
      const forget = h("button", { class: "btn small", tip: "Deletes what was learned about the files in the folders on the left. The files themselves are not touched." }, "Forget these folders");
      const wipe = h("button", { class: "btn small danger", tip: "Deletes everything this tool has learned, for every folder. Your files are not touched." }, "Clear everything");
      const stat = h("div", { class: "hint" }), box = h("div");
      const q = h("input", { type: "text", placeholder: "e.g. the letter about my rent going up", style: "width:100%", "aria-label": "What are you looking for" });
      const find = h("button", { class: "primary", tip: "Searches the files you have learned inside the folders on the left." }, "Search");
      const csv = h("button", { class: "btn small", hidden: true, tip: "Saves these results as a spreadsheet file (CSV)." }, "Save results as CSV");
      const res = h("div"), proofHost = h("div");
      main.append(h("div", { class: "row", style: "margin-top:16px" }, learn, forget, wipe), stat, box, h("div", { class: "card-box", style: "margin-top:16px" }, h("h3", { text: "3. Ask" }), q), h("div", { class: "row", style: "margin-top:12px" }, find, csv), res, proofHost);
      const lv = () => { const v = learnForm.values(); return { groups: v.groups, size: v.size, max_chunks: +v.max_chunks || 10, pdf_pages: +v.pdf_pages || 12, model: v.model || "" }; };
      const refresh = async () => { try { const r = await post("/api/tools/semstatus", { paths: F.state.sources || [] }); stat.textContent = r.files ? `Learned so far: ${r.files} files (${r.passages} passages, ${(r.bytes / 1048576).toFixed(1)} MB). ${F.state.sources && F.state.sources.length ? r.here + " of them are in the folders on the left." : ""}` : "Nothing learned yet."; } catch (e) { stat.textContent = ""; } };
      refresh();
      const panel = new F.JobPanel(box, { noun: "file", summary: false }); panel.onDone = () => { learn.disabled = false; refresh(); };
      learn.onclick = async () => { if (!F.needFiles()) return; learn.disabled = true; try { const r = await post("/api/tools/semindex", { paths: F.state.sources, recursive: true, options: lv() }); panel.start(r.job); } catch (e) { learn.disabled = false; F.toast(e.message); } };
      forget.onclick = async () => { if (!F.needFiles()) return; try { const r = await post("/api/tools/semforget", { paths: F.state.sources, flag: false }); F.toast(`Forgot ${r.forgotten} file${r.forgotten === 1 ? "" : "s"}`); refresh(); } catch (e) { F.toast(e.message); } };
      wipe.onclick = async () => { if (!confirm("Forget everything Search by meaning has learned? Your files are not touched.")) return; try { const r = await post("/api/tools/semforget", { paths: [], flag: true }); F.toast(`Forgot ${r.forgotten} file${r.forgotten === 1 ? "" : "s"}`); res.replaceChildren(); proofHost.replaceChildren(); refresh(); } catch (e) { F.toast(e.message); } };
      let last = [];
      const go = async () => {
        try {
          const v = searchForm.values();
          const r = await post("/api/tools/semsearch", { paths: F.state.sources || [], text: q.value, options: { limit: +v.limit || 12, min_score: (+v.min || 0) / 100, per_file: v.per_file, groups: v.gf, name_contains: v.name_contains || "", proofs: +v.proofs || 0, arrows: !!v.arrows, highlight: v.highlight, circle: v.circle, index: lv() } });
          last = r.hits; csv.hidden = !last.length;
          res.replaceChildren(r.hits.length ? h("table", { class: "tbl" }, h("tr", {}, ["Match", "File", "Best matching passage", ""].map((x) => h("th", { text: x }))), ...r.hits.map((x) => h("tr", {},
            h("td", { text: x.percent + "%", tip: "How close this passage is to what you asked. 100% would be identical meaning." }),
            h("td", {}, h("b", { text: x.name }), x.page ? h("small", { text: " · page " + x.page }) : null, h("div", { class: "hint", text: x.folder })),
            h("td", { text: x.snippet }),
            h("td", {}, h("button", { class: "btn small", tip: "Opens this file.", onclick: () => F.openFile(x.path) }, "Open"), " ", h("button", { class: "btn small", tip: "Shows the folder that holds this file.", onclick: () => F.reveal(x.path) }, "Show folder"), " ", h("button", { class: "btn small", tip: "Copies the full path of this file.", onclick: () => { try { navigator.clipboard.writeText(x.path); F.toast("Path copied"); } catch (e) { F.toast(x.path); } } }, "Copy path"))))) : h("div", { class: "hint", text: r.indexed ? "Nothing close enough was found. Lower “Smallest match to show”, or learn more files." : "Nothing has been learned yet. Press “Learn these files” first." }));
          proofHost.replaceChildren(); const pg = F.proofGallery(r.hits.map((x) => x.proof && { ...x.proof, note: x.proof.note + (x.best ? " · " + x.best : "") }), { first: 6 }); if (pg) proofHost.append(pg);
        } catch (e) { F.toast(e.message); }
      };
      find.onclick = go; q.onkeydown = (e) => { if (e.key === "Enter") go(); };
      csv.onclick = () => { const esc = (s) => '"' + String(s == null ? "" : s).replace(/"/g, '""') + '"'; const rows = [["match_percent", "file", "folder", "page", "passage"], ...last.map((x) => [x.percent, x.name, x.folder, x.page || "", x.snippet])];
        const a = h("a", { href: URL.createObjectURL(new Blob(["﻿" + rows.map((r) => r.map(esc).join(",")).join("\r\n")], { type: "text/csv" })), download: "search-by-meaning.csv" }); document.body.append(a); a.click(); a.remove(); };
    } });
  } catch (e) { console.warn("Fathom: the extra PDF tools could not load", e); }
})();
