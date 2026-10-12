/* Shared page tools: "which pages" (type them, tick presets, or click the pages) and "preview on one of my files" (a real page from a file
   you added; when you added folders, you choose which file). Used by Stamp, Sign, Redact, Rotate, Find & replace, Print and more. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h;
  const post = (p, b) => F.api(p, { method: "POST", body: b });
  const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // ---------------------------------------------------------------- page lists (same rules as app/pagesel.py)
  const num = (tok, total) => {
    tok = tok.trim().toLowerCase();
    if (tok === "end" || tok === "last") return total;
    let m = tok.match(/^(?:end|last)\s*-\s*(\d+)$/); if (m) return total - +m[1];
    if (/^\d+$/.test(tok)) return +tok;
    throw new Error(`'${tok}' is not a page number. Use something like 1,3,5-8,end.`);
  };
  function parse(spec, total) {
    spec = (spec || "").trim().toLowerCase();
    let chosen = []; const removed = new Set();
    if (!spec) chosen = [...Array(total).keys()];
    for (let part of spec ? spec.split(/[,;]+/) : []) {
      part = part.trim(); if (!part) continue;
      let neg = false; if (part.startsWith("!")) { neg = true; part = part.slice(1).trim(); } else if (part.startsWith("not ")) { neg = true; part = part.slice(4).trim(); }
      let pages = [], m;
      if (part === "all" || part === "*") pages = [...Array(total).keys()];
      else if (part === "odd") pages = [...Array(total).keys()].filter((i) => i % 2 === 0);
      else if (part === "even") pages = [...Array(total).keys()].filter((i) => i % 2 === 1);
      else if (part === "first") pages = [0];
      else if (part === "last") pages = [total - 1];
      else if ((m = part.match(/^(?:every|each)\s*(\d+)(?:\s*(?:st|nd|rd|th))?$/))) { const k = Math.max(1, +m[1]); for (let i = k - 1; i < total; i += k) pages.push(i); }
      else if ((m = part.match(/^(.*?)\s*-\s*(.*)$/)) && (m[1] || m[2]) && !/^(?:end|last)\s*-\s*\d+$/.test(part)) {
        const a = m[1] ? num(m[1], total) : 1, b = m[2] ? num(m[2], total) : total;
        if (a <= b) for (let i = a - 1; i < b; i++) pages.push(i); else for (let i = a - 1; i >= b - 1; i--) pages.push(i);
      } else pages = [num(part, total) - 1];
      pages = pages.filter((p) => p >= 0 && p < total);
      if (neg) pages.forEach((p) => removed.add(p)); else chosen.push(...pages);
    }
    if (spec && !chosen.length && removed.size) chosen = [...Array(total).keys()];
    const seen = new Set();
    return chosen.filter((p) => !removed.has(p) && !seen.has(p) && seen.add(p));
  }
  function compact(pages) {
    const ps = [...new Set(pages)].sort((a, b) => a - b), out = [];
    for (let i = 0; i < ps.length;) { let j = i; while (j + 1 < ps.length && ps[j + 1] === ps[j] + 1) j++; out.push(i === j ? String(ps[i] + 1) : `${ps[i] + 1}-${ps[j] + 1}`); i = j + 1; }
    return out.join(",");
  }
  F.pagesel = { parse, compact };

  F.watchSources = (fn) => { const prev = F.onSourcesChanged; F.onSourcesChanged = () => { prev && prev(); fn(); }; };

  // ---------------------------------------------------------------- "preview on one of my files"
  const PAPER = { a4: [1, 1.414, "A4 page"], a4l: [1.414, 1, "A4 page, sideways"], letter: [1, 1.294, "Letter page"] };
  const pageUrl = (path, page, size) => `/api/preview/page?path=${encodeURIComponent(path)}&page=${page}&size=${size}&t=${encodeURIComponent(F.TOKEN)}`;
  F.pageUrl = pageUrl;

  /** opts: {blank:true, mini:false, onChange(state)} -> {el, stage, layer, state, reload(), setPage(n), hasFile()} */
  F.previewPicker = (opts = {}) => {
    const st = { path: "", page: 0, pages: 1, blank: "a4", files: [], hasFolders: false, loaded: false, w: 0, h: 0, ratio: 1 / 1.414 };
    const sel = h("select", { class: "pv-sel", tip: "Choose which of your own files the preview is drawn on, so you can see exactly how it will look on a real page." });
    const browse = h("button", { class: "btn small", tip: "Choose any PDF or picture on this computer to preview on." }, "Browse…");
    const prev = h("button", { class: "btn small", tip: "Shows the previous page of this file.", "aria-label": "Previous page" }, "◀");
    const next = h("button", { class: "btn small", tip: "Shows the next page of this file.", "aria-label": "Next page" }, "▶");
    const pageIn = h("input", { type: "number", min: 1, value: 1, class: "pv-page", tip: "Which page of the file to show." });
    const of = h("span", { class: "hint", style: "margin:0" });
    const nav = h("span", { class: "pv-nav" }, prev, pageIn, of, next);
    const note = h("p", { class: "hint pv-note" });
    const base = h("img", { class: "pvbase", alt: "", draggable: "false" });
    const layer = h("div", { class: "pvlayer" });
    const stage = h("div", { class: "pvpage" }, base, layer);
    const el = h("div", { class: "pvpicker" }, h("div", { class: "row pv-row" }, h("span", { class: "lab", text: opts.label || "Preview on" }), sel, browse, nav), note);
    const listeners = opts.onChange ? [opts.onChange] : [];
    const fire = () => listeners.forEach((fn) => { try { fn(st); } catch (e) { console.error(e); } });
    const fitBlank = () => { const p = PAPER[st.blank] || PAPER.a4; st.ratio = p[1] / p[0]; stage.style.aspectRatio = `${p[0]} / ${p[1]}`; };
    const showBlank = () => { st.path = ""; base.hidden = true; base.removeAttribute("src"); st.pages = 1; st.page = 0; fitBlank(); stage.classList.add("blank"); nav.hidden = true; fire(); };
    let seq = 0;
    async function showFile() {
      const my = ++seq; stage.classList.remove("blank"); nav.hidden = false; note.textContent = "";
      try {
        const res = await fetch(pageUrl(st.path, st.page, opts.size || 900)); if (!res.ok) throw new Error(await res.text() || "no preview");
        const pages = +res.headers.get("X-Pages") || 1; const blob = await res.blob(); if (my !== seq) return;
        st.pages = pages; pageIn.max = pages; pageIn.value = st.page + 1; of.textContent = "of " + pages; prev.disabled = st.page <= 0; next.disabled = st.page >= pages - 1;
        base.onload = () => { st.w = base.naturalWidth; st.h = base.naturalHeight; st.ratio = st.h / st.w; stage.style.aspectRatio = `${st.w} / ${st.h}`; st.loaded = true; fire(); };
        const old = base.src; base.src = URL.createObjectURL(blob); if (old && old.startsWith("blob:")) URL.revokeObjectURL(old); base.hidden = false;
      } catch (e) { if (my !== seq) return; note.textContent = "A picture of this file could not be made here (" + String(e.message || e).slice(0, 120).replace(/<[^>]+>/g, "") + "). A blank page is shown instead."; showBlank(); }
    }
    function choose(value) {
      if (value.startsWith("blank:")) { st.blank = value.slice(6); showBlank(); }
      else if (value.startsWith("file:")) { st.path = value.slice(5); st.page = 0; showFile(); }
      else { showBlank(); }
    }
    sel.onchange = () => { try { F.save("pv_choice", sel.value); } catch {} choose(sel.value); };
    prev.onclick = () => { if (st.page > 0) { st.page--; showFile(); } };
    next.onclick = () => { if (st.page < st.pages - 1) { st.page++; showFile(); } };
    pageIn.onchange = () => { st.page = Math.max(0, Math.min(st.pages - 1, (+pageIn.value || 1) - 1)); showFile(); };
    browse.onclick = async () => { const p = await F.pickOne("files"); if (!p) return; if (!st.files.some((f) => f.path === p)) st.files.push({ path: p, name: F.baseName(p), folder: "", kind: "" }); fill(); sel.value = "file:" + p; choose(sel.value); };
    function fill(keep) {
      const cur = keep ?? sel.value;
      const direct = st.files.filter((f) => !f.folder), inFolders = st.files.filter((f) => f.folder);
      sel.replaceChildren();
      if (st.hasFolders && !direct.length) sel.append(h("option", { value: "", text: "— you added folders: choose a file to preview on —" }));
      const g1 = h("optgroup", { label: "Your files" }); direct.forEach((f) => g1.append(h("option", { value: "file:" + f.path, text: f.name })));
      if (direct.length) sel.append(g1);
      const byFolder = new Map(); inFolders.forEach((f) => { if (!byFolder.has(f.folder)) byFolder.set(f.folder, []); byFolder.get(f.folder).push(f); });
      for (const [folder, list] of byFolder) { const g = h("optgroup", { label: "In folder: " + F.baseName(folder) }); list.forEach((f) => g.append(h("option", { value: "file:" + f.path, text: f.name }))); sel.append(g); }
      if (!opts.noBlank) { const g3 = h("optgroup", { label: "An empty page" }); Object.entries(PAPER).forEach(([k, v]) => g3.append(h("option", { value: "blank:" + k, text: "A blank " + v[2] }))); sel.append(g3); }
      else if (!st.files.length) sel.append(h("option", { value: "", text: "— add a picture or PDF on the left —" }));
      if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
    }
    async function reload() {
      const keep = sel.value;
      let r = { files: [], has_folders: false };
      if (F.state.sources.length) { try { r = await post("/api/preview/files", { paths: F.state.sources, recursive: true }); } catch {} }
      st.files = (r.files || []).filter((f) => !opts.kinds || opts.kinds.includes(f.kind)); st.hasFolders = !!r.has_folders; fill(keep);
      const wasFile = keep.startsWith("file:") && [...sel.options].some((o) => o.value === keep);
      if (wasFile) { sel.value = keep; if (st.path !== keep.slice(5)) choose(keep); return; }
      const direct = st.files.filter((f) => !f.folder);
      if (direct.length) { sel.value = "file:" + direct[0].path; choose(sel.value); }
      else if (st.hasFolders && st.files.length) { sel.value = ""; note.textContent = `You added ${st.files.length > 1 ? "folders with " + st.files.length + " pages or pictures" : "a folder"}. Choose which file from the folder to preview on.`; showBlank(); }
      else { sel.value = "blank:" + st.blank; showBlank(); }
    }
    fitBlank(); F.watchSources(debounce(reload, 300)); queueMicrotask(reload);
    return { el, stage, layer, state: st, reload, listen: (fn) => listeners.push(fn), setPage: (n) => { st.page = Math.max(0, Math.min(st.pages - 1, n)); if (st.path) showFile(); }, hasFile: () => !!st.path,
             current: () => (st.path ? { path: st.path, page: st.page, pages: st.pages } : null) };
  };

  /** BEFORE / AFTER of the tool's real processing on one chosen picture or page.  opts: {tool, options: () => ({...}), kinds} -> {el, update()} */
  F.livePreview = (opts) => {
    const before = h("img", { alt: "", class: "lp-img" }), after = h("img", { alt: "", class: "lp-img" });
    const note = h("p", { class: "hint", style: "text-align:center;margin:6px 0 0" });
    const busy = h("span", { class: "lp-busy", text: "…" }); busy.hidden = true;
    let seq = 0, pp = null;
    async function update() {
      if (!pp) return; const s = pp.state;
      if (!s.path) { before.removeAttribute("src"); after.removeAttribute("src"); note.textContent = "Add a picture (or choose one from your folder) to see exactly what this does to it."; return; }
      const my = ++seq; busy.hidden = false;
      try {
        const r = await post("/api/tools/preview", { paths: [s.path], mode: opts.tool, number: s.page, value: "900", options: opts.options() });
        if (my !== seq) return; before.src = r.before; after.src = r.after; note.textContent = r.note || "";
      } catch (e) { if (my === seq) note.textContent = e.message; }
      finally { if (my === seq) busy.hidden = true; }
    }
    const soon = debounce(update, 350);
    pp = F.previewPicker({ label: "Try it on", size: 700, kinds: opts.kinds || ["image"], noBlank: true, onChange: soon });
    const el = h("div", { class: "card-box" }, h("h3", {}, "See it first ", busy), pp.el, h("div", { class: "rot-pair lp-pair" }, h("figure", {}, before, h("figcaption", { text: "Before" })), h("figure", {}, after, h("figcaption", { text: "After" }))), note);
    return { el, update: soon, picker: pp };
  };

  // ---------------------------------------------------------------- "which pages"
  /** spec: {label, value, tip, source (a previewPicker to take the file from), orient (adds portrait/landscape)} */
  F.pagePicker = (spec, changed) => {
    const own = spec.source ? null : F.previewPicker({ label: "Pages of", size: 300 });
    const src = spec.source || own;
    const input = h("input", { type: "text", value: spec.value || "", placeholder: spec.placeholder || "all pages  ·  or e.g. 1,3,5-8,end  ·  odd  ·  every 3", autocomplete: "off", spellcheck: "false", class: "pg-in" });
    F.tip(input, spec.tip || "Which pages.\nType numbers (1,3,5), ranges (5-8), 'end' for the last page, 'odd', 'even', 'every 3', or '!4' for 'not page 4'. Empty means every page. Or click the pages below.");
    const count = h("small", { class: "hint", style: "margin:0 0 0 8px" });
    const grid = h("div", { class: "pg-grid" }); grid.hidden = true;
    const toggle = h("button", { class: "btn small", type: "button", tip: "Shows small pictures of the pages. Click a page to choose it; Shift-click chooses a whole stretch." }, "Click the pages…");
    const chip = (label, val, tip) => h("button", { class: "btn small", type: "button", tip, onclick: () => { input.value = val; sync(true); } }, label);
    const chips = h("div", { class: "chips pg-chips" }, chip("All", "", "Every page."), chip("Odd", "odd", "Pages 1, 3, 5 …"), chip("Even", "even", "Pages 2, 4, 6 …"), chip("First", "first", "Only the first page."), chip("Last", "last", "Only the last page."),
      h("button", { class: "btn small", type: "button", tip: "Chooses every page you have not chosen now.", onclick: () => { const t = total(); if (!t) return; const cur = new Set(safeParse()); input.value = compact([...Array(t).keys()].filter((i) => !cur.has(i))); sync(true); } }, "Swap"));
    let order = [];                                                       // how many thumbs are drawn
    const total = () => { const s = src.state; return s.path && /\.pdf$/i.test(s.path) ? s.pages : (s.path ? s.pages : 0); };
    function safeParse() { try { return parse(input.value, total() || 100000); } catch { return []; } }
    function paintGrid() {
      const t = total(), sel = new Set(safeParse());
      grid.querySelectorAll(".pg-cell").forEach((c) => c.classList.toggle("on", sel.has(+c.dataset.i)));
      const txt = !t ? "" : `${sel.size} of ${t} page${t === 1 ? "" : "s"} chosen`;
      let err = ""; try { parse(input.value, t || 100000); } catch (e) { err = e.message; }
      count.textContent = err || txt; count.classList.toggle("bad", !!err);
    }
    function buildGrid(more) {
      const t = total(), cur = src.state.path;
      if (!t || !cur || !/\.pdf$/i.test(cur)) { grid.hidden = true; toggle.hidden = !(t && cur && /\.pdf$/i.test(cur)); if (!cur || !/\.pdf$/i.test(cur)) { toggle.hidden = true; } return; }
      toggle.hidden = false;
      if (!more) { grid.replaceChildren(); order = []; }
      const from = order.length, to = Math.min(t, from + 120);
      for (let i = from; i < to; i++) {
        order.push(i);
        const c = h("button", { type: "button", class: "pg-cell", "data-i": i, tip: `Page ${i + 1}. Click to choose or un-choose it.` }, h("img", { src: `/api/pdf/page?path=${encodeURIComponent(cur)}&page=${i}&size=120&t=${encodeURIComponent(F.TOKEN)}`, alt: "", loading: "lazy" }), h("span", { text: String(i + 1) }));
        c.onclick = (e) => {
          let sel = new Set(safeParse());
          if (e.shiftKey && lastClick !== null) { const [a, b] = [Math.min(lastClick, i), Math.max(lastClick, i)]; for (let k = a; k <= b; k++) sel.add(k); }
          else if (sel.has(i)) sel.delete(i); else sel.add(i);
          lastClick = i; input.value = sel.size === t ? "" : compact([...sel]); sync(true);
        };
        grid.append(c);
      }
      if (to < t) { const m = h("button", { type: "button", class: "btn small pg-more", tip: "Shows more pages." }, `Show ${Math.min(120, t - to)} more…`); m.onclick = () => { m.remove(); buildGrid(true); }; grid.append(m); }
      paintGrid();
    }
    let lastClick = null;
    const sync = (fromUser) => { paintGrid(); if (fromUser) changed && changed(); };
    input.addEventListener("input", () => { paintGrid(); changed && changed(); });
    toggle.onclick = () => { grid.hidden = !grid.hidden; toggle.textContent = grid.hidden ? "Click the pages…" : "Hide the pictures"; if (!grid.hidden && !grid.children.length) buildGrid(false); };
    // when the previewed file or page changes, rebuild the thumbnails
    let lastPath = "";
    src.listen((state) => { const key = state.path + "|" + state.pages; if (key === lastPath) return; lastPath = key; lastClick = null; grid.replaceChildren(); order = []; const wasHidden = grid.hidden; buildGrid(false); grid.hidden = wasHidden; paintGrid(); });
    const el = h("div", { class: "pagepicker" }, own ? own.el : null, h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;align-items:center" }, input, toggle, count), chips, grid);
    paintGrid();
    return { el, get: () => input.value.trim(), set: (v) => { input.value = v || ""; paintGrid(); }, count: () => safeParse().length, total, source: src, includes: (pageIndex) => safeParse().includes(pageIndex) };
  };
})();
