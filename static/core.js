/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* Fathom core: helpers, tooltips, the shared file tray, the "where to save" chooser, search-and-pick lists, background jobs. */
(() => {
  "use strict";
  const F = (window.Fathom = {});
  const $ = (id) => document.getElementById(id);
  F.$ = $;
  // the browser's append() writes the word "null" when it is handed null; skip empty arguments instead
  for (const m of ["append", "prepend", "replaceChildren"]) {
    for (const proto of [Element.prototype, DocumentFragment.prototype]) {
      const orig = proto[m]; if (!orig) continue;
      proto[m] = function (...kids) { return orig.apply(this, kids.filter((k) => k != null && k !== false)); };
    }
  }
  F.TOKEN = document.querySelector('meta[name="token"]').content;

  // ---------- helpers (text from files is always inserted as text, never as HTML)
  F.h = function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k === "tip") el.setAttribute("data-tip", v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else if (v !== false && v != null) el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  };
  const h = F.h;
  F.api = async function api(path, { method = "GET", body } = {}) {
    const res = await fetch(path, {
      method,
      headers: { "X-Fathom-Token": F.TOKEN, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { /* not json */ }
    if (!res.ok) throw new Error((data && (data.error || data.detail)) || `Request failed (${res.status})`);
    return data;
  };
  const api = F.api;
  let toastTimer;
  F.toast = function toast(msg, ms) {
    const t = $("toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), ms || 3400);
  };
  F.fmtBytes = (n) => (n >= 1e12 ? (n / 1e12).toFixed(2) + " TB" : n >= 1e9 ? (n / 1e9).toFixed(n >= 1e10 ? 1 : 2) + " GB" : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + " MB" : n >= 1e3 ? Math.round(n / 1e3) + " KB" : (n || 0) + " B");
  F.fmtTime = (s) => (s < 60 ? `${s.toFixed(0)} s` : s < 3600 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`);
  F.baseName = (p) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p;
  F.ext = (p) => { const n = F.baseName(p).toLowerCase(); const i = n.lastIndexOf("."); return i > 0 ? n.slice(i + 1) : ""; };
  F.IMG_EXT = new Set(["jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "ico", "avif", "heic"]);
  F.thumbUrl = (p, size = 160) => `/api/thumb?path=${encodeURIComponent(p)}&size=${size}&t=${encodeURIComponent(F.TOKEN)}`;
  F.copy = async (text) => { try { await navigator.clipboard.writeText(text); F.toast("Copied"); } catch { F.toast("Could not copy"); } };
  F.reveal = (p) => api("/api/reveal", { method: "POST", body: { path: p } }).catch((e) => F.toast(e.message));
  F.openFile = (p) => api("/api/open", { method: "POST", body: { path: p } }).catch((e) => F.toast(e.message));
  // Settings live on the computer (data folder, prefs.json) and are mirrored in the browser's storage, because the app opens on a different port each time and the browser forgets a "different site".
  F.prefs = (() => { try { const x = new XMLHttpRequest(); x.open("GET", "/api/prefs", false); x.setRequestHeader("X-Fathom-Token", F.TOKEN); x.send(); const d = x.status === 200 ? JSON.parse(x.responseText) : null; return d && typeof d === "object" ? d : null; } catch { return null; } })();
  F.save = (key, val) => {
    try { localStorage.setItem("fathom." + key, JSON.stringify(val)); } catch { /* storage off */ }
    if (F.prefs) F.prefs[key] = val;
    try { fetch("/api/prefs", { method: "POST", headers: { "X-Fathom-Token": F.TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ key, value: val === undefined ? null : val }) }).catch(() => {}); } catch { /* offline */ }
  };
  F.load = (key, d) => {
    if (F.prefs && Object.prototype.hasOwnProperty.call(F.prefs, key)) { const v = F.prefs[key]; return v == null ? d : v; }
    try { const v = localStorage.getItem("fathom." + key); return v == null ? d : JSON.parse(v); } catch { return d; }
  };


  // ---------- tooltips: hover (or focus) anything with data-tip to get a small plain-words box
  (function tooltips() {
    const tip = $("tip"); let timer = null, cur = null;
    const textFor = (el) => {
      let t = el._tipFn ? el._tipFn() : el.getAttribute("data-tip");
      return t;
    };
    const render = (t) => {
      tip.replaceChildren();
      const parts = String(t).split("\n");
      parts.forEach((p, i) => {
        const m = /^(On|Off|High|Low|Yes|No|Left|Right):\s*(.*)$/.exec(p);
        if (m && i > 0) tip.append(h("span", { class: "st" }, h("b", { text: m[1] + ": " }), m[2]));
        else tip.append(i ? h("span", { class: "st", text: p }) : document.createTextNode(p));
      });
    };
    const place = (el) => {
      const r = el.getBoundingClientRect(), tw = tip.offsetWidth, th = tip.offsetHeight;
      let x = Math.min(Math.max(8, r.left + r.width / 2 - tw / 2), innerWidth - tw - 8);
      let y = r.bottom + 10;
      if (y + th > innerHeight - 8) y = Math.max(8, r.top - th - 10);
      tip.style.left = x + "px"; tip.style.top = y + "px";
    };
    const show = (el) => {
      const t = textFor(el); if (!t) return;
      cur = el; render(t); tip.classList.remove("on"); place(el); requestAnimationFrame(() => { place(el); tip.classList.add("on"); });
    };
    const hide = () => { clearTimeout(timer); timer = null; cur = null; tip.classList.remove("on"); };
    document.addEventListener("mouseover", (e) => {
      const el = e.target.closest && e.target.closest("[data-tip]");
      if (!el || el === cur) return;
      clearTimeout(timer); timer = setTimeout(() => show(el), 320);
    });
    document.addEventListener("mouseout", (e) => { const el = e.target.closest && e.target.closest("[data-tip]"); if (el && !el.contains(e.relatedTarget)) hide(); });
    document.addEventListener("focusin", (e) => { const el = e.target.closest && e.target.closest("[data-tip]"); if (el) { clearTimeout(timer); timer = setTimeout(() => show(el), 150); } });
    document.addEventListener("focusout", hide);
    document.addEventListener("mousedown", hide);
    document.addEventListener("scroll", hide, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  })();
  /** Gives an element a tooltip. `text` can be a string or a function (so it can change with the current choice). */
  F.tip = (el, text) => { if (!el) return el; if (typeof text === "function") el._tipFn = text; else el.setAttribute("data-tip", text); return el; };

  // ---------- the file tray every tool shares
  F.state = { sources: [], output: F.load("output", { mode: "beside", dir: "", keep_structure: true }), caps: null };
  const norm = (p) => { const q = p.replace(/\//g, "\\").replace(/\\+$/, ""); return /^[A-Za-z]:|^\\\\/.test(q) ? q.toLowerCase() : q; };
  const hosts = new Set();
  F.addPaths = (paths) => {
    let added = 0;
    for (const p of paths || []) {
      if (!p || F.state.sources.some((s) => norm(s) === norm(p))) continue;
      F.state.sources.push(p); added++;
    }
    renderSources();
    if (added) { F.toast(`Added ${added} ${added === 1 ? "item" : "items"}`); F.onSourcesChanged && F.onSourcesChanged(); }
  };
  async function pick(kind) {
    try { F.addPaths(await F.pickPaths(kind)); }
    catch (e) { F.toast(e.message); }
  }
  F.pickOne = async (kind) => { try { return ((await api("/api/pick", { method: "POST", body: { kind } })).paths || [])[0] || ""; } catch (e) { F.toast(e.message); return ""; } };
  function renderSources() {
    for (const host of hosts) {
      const { ul, empty, clear } = host._parts;
      ul.replaceChildren();
      const move = (i, d) => { const a = F.state.sources; const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; renderSources(); };
      F.state.sources.forEach((p, i) => {
        const isLink = /^https?:\/\//i.test(p);
        const isFolder = !isLink && !/\.[A-Za-z0-9]{1,8}$/.test(F.baseName(p));
        const shown = isLink ? p.replace(/^https?:\/\/(www\.)?/i, "") : F.baseName(p);
        ul.append(h("li", { title: p },
          h("span", { text: isLink ? "🔗" : isFolder ? "📁" : "📄" }),
          h("span", { class: "name", text: shown }),
          !isFolder && !isLink && F.editFile ? h("button", { class: "mv", tip: "Open this file in the editor and change what is inside it.", "aria-label": `Edit ${F.baseName(p)}`, onclick: () => F.editFile(p) }, "✏️") : null,
          F.state.sources.length > 1 ? h("button", { class: "mv", tip: "Move this up. The order matters when you merge files.", "aria-label": "Move up", onclick: () => move(i, -1) }, "▲") : null,
          F.state.sources.length > 1 ? h("button", { class: "mv", tip: "Move this down.", "aria-label": "Move down", onclick: () => move(i, 1) }, "▼") : null,
          h("button", { class: "x", tip: "Take this out of the list. The real file is not touched.", "aria-label": `Remove ${F.baseName(p)}`, onclick: () => { F.state.sources.splice(i, 1); renderSources(); F.onSourcesChanged && F.onSourcesChanged(); } }, "×")));
      });
      empty.hidden = F.state.sources.length > 0;
      clear.hidden = F.state.sources.length < 2;
    }
  }
  F.mountSources = (host, hint, extra = {}) => {
    const ul = h("ul", { class: "sources" });
    const empty = h("div", { class: "dropzone", text: hint || "Add as many files and folders as you like, or drag them into this window." });
    const clear = h("button", { class: "link", hidden: true, tip: "Empties the list. Your real files are not touched.", onclick: () => { F.state.sources = []; renderSources(); F.onSourcesChanged && F.onSourcesChanged(); } }, "Remove all");
    let linkRow = null;
    if (extra.links) {
      const box = h("input", { type: "url", placeholder: "Paste a video or picture link, then press Enter", "aria-label": "Link", spellcheck: "false", style: "flex:1;min-width:0" });
      const go = () => {
        const urls = box.value.split(/\s+/).filter((u) => /^https?:\/\//i.test(u));
        if (!urls.length) { F.toast("Paste a link that starts with http:// or https://"); return; }
        F.addPaths(urls); box.value = ""; linkRow.hidden = true;
      };
      box.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
      linkRow = h("div", { class: "row", hidden: true }, box, h("button", { class: "btn small", onclick: go }, "Add"));
      F.tip(box, "A link to a video (YouTube and most video sites) or straight to a video or picture file. Fathom downloads it to this computer and searches it. Several links can be pasted at once, separated by spaces.");
    }
    host.append(
      h("div", { class: "row" },
        h("button", { class: "btn fill", tip: "Choose one or more files from your PC. You can pick as many as you like.", onclick: () => pick("files") }, "Add files…"),
        h("button", { class: "btn fill", tip: "Choose a whole folder. Everything inside it (and its subfolders) is included.", onclick: () => pick("folder") }, "Add folder…"),
        extra.links ? h("button", { class: "btn fill", tip: "Search a video from a web link instead of a file on your PC.", onclick: () => { linkRow.hidden = !linkRow.hidden; if (!linkRow.hidden) linkRow.querySelector("input").focus(); } }, "Add link…") : null),
      linkRow || "", ul, empty, clear);
    host._parts = { ul, empty, clear };
    hosts.add(host); renderSources();
  };

  // ---------- where the results go
  F.mountOutput = (host, opts = {}) => {
    const o = F.state.output;
    const dirBox = h("input", { type: "text", placeholder: "Choose a folder…", value: o.dir, readonly: true, style: "flex:1;min-width:0" });
    const keep = h("input", { type: "checkbox" }); keep.checked = o.keep_structure !== false;
    const rBeside = h("input", { type: "radio", name: "out-" + Math.random() }); const rFolder = h("input", { type: "radio", name: rBeside.name });
    rBeside.checked = o.mode !== "folder"; rFolder.checked = o.mode === "folder";
    const sync = () => {
      o.mode = rFolder.checked && o.dir ? "folder" : "beside"; o.keep_structure = keep.checked; F.save("output", o);
      dirBox.disabled = !rFolder.checked; keepRow.hidden = !rFolder.checked;
      for (const h2 of outHosts) if (h2 !== host) h2._sync && h2._sync();
    };
    const keepRow = h("label", { tip: "On: files from folders you added are saved into matching subfolders, so nothing gets mixed up.\nOff: everything lands in one flat folder." }, keep, "Keep the same folder layout");
    const browse = h("button", { class: "btn small", tip: "Choose the folder where the new files will be saved. You can create a new folder in that window.", onclick: async () => { const p = await F.pickOne("outfolder"); if (p) { o.dir = p; dirBox.value = p; rFolder.checked = true; sync(); } } }, "Browse…");
    rBeside.addEventListener("change", sync); rFolder.addEventListener("change", sync); keep.addEventListener("change", sync);
    host.append(h("div", { class: "opts" },
      h("label", { tip: "The new file is saved in the same folder as the original, with a slightly different name. Nothing is ever overwritten." }, rBeside, "Next to the original files"),
      h("label", { tip: "All new files are saved into one folder you choose." }, rFolder, "In a folder I choose"),
      h("div", { class: "row" }, dirBox, browse), keepRow));
    host._sync = () => { rBeside.checked = o.mode !== "folder"; rFolder.checked = o.mode === "folder"; dirBox.value = o.dir; keep.checked = o.keep_structure !== false; dirBox.disabled = !rFolder.checked; keepRow.hidden = !rFolder.checked; };
    outHosts.add(host); sync();
  };
  const outHosts = new Set();
  F.outputBody = () => ({ mode: F.state.output.mode, dir: F.state.output.dir, keep_structure: F.state.output.keep_structure });

  // ---------- a search box with a drop-down list (used to pick file types)
  F.combo = ({ placeholder = "Search…", options = [], onPick, tipText, allowEmpty = false }) => {
    const input = h("input", { type: "text", placeholder, autocomplete: "off", spellcheck: "false", "aria-label": placeholder });
    if (tipText) F.tip(input, tipText);
    const list = h("div", { class: "list", hidden: true, role: "listbox" });
    const el = h("div", { class: "combo" }, h("span", { class: "mag", text: "🔍" }), input, list);
    let opts = options, filtered = [], act = -1, category = "", value = "";
    const label = (o) => (o.label || o.id);
    function draw() {
      const q = input.value.trim().toLowerCase();
      const raw = input.dataset.picked === input.value ? "" : q;
      filtered = opts.filter((o) => (!category || o.category === category) && (!raw || `${o.id} ${label(o)} ${o.category} ${o.keywords || ""}`.toLowerCase().includes(raw)));
      list.replaceChildren();
      if (!filtered.length) list.append(h("div", { class: "none", text: "No file type matches. Try its extension (like png) or a word (like picture)." }));
      let lastCat = null;
      filtered.forEach((o, i) => {
        if (o.category !== lastCat) { lastCat = o.category; list.append(h("div", { class: "grp", text: F.CAT_LABEL[o.category] || o.category })); }
        list.append(h("div", { class: "opt" + (i === act ? " act" : ""), role: "option", onmousedown: (e) => { e.preventDefault(); choose(o); } },
          h("span", { text: label(o) }), h("small", { text: (o.note || "") || "." + o.id })));
      });
      const a = list.querySelector(".act"); if (a) a.scrollIntoView({ block: "nearest" });
    }
    function choose(o) { value = o ? o.id : ""; input.value = o ? label(o) : ""; input.dataset.picked = input.value; list.hidden = true; onPick && onPick(o); }
    input.addEventListener("focus", () => { input.select(); act = -1; list.hidden = false; draw(); });
    input.addEventListener("input", () => { act = 0; input.dataset.picked = ""; list.hidden = false; draw(); });
    input.addEventListener("blur", () => { setTimeout(() => { list.hidden = true; if (!value && !allowEmpty) input.value = ""; else if (value) { const o = opts.find((x) => x.id === value); if (o) input.value = label(o); } }, 120); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); act = Math.min(filtered.length - 1, act + 1); draw(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); act = Math.max(0, act - 1); draw(); }
      else if (e.key === "Enter") { e.preventDefault(); if (filtered[Math.max(act, 0)]) choose(filtered[Math.max(act, 0)]); }
      else if (e.key === "Escape") { list.hidden = true; input.blur(); }
    });
    return { el, input, setOptions(o) { opts = o; if (!list.hidden) draw(); }, setCategory(c) { category = c; if (!list.hidden) draw(); }, set(id) { value = id || ""; const o = opts.find((x) => x.id === id); input.value = o ? label(o) : ""; input.dataset.picked = input.value; }, get value() { return value; } };
  };
  F.CAT_LABEL = { image: "Pictures", video: "Video", audio: "Audio", document: "Documents", presentation: "Presentations", spreadsheet: "Spreadsheets", data: "Data", text: "Text and code", ebook: "E-books", subtitle: "Subtitles", font: "Fonts", mesh: "3D models", archive: "Archives and folders", other: "Other" };

  // ---------- background jobs: progress bar, per-file results, stop button
  const EMOJI = { image: "🖼", video: "🎞", audio: "🎵", document: "📄", presentation: "📊", spreadsheet: "📈", data: "🧮", text: "📝", ebook: "📚", archive: "🗜", font: "🔤", mesh: "🧊", subtitle: "💬" };
  F.JobPanel = class {
    constructor(host, { noun = "file", onDone, renderItem, summary = true } = {}) {
      this.host = host; this.noun = noun; this.onDone = onDone; this.renderItem = renderItem; this.id = null; this.next = 0; this.items = []; this.wantSummary = summary;
      this.fill = h("i"); this.bar = h("div", { class: "bar" }, this.fill);
      this.title = h("strong"); this.detail = h("span");
      this.stopBtn = h("button", { class: "btn small danger", tip: "Stops the work. Files that are already finished are kept.", onclick: () => this.stop() }, "Stop");
      this.waitNote = h("div", { class: "waitnote", hidden: true });
      this.progress = h("section", { class: "progress", hidden: true, "aria-live": "polite" }, this.bar, h("div", { class: "progress-text" }, this.title, this.detail, this.stopBtn), this.waitNote);
      this.sum = h("div", { class: "summary", hidden: true });
      this.list = h("div", { class: "joblist" });
      host.append(this.progress, this.sum, this.list);
    }
    reset() { this.id = null; this.next = 0; this.items = []; this.list.replaceChildren(); this.sum.hidden = true; this.progress.hidden = true; this.waitNote.hidden = true; }
    start(jobId) { this.reset(); this.id = jobId; this.progress.hidden = false; this.stopBtn.hidden = false; this.stopBtn.disabled = false; this.title.textContent = "Starting…"; this.bar.classList.add("busy"); this.poll(); }
    async stop() { if (!this.id) return; try { await api(`/api/ops/${this.id}/cancel`, { method: "POST" }); this.title.textContent = "Stopping…"; } catch (e) { F.toast(e.message); } }
    async poll() {
      const id = this.id; if (!id) return;
      let s;
      try { s = await api(`/api/ops/${id}?since=${this.next}`); }
      catch (e) { this.title.textContent = "Lost contact with Fathom's engine"; this.detail.textContent = e.message; this.bar.classList.remove("busy"); this.stopBtn.hidden = true; return; }
      if (id !== this.id) return;
      this.next = s.next;
      for (const r of s.results) { this.items.push(r); this.list.append(this.renderItem ? this.renderItem(r) : F.defaultItem(r)); }
      const det = s.total > 0;
      this.bar.classList.toggle("busy", !det);
      this.fill.style.width = det ? `${Math.round(s.progress * 100)}%` : "";
      this.title.textContent = det ? `${s.done} of ${s.total} ${this.noun}${s.total === 1 ? "" : "s"}` : "Getting ready…";
      this.detail.textContent = s.message || "";
      if (!["done", "cancelled", "failed"].includes(s.status) && (s.elapsed || 0) >= 5 && F.waitText) { this.waitNote.textContent = F.waitText(s.elapsed, null, det ? s.progress : null); this.waitNote.hidden = false; }
      if (["done", "cancelled", "failed"].includes(s.status)) return this.finish(s);
      setTimeout(() => this.poll(), this.items.length < 40 ? 350 : 800);
    }
    finish(s) {
      this.waitNote.hidden = true;
      this.bar.classList.remove("busy"); this.bar.classList.add("idle"); this.stopBtn.hidden = true;
      this.fill.style.width = s.status === "failed" ? "0%" : "100%";
      const c = s.counts || {};
      this.title.textContent = s.status === "failed" ? "Could not finish" : s.status === "cancelled" ? "Stopped" : "Done";
      this.detail.textContent = (s.status === "failed" ? s.message : `${F.fmtTime(s.elapsed)}`) || "";
      if (this.wantSummary) {
        this.sum.replaceChildren(); this.sum.hidden = false;
        const stat = (b, t) => h("div", { class: "stat" }, h("b", { text: b }), h("span", { text: t }));
        this.sum.append(stat(String(c.done || 0), "finished"));
        if (c.error) this.sum.append(stat(String(c.error), "had a problem"));
        if (c.skipped) this.sum.append(stat(String(c.skipped), "skipped"));
        if (s.bytes_in && s.bytes_out && s.kind === "size") this.sum.append(stat(`${F.fmtBytes(s.bytes_in)} → ${F.fmtBytes(s.bytes_out)}`, "total size"));
      }
      this.data = s.data; this.status = s;
      try { F.jobFinished && F.jobFinished(s, this.noun); } catch (e) { /* never block */ }
      this.onDone && this.onDone(s, this.items);
    }
  };
  F.defaultItem = (r) => {
    const first = r.outputs && r.outputs[0];
    const isImg = first && !first.dir && F.IMG_EXT.has(F.ext(first.path));
    const ico = h("div", { class: "ico" }, isImg ? h("img", { src: F.thumbUrl(first.path), alt: "", loading: "lazy", onerror: (e) => e.target.replaceWith(document.createTextNode("🖼")) }) : (r.status === "error" ? "⚠️" : first && first.dir ? "📁" : "📄"));
    const delta = r.bytes_in && r.bytes_out ? (() => { const d = Math.round((1 - r.bytes_out / r.bytes_in) * 100); return `${F.fmtBytes(r.bytes_in)} → ${F.fmtBytes(r.bytes_out)}` + (d > 0 ? `  (${d}% smaller)` : d < 0 ? `  (${-d}% bigger)` : ""); })() : "";
    const note = r.status === "error" ? r.error : r.status === "cancelled" ? "Stopped before this one." : (r.note || "");
    const acts = h("div", { class: "acts" });
    if (first) {
      acts.append(h("button", { class: "btn small", tip: "Opens the folder that holds the new file, with the file selected.", onclick: () => F.reveal(first.path) }, "Show"));
      if (!first.dir) acts.append(h("button", { class: "btn small", tip: "Opens the new file in your usual program for it.", onclick: () => F.openFile(first.path) }, "Open"));
    }
    const pr = F.proofToggle && r.extra && r.extra.proof && r.extra.proof.length ? F.proofToggle(r.extra.proof) : null;
    if (pr) acts.prepend(pr.btn);
    return h("div", { class: "job " + r.status },
      ico,
      h("div", { class: "t" }, h("b", { text: first ? (r.outputs.length > 1 ? `${r.name}  →  ${r.outputs.length} files` : first.name) : r.name }), h("small", { text: [note, delta && r.status === "done" ? "" : ""].filter(Boolean).join("  ·  ") }), delta ? h("small", { class: "delta", text: delta }) : null, pr ? pr.wrap : null),
      acts);
  };
  F.CATEGORY_EMOJI = EMOJI;

  // ---------- tool registry (the bars at the top)
  F.tools = []; F.groups = [];
  F.addGroup = (id, label) => F.groups.push({ id, label });
  F.addTool = (t) => F.tools.push(t);
  F.currentTool = null;
  F.show = (id) => {
    const t = F.tools.find((x) => x.id === id) || F.tools[0];
    F.currentTool = t; F.save("tool", t.id);
    if (!t.built && t.build) { t.built = true; const placeholder = t.el; t.build(placeholder); }
    for (const x of F.tools) { if (x.el) x.el.classList.toggle("on", x === t); }
    for (const b of document.querySelectorAll("#groups button")) b.setAttribute("aria-selected", b.dataset.g === t.group);
    { const on = document.querySelector('#groups button[aria-selected="true"]'); if (on && on.scrollIntoView) on.scrollIntoView({ inline: "nearest", block: "nearest" }); }
    for (const b of document.querySelectorAll("#tools button")) { b.setAttribute("aria-selected", b.dataset.t === t.id); }
    renderToolBar(t.group);
    t.onShow && t.onShow(t);
  };
  function renderToolBar(group) {
    const bar = $("tools"); bar.replaceChildren();
    for (const t of F.tools.filter((x) => x.group === group)) {
      bar.append(h("button", { role: "tab", "data-t": t.id, "aria-selected": F.currentTool === t, tip: t.blurb, onclick: () => F.show(t.id) }, h("span", { class: "ic", text: t.icon }), t.label));
    }
  }
  F.buildNav = () => {
    const g = $("groups"); g.replaceChildren();
    for (const grp of F.groups) g.append(h("button", { role: "tab", "data-g": grp.id, onclick: () => { const first = F.tools.find((t) => t.group === grp.id); if (first) F.show(first.id); } }, grp.label));
  };
  F.makeView = (id, withFiles = true) => {
    const sec = h("section", { class: "view" + (withFiles ? "" : " nofiles"), "data-view": id, id: "v-" + id });
    $("stage").append(sec); return sec;
  };
  // handy: a "side + main" view with the file tray and the where-to-save chooser
  F.standardView = (id, { files = true, output = true, sideExtra, hint } = {}) => {
    const sec = F.makeView(id, files || output);
    const side = h("aside", { class: "side" }); const main = h("main", { class: "main" });
    if (files) { const b = h("section", { class: "block" }, h("h2", { text: "Files" })); const hs = h("div"); b.append(hs); F.mountSources(hs, hint); side.append(b); }
    if (sideExtra) side.append(...[].concat(sideExtra));
    if (output) { const b = h("section", { class: "block" }, h("h2", { text: "Where to save" })); const ho = h("div"); b.append(ho); F.mountOutput(ho); side.append(b); }
    sec.append(side, main);
    if (!files && !output && !sideExtra) { sec.classList.add("nofiles"); side.remove(); }
    return { sec, side, main };
  };
  F.titleBlock = (title, sub) => h("div", {}, h("h1", { class: "page-title", text: title }), h("p", { class: "page-sub", text: sub }));
  F.needFiles = () => { if (!F.state.sources.length) { F.toast("Add at least one file or folder first (on the left)."); return false; } return true; };
})();
