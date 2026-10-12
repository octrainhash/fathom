/* Find: words, numbers and objects in any file, with highlighted pictures and slow-motion clips. */
(() => {
  "use strict";
  const F = window.Fathom, $ = F.$, h = F.h, api = F.api;
  const state = { mode: "text", preset: "words", clipmode: "result", jobId: null, running: false, next: 0, results: [], filter: "all", text: "", group: false, caps: null, groups: new Map() };
  const KIND_LABEL = { text: "Text", object: "Object", video: "Video", speech: "Spoken", change: "Change" };

  F.mountSources($("v-find").querySelector(".sources-host"));

  // ---------- what to find
  const PRESETS = {
    words:   { mode: "text",   only: [], hint: "Finds the characters you type in any file: documents, code, spreadsheets, PDFs, pictures and screenshots (OCR), and video frames.", ph: "Type words, numbers or a pattern…" },
    seen:    { mode: "text",   only: ["pictures", "videos"], hint: "Finds words you can SEE: signs, screenshots, slides, subtitles and photos of paper, in pictures and video frames. Tick Documents under “Look in” to include scanned PDFs too.", ph: "Words written in the picture or on screen, e.g. EXIT, invoice 4821" },
    spoken:  { mode: "text",   only: ["videos", "audio"], hint: "Finds words that are SAID in videos and audio recordings, like searching a transcript. Every match gives you the moment, with a clip for videos.", ph: "Words someone says, e.g. refund, birthday, next quarter" },
    objects: { mode: "object", only: [], hint: "Finds the actual thing, not the word. “butterfly” finds butterflies in pictures, PDF pages and videos, and ignores the written word.", ph: "What should I look for?  e.g. butterfly, red car, fire" },
    objpic:  { mode: "object", only: ["pictures"], hint: "Finds the actual thing in pictures, photos and scanned pages only. “dog” finds dogs, not the word.", ph: "What should I look for in pictures?  e.g. dog, bicycle, sunset" },
    objvid:  { mode: "object", only: ["videos"], hint: "Finds the actual thing in videos only. Every match gives you a still and a slow-motion clip of the moment it appears.", ph: "What should I look for in videos?  e.g. person in a red coat, fire" },
  };
  const KINDS = ["documents", "pictures", "videos", "audio"];
  const lookIn = () => KINDS.filter((k) => $("in-" + k).checked);
  function setPreset(id, keepFilter) {
    if (!PRESETS[id]) id = "words";
    const P = PRESETS[id];
    state.preset = id; state.mode = P.mode;
    for (const b of document.querySelectorAll("#kinds .choice")) b.setAttribute("aria-pressed", b.dataset.p === id);
    if (!keepFilter) for (const k of KINDS) $("in-" + k).checked = !P.only.length || P.only.includes(k);
    $("text-opts").hidden = P.mode !== "text";
    $("object-opts").hidden = P.mode !== "object";
    let hint = P.hint;
    if (P.mode === "object" && state.caps && !state.caps.objects_model_ready) hint += " The first object search downloads a 600 MB model (needs internet, once).";
    if (id === "spoken" && state.caps && !state.caps.speech) hint += " The speech engine is not installed yet: run Fathom.bat repair with internet.";
    $("mode-hint").textContent = hint;
    $("query").placeholder = P.ph;
    saveOptions();
  }
  function setClipMode(m) {
    state.clipmode = m;
    for (const b of document.querySelectorAll("#clipmode .choice")) b.setAttribute("aria-pressed", b.dataset.v === m);
    $("slow-row").style.opacity = m === "pause" ? ".4" : "1"; $("opt-slow").disabled = m === "pause";
    syncLabels(); saveOptions();
  }
  const num = (id, d) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : d; };
  function options() {
    const o = {
      mode: state.mode,
      case_sensitive: $("opt-case").checked, whole_word: $("opt-word").checked, use_regex: $("opt-regex").checked, ocr: $("opt-ocr").checked, handwriting: $("opt-hand").checked,
      strictness: num("opt-strict", 60) / 100, thorough: $("opt-thorough").checked,
      recursive: $("opt-recursive").checked, skip_junk: $("opt-junk").checked, include_cloud: $("opt-cloud").checked,
      scan_every: num("opt-every", 1), slowmo: num("opt-slow", 4), before: num("opt-before", 2), after: num("opt-after", 2), hold: num("opt-hold", 2), clipmode: state.clipmode,
      changes: $("opt-changes").checked, listen: $("opt-listen").checked, speech_model: $("opt-model").value,
    };
    const only = lookIn(); if (only.length < KINDS.length) o.only = only;
    if (state.preset === "seen") Object.assign(o, { ocr: true, media_text: true, media_speech: false, listen: false });
    else if (state.preset === "spoken") Object.assign(o, { media_text: false, media_speech: true, listen: true });
    else if (state.mode === "object") Object.assign(o, { media_object: true, media_text: false, media_speech: false, listen: false });
    return o;
  }
  const OPTION_IDS = ["opt-case", "opt-word", "opt-regex", "opt-ocr", "opt-hand", "opt-strict", "opt-thorough", "opt-recursive", "opt-junk", "opt-cloud", "opt-every", "opt-slow", "opt-before", "opt-after", "opt-hold", "opt-changes", "opt-listen", "opt-model", "in-documents", "in-pictures", "in-videos", "in-audio"];
  function saveOptions() {
    F.save("find", { mode: state.mode, preset: state.preset, clipmode: state.clipmode, v: Object.fromEntries(OPTION_IDS.map((id) => [id, $(id).type === "checkbox" ? $(id).checked : $(id).value])) });
  }
  function restoreOptions() {
    const saved = F.load("find", null);
    if (!saved) return;
    for (const [id, val] of Object.entries(saved.v || {})) { const el = $(id); if (!el) continue; if (el.type === "checkbox") el.checked = !!val; else el.value = val; }
    state.mode = saved.mode === "object" ? "object" : "text";
    state.preset = PRESETS[saved.preset] ? saved.preset : (state.mode === "object" ? "objects" : "words");
    state.clipmode = ["pause", "result", "all"].includes(saved.clipmode) ? saved.clipmode : "result";
  }
  function syncLabels() {
    $("strict-out").textContent = `${$("opt-strict").value}%`;
    $("slow-out").textContent = `${$("opt-slow").value}×`;
    $("model-row").hidden = !$("opt-listen").checked;
    // how long will a clip be? (shown so the numbers above are easy to understand)
    const b = num("opt-before", 2), a = num("opt-after", 2), hold = num("opt-hold", 2), f = state.clipmode === "pause" ? 1 : num("opt-slow", 4), m = 2;
    const total = state.clipmode === "all" ? (b + m + a) * f + hold : b + m * f + a + hold;
    const parts = [`${b} s before`, state.clipmode === "pause" ? `${m} s of the result` : `${m} s of the result at ${f}× slow`, `${a} s after`];
    if (hold > 0) parts.push(`${hold} s stopped on the full result`);
    $("clipcalc").replaceChildren("A result that stays on screen for ", h("b", { text: `${m} seconds` }), ` makes a clip of about `, h("b", { text: `${+total.toFixed(1)} seconds` }), `: ${parts.join(" + ")}.`);
  }

  // ---------- searching
  const showError = (msg) => { const e = $("query-error"); e.textContent = msg; e.hidden = false; };
  const hideError = () => { $("query-error").hidden = true; };
  function setRunning(on) { state.running = on; const go = $("go"); go.textContent = on ? "Stop" : "Search"; go.classList.toggle("stop", on); }
  function clearResults(title = "Searching…", text = "Results appear here as soon as they are found.") {
    state.results = []; state.next = 0; state.groups = new Map();
    $("results").replaceChildren(); $("toolbar").hidden = true; $("errors").hidden = true;
    $("empty").hidden = false; $("empty-title").textContent = title; $("empty-text").textContent = text;
    state.filter = "all"; state.text = ""; $("filter").value = "";
  }
  async function startSearch() {
    if (state.running) { stopSearch(); return; }
    hideError();
    const query = $("query").value.trim();
    if (!query) return showError("Type what to look for first.");
    if (!F.state.sources.length) return showError("Add at least one file or folder first (on the left).");
    try {
      const r = await api("/api/search", { method: "POST", body: { query, paths: F.state.sources, options: options() } });
      clearResults();
      state.jobId = r.job; setRunning(true);
      renderProgress({ status: "starting", files_done: 0, files_total: 0, files_found: 0, message: "", current: "" });
      poll();
    } catch (e) { showError(e.message); }
  }
  async function stopSearch() {
    if (!state.jobId) return;
    try { await api(`/api/jobs/${state.jobId}/cancel`, { method: "POST" }); $("progress-title").textContent = "Stopping…"; } catch (e) { F.toast(e.message); }
  }
  async function poll() {
    const id = state.jobId; if (!id) return;
    let s;
    try { s = await api(`/api/jobs/${id}?since=${state.next}`); }
    catch (e) { setRunning(false); $("progress-title").textContent = "Lost contact with Fathom's engine"; $("progress-detail").textContent = e.message; return; }
    if (id !== state.jobId) return;
    state.next = s.next;
    if (s.results.length) addResults(s.results);
    renderProgress(s); renderErrors(s);
    if (["done", "cancelled", "failed"].includes(s.status)) return finish(s);
    setTimeout(poll, state.results.length < 60 ? 350 : 800);
  }
  function renderProgress(s) {
    $("progress").hidden = false;
    const bar = $("progress").querySelector(".bar");
    const determinate = s.status === "searching" && s.files_total > 0;
    bar.classList.toggle("busy", !determinate); bar.classList.remove("idle");
    $("bar-fill").style.width = determinate ? `${Math.min(100, (s.files_done / s.files_total) * 100)}%` : "";
    let title = s.status === "searching" ? `${s.files_done.toLocaleString()} of ${s.files_total.toLocaleString()} files` : s.files_found ? `Finding files… ${s.files_found.toLocaleString()}` : "Getting ready…";
    if (state.results.length) title += `  ·  ${state.results.length.toLocaleString()} found`;
    $("progress-title").textContent = title;
    $("progress-detail").textContent = s.message || s.current || "";
  }
  function finish(s) {
    setRunning(false);
    const bar = $("progress").querySelector(".bar"); bar.classList.remove("busy"); bar.classList.add("idle");
    const n = state.results.length;
    if (s.status === "failed") {
      $("progress-title").textContent = "The search could not finish";
      $("progress-detail").textContent = s.message || "See the log for details.";
    } else {
      $("bar-fill").style.width = "100%";
      $("progress-title").textContent = `${s.status === "cancelled" ? "Stopped" : "Done"}  ·  ${n.toLocaleString()} ${n === 1 ? "match" : "matches"} in ${s.files_done.toLocaleString()} ${s.files_done === 1 ? "file" : "files"}  ·  ${F.fmtTime(s.elapsed)}`;
      $("progress-detail").textContent = s.skipped_count ? `${s.skipped_count} items skipped (online-only cloud files or folders that could not be opened)` : "";
    }
    if (!n) {
      $("empty").hidden = false;
      $("empty-title").textContent = "No matches";
      $("empty-text").textContent = state.mode === "object"
        ? "Object search looks at what is pictured, not at written words. Try a simpler name (“dog”, not “my dog Rex”), lower the strictness, or turn on “Look closely”."
        : "Nothing matched. Try turning off “Whole word” or “Match case”, check the regular expression, or make sure “Read text inside pictures” is on.";
    }
  }
  function renderErrors(s) {
    const box = $("errors");
    if (!s.error_count) { box.hidden = true; return; }
    box.hidden = false;
    $("errors-title").textContent = `${s.error_count} ${s.error_count === 1 ? "file" : "files"} could not be fully read`;
    $("errors-list").replaceChildren(...s.errors.map((e) => h("li", {}, h("b", { text: e.file }), "  ", e.error)));
  }

  // ---------- results
  const matches = (r) => (state.filter === "all" || r.kind === state.filter) && (!state.text || `${r.file} ${r.where} ${(r.snippet || []).join("")}`.toLowerCase().includes(state.text));
  const badgeText = (r) => (r.kind === "object" && r.score != null ? `Object ${Math.round(r.score * 100)}%` : KIND_LABEL[r.kind] || r.kind);
  function makeCard(r, idx) {
    const [pre, hit, post] = r.snippet && r.snippet.length === 3 ? r.snippet : ["", (r.snippet || [""])[0], ""];
    const card = h("article", { class: "card" },
      h("button", { class: "thumb", "aria-label": `Open match in ${r.file}`, onclick: () => openLightbox(idx) },
        h("img", { src: r.thumb, loading: "lazy", alt: "" }),
        h("span", { class: "badge", text: badgeText(r) }),
        r.clip && r.still ? h("span", { class: "badge pair", text: "clip + still" }) : null,
        r.clip || r.audio ? h("span", { class: "play", text: "▶" }) : null),
      h("div", { class: "meta" },
        h("p", { class: "snip" }, pre, h("mark", { text: hit }), post),
        h("p", { class: "where" }, h("span", { class: "file", title: r.file, text: "‎" + r.file + "‎" }), h("span", { class: "loc", text: r.where + (r.clip_len ? `  ·  ${r.clip_len}s clip` : "") }))));
    card.hidden = !matches(r);
    return card;
  }
  function place(card, r) {
    const host = $("results");
    if (!state.group) { host.append(card); return; }
    let g = state.groups.get(r.file);
    if (!g) {
      g = { count: 0, head: h("div", { class: "group-head" }), cards: h("div", { class: "group-grid" }) };
      g.wrap = h("div", { class: "group" }, g.head, g.cards);
      state.groups.set(r.file, g); host.append(g.wrap);
    }
    g.count++;
    g.head.replaceChildren(h("span", { text: r.file }), h("small", { text: `${g.count} ${g.count === 1 ? "match" : "matches"}` }));
    g.cards.append(card);
  }
  function addResults(list) {
    $("empty").hidden = true; $("toolbar").hidden = false;
    for (const r of list) { const i = state.results.push(r) - 1; r._card = makeCard(r, i); place(r._card, r); }
    renderChips();
  }
  function rerender() { $("results").replaceChildren(); state.groups = new Map(); state.results.forEach((r, i) => { r._card = makeCard(r, i); place(r._card, r); }); applyFilter(); }
  function applyFilter() {
    for (const r of state.results) r._card.hidden = !matches(r);
    if (state.group) for (const g of state.groups.values()) g.wrap.hidden = ![...g.cards.children].some((c) => !c.hidden);
    renderChips();
  }
  function renderChips() {
    const counts = { all: state.results.length };
    for (const r of state.results) counts[r.kind] = (counts[r.kind] || 0) + 1;
    $("chips").replaceChildren(...["all", ...Object.keys(KIND_LABEL).filter((k) => counts[k])].map((k) =>
      h("button", { "aria-pressed": state.filter === k, tip: k === "all" ? "Show every kind of result." : `Show only ${KIND_LABEL[k].toLowerCase()} results.`, onclick: () => { state.filter = k; applyFilter(); } }, k === "all" ? "All" : KIND_LABEL[k], h("b", { text: counts[k] }))));
  }

  // ---------- viewer: a result with a clip shows the clip and the still of the full result side by side, as ONE result
  const lb = { order: [], pos: 0, tab: "both" };
  const visibleIndexes = () => state.results.map((r, i) => (matches(r) ? i : -1)).filter((i) => i >= 0);
  const current = () => state.results[lb.order[lb.pos]];
  function openLightbox(i) { lb.order = visibleIndexes(); lb.pos = Math.max(0, lb.order.indexOf(i)); lb.tab = "both"; $("lightbox").hidden = false; showMatch(); $("lb-close").focus(); }
  function closeLightbox() { $("lightbox").hidden = true; $("lb-stage").replaceChildren(); }
  function stillImg(r, fit) {
    const img = h("img", { src: r.still || r.image, alt: "The full result, highlighted, circled and pointed at" });
    if (fit) {
      const fitIt = () => { const k = Math.min(fit.clientWidth / img.naturalWidth, fit.clientHeight / img.naturalHeight, 2.5); if (k > 0 && Number.isFinite(k)) { img.style.width = `${Math.round(img.naturalWidth * k)}px`; img.style.height = `${Math.round(img.naturalHeight * k)}px`; } };
      img.addEventListener("load", fitIt);
      img.addEventListener("click", () => { const z = img.classList.toggle("zoomed"); fit.classList.toggle("zoomed", z); if (z) { img.style.width = `${img.naturalWidth}px`; img.style.height = `${img.naturalHeight}px`; } else fitIt(); });
    }
    return img;
  }
  function clipEl(r, stage) {
    const v = h("video", { src: r.clip, controls: true, autoplay: true, loop: true, muted: true, playsinline: true });
    v.addEventListener("error", () => stage.append(h("p", { class: "lb-note" }, "This window could not play the clip. ", h("a", { href: r.clip, download: "fathom-clip.mp4", text: "Save the clip" }), " and open it in any video player.")));
    return v;
  }
  function showMatch() {
    const r = current(); if (!r) return;
    $("lb-file").textContent = r.file;
    $("lb-where").textContent = r.where + (r.kind === "object" && r.score != null ? `  ·  ${Math.round(r.score * 100)}% sure` : "") + (r.count > 1 ? `  ·  ${r.count} results marked` : "");
    const [pre, hit, post] = r.snippet && r.snippet.length === 3 ? r.snippet : ["", "", ""];
    $("lb-snippet").replaceChildren(pre, h("mark", { text: hit }), post);
    const hasClip = !!r.clip;
    $("lb-tabs").hidden = !hasClip;
    for (const [id, k] of [["tab-both", "both"], ["tab-clip", "clip"], ["tab-shot", "shot"]]) $(id).setAttribute("aria-pressed", lb.tab === k);
    const stage = $("lb-stage"); stage.replaceChildren(); stage.classList.remove("zoomed");
    if (hasClip && lb.tab === "both") {
      stage.append(h("div", { class: "lb-pair" },
        h("figure", {}, clipEl(r, stage), h("figcaption", { text: `Clip${r.clip_len ? ` · ${r.clip_len} s` : ""}: every result is circled and pointed at while it is on screen` })),
        h("figure", {}, stillImg(r, null), h("figcaption", { text: `Still of the full result${r.peak ? ` · ${r.peak}` : ""}` }))));
    } else if (hasClip && lb.tab === "clip") stage.append(clipEl(r, stage));
    else { stage.append(stillImg(r, stage)); if (r.audio) stage.append(h("audio", { src: r.audio, controls: true })); }
    $("lb-save").href = r.image;
    $("lb-save").setAttribute("download", `fathom-${F.baseName(r.file).replace(/[^\w.-]+/g, "_")}.${r.image.split(".").pop()}`);
    $("lb-prev").hidden = $("lb-next").hidden = lb.order.length < 2;
  }
  const step = (d) => { if (lb.order.length < 2) return; lb.pos = (lb.pos + d + lb.order.length) % lb.order.length; showMatch(); };

  // ---------- engine status, storage
  async function refreshCaps() {
    try {
      state.caps = await api("/api/capabilities");
      const c = state.caps, chip = $("engine"), warm = c.warm || {};
      if (warm.state === "ready") { chip.textContent = "Ready"; chip.className = "chip ok"; }
      else if (warm.state === "error") { chip.textContent = "Engine problem, see logs"; chip.className = "chip warn"; }
      else { chip.textContent = "Loading models…"; chip.className = "chip"; setTimeout(refreshCaps, 1500); }
      $("opt-ocr").disabled = !c.ocr;
      for (const id of ["kind-objects", "kind-objpic", "kind-objvid"]) $(id).disabled = !c.objects;
      $("kind-spoken").disabled = !c.speech;
      $("opt-listen").disabled = !c.speech; $("listen-note").textContent = c.speech ? "" : "(not installed)";
      if ((!c.objects && state.mode === "object") || (!c.speech && state.preset === "spoken")) state.preset = "words";
      setPreset(state.preset, true);
    } catch { setTimeout(refreshCaps, 2000); }
  }
  async function storageClick() {
    try {
      const s = await api("/api/storage");
      if (!confirm(`Fathom keeps the pictures and clips of your matches on this PC (${F.fmtBytes(s.results_bytes)}).\n\nDelete them now? Your own files are never touched.`)) return;
      const r = await api("/api/storage/clear", { method: "POST" });
      clearResults("Find it in anything.", "Saved results deleted."); $("progress").hidden = true;
      F.toast(`Freed ${F.fmtBytes(r.freed_bytes)}`);
    } catch (e) { F.toast(e.message); }
  }

  function wire() {
    for (const b of document.querySelectorAll("#kinds .choice")) b.onclick = () => setPreset(b.dataset.p);
    for (const k of KINDS) $("in-" + k).addEventListener("change", (e) => { if (!lookIn().length) { e.target.checked = true; F.toast("Pick at least one kind of file to look in."); } });
    for (const b of document.querySelectorAll("#clipmode .choice")) b.onclick = () => setClipMode(b.dataset.v);
    $("go").onclick = startSearch;
    $("query").addEventListener("keydown", (e) => { if (e.key === "Enter") startSearch(); });
    $("filter").addEventListener("input", (e) => { state.text = e.target.value.trim().toLowerCase(); applyFilter(); });
    $("group").addEventListener("change", (e) => { state.group = e.target.checked; rerender(); });
    for (const id of OPTION_IDS) $(id).addEventListener("input", () => { syncLabels(); saveOptions(); });
    $("storage").onclick = storageClick;
    $("lb-close").onclick = closeLightbox; $("lb-prev").onclick = () => step(-1); $("lb-next").onclick = () => step(1);
    $("tab-both").onclick = () => { lb.tab = "both"; showMatch(); };
    $("tab-clip").onclick = () => { lb.tab = "clip"; showMatch(); };
    $("tab-shot").onclick = () => { lb.tab = "shot"; showMatch(); };
    $("lb-open").onclick = () => F.openFile(current().path);
    $("lb-reveal").onclick = () => F.reveal(current().path);
    $("lightbox").addEventListener("click", (e) => { if (e.target === $("lightbox") || e.target === $("lb-stage")) closeLightbox(); });
    document.addEventListener("keydown", (e) => {
      if ($("lightbox").hidden) return;
      if (e.key === "Escape") closeLightbox(); else if (e.key === "ArrowLeft") step(-1); else if (e.key === "ArrowRight") step(1);
    });
  }
  // ---------- show the video and audio options only when the added files really contain video or audio
  let mediaTimer = null, mediaSeq = 0;
  function applyMedia(counts) {
    const v = (counts && counts.video) || 0, a = (counts && counts.audio) || 0;
    const block = $("video-block"); block.hidden = !(v || a);
    for (const el of block.querySelectorAll("[data-media]")) el.hidden = el.dataset.media === "video" ? !v : false;
    $("media-title").textContent = v && a ? "Video & audio clips" : v ? "Video clips" : "Audio clips";
  }
  function refreshMedia() {
    clearTimeout(mediaTimer);
    if (!F.state.sources.length) return applyMedia(null);
    mediaTimer = setTimeout(async () => {
      const seq = ++mediaSeq;
      try { const r = await api("/api/sources/kinds", { method: "POST", body: { paths: F.state.sources, recursive: $("opt-recursive").checked, options: { skip_junk: $("opt-junk").checked } } }); if (seq === mediaSeq) applyMedia(r.counts); }
      catch { if (seq === mediaSeq) applyMedia(null); }
    }, 250);
  }
  F.onSourcesChanged = ((prev) => () => { prev && prev(); refreshMedia(); })(F.onSourcesChanged);
  $("opt-recursive").addEventListener("change", refreshMedia); $("opt-junk").addEventListener("change", refreshMedia);
  F.engineRefresh = refreshCaps;
  restoreOptions(); wire(); setClipMode(state.clipmode); syncLabels(); setPreset(state.preset, true);
  F.addTool({ id: "find", group: "search", icon: "🔎", label: "Find", blurb: "Search any file for words, numbers or objects. Every match comes with a highlighted picture, and videos give you a clip plus a still.", el: $("v-find"), onShow: () => { $("query").focus(); refreshMedia(); } });
})();
