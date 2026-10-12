/* Edit group extras: Find & replace (any file), Stamp, Sign, Print (digital to paper), Photocopy (paper to paper). */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  const post = (p, b) => api(p, { method: "POST", body: b });
  const reg = (t, build) => F.addTool({ ...t, el: F.makeView(t.id), build: (sec) => { const v = F.standardView(t.id, { files: t.files !== false, output: t.output !== false, hint: t.hint }); sec.replaceWith(v.sec); F.tools.find((x) => x.id === t.id).el = v.sec; v.sec.classList.add("on"); build(v.main, v); } });
  function runBar(main, label, tipText, start, panelOpts = {}) {
    const go = h("button", { class: "primary", tip: tipText }, label); const host = h("div");
    const panel = new F.JobPanel(host, { ...panelOpts, onDone: (s, items) => { go.disabled = false; panelOpts.onDone && panelOpts.onDone(s, items); } });
    main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
    go.onclick = async () => { try { go.disabled = true; const r = await start(); if (r) panel.start(r.job); else go.disabled = false; } catch (e) { go.disabled = false; F.toast(e.message); } };
    return { go, panel, host };
  }

  // ================================================================== FIND & REPLACE
  reg({ id: "replace", group: "edit", icon: "🔁", label: "Find & replace", blurb: "Find a word or phrase and replace it in any kind of file: Word, Excel, PowerPoint, PDF, web pages, text, databases, even pictures.", hint: "Add the files or folders to change." }, (main) => {
    main.append(F.titleBlock("Find & replace", "Type what to find and what to put instead. It works inside Word, Excel and PowerPoint files (even when a phrase was split into pieces), OpenDocument, e-books, web pages and XML, text and code in any encoding, PDF, databases, older Office files and pictures. The original is never touched unless you choose to replace it, and then it goes to the Recycle Bin."));
    const pairsBox = h("div", { class: "pairs" });
    const rows = [];
    function addRow(f = "", r = "") {
      const fi = h("input", { type: "text", placeholder: "Find…", value: f, spellcheck: "false", tip: "The word or phrase to look for." });
      const ri = h("input", { type: "text", placeholder: "Replace with…", value: r, spellcheck: "false", tip: "What to put instead. Leave empty to simply delete what was found." });
      const row = h("div", { class: "pair" }, fi, h("span", { class: "arrow", text: "→" }), ri,
        h("button", { class: "btn small", tip: "Removes this pair.", onclick: () => { if (rows.length > 1) { rows.splice(rows.indexOf(rec), 1); row.remove(); } else { fi.value = ""; ri.value = ""; } } }, "✕"));
      const rec = { fi, ri }; rows.push(rec); pairsBox.append(row); return rec;
    }
    addRow();
    const add = h("button", { class: "btn small", tip: "Add another word to find and replace in the same go. They are applied from top to bottom." }, "+ Add another pair");
    add.onclick = () => addRow().fi.focus();
    const form = F.form([
      { id: "case", type: "check", label: "Match upper and lower case", value: false, tip: "On: 'Apple' and 'apple' count as different.\nOff: both are found." },
      { id: "whole", type: "check", label: "Whole words only", value: false, tip: "On: finding 'cat' will not touch 'category'.\nOff: it also changes letters inside other words." },
      { id: "keep_case", type: "check", label: "Keep the capital letters style", value: false, tip: "On: if the found word was ALL CAPS or Capitalised, the new word is written the same way." },
      { id: "regex", type: "check", label: "Use patterns (advanced)", value: false, tip: "On: the 'find' box is a regular expression, for example \\d{4}-\\d{2} finds dates, and you can use \\1 in the replacement. For people who know patterns.\nOff: it finds exactly what you type." },
      { id: "raw_markup", type: "check", label: "Also change inside web page tags", value: false, tip: "On: for HTML and XML files, the tags and addresses are searched too (a link address, a CSS name).\nOff: only the words people read are changed, so the page cannot break." },
      { id: "legacy", type: "check", label: "Include old Office files (doc, xls, ppt, rtf)", value: true, tip: "On: older files are converted, changed and converted back (needs LibreOffice, which Fathom can install). Formatting can shift slightly.\nOff: they are skipped." },
      { id: "binary", type: "check", label: "Try other files byte for byte", value: false, tip: "On: for programs and other unknown files, the text hidden inside is replaced, but only if the new text is not longer than the old (it is padded). Case must match exactly.\nOff: files Fathom does not understand are skipped." },
      { id: "pages", type: "pages", label: "Only on these PDF pages", value: "", tip: "For PDFs: only these pages are searched and changed. Empty = every page." },
      { id: "inplace", type: "check", label: "Replace the original files (they go to the Recycle Bin)", value: false, tip: "On: the changed file takes the original's place and the old one is put in the Recycle Bin, so you can still get it back.\nOff: a new file ending in _edited is saved and the original stays as it was." }]);
    main.append(h("div", { class: "card-box" }, pairsBox, h("div", { class: "row", style: "margin-top:8px" }, add), h("div", { style: "margin-top:12px" }, form.el)));
    const collect = () => {
      const pairs = rows.map((r) => ({ find: r.fi.value, replace: r.ri.value })).filter((p) => p.find !== "");
      if (!pairs.length) { F.toast("Type something to find first."); return null; }
      if (!F.needFiles()) return null;
      return { pairs, ...form.values() };
    };
    const sample = (s) => h("div", { class: "snip" }, h("span", { class: "mono", text: "…" + s.before }), h("mark", { text: s.match }), h("span", { class: "mono", text: s.after + "…" }), h("span", { class: "arrow", text: " → " }), h("b", { text: s.to === "" ? "(deleted)" : s.to }));
    const previewItem = (r) => {
      const c = (r.extra && r.extra.count) || 0;
      return h("div", { class: "job " + (r.status === "error" ? "error" : c ? "done" : "skipped") }, h("div", { class: "ico", text: r.status === "error" ? "⚠️" : c ? "🔎" : "➖" }),
        h("div", { class: "t" }, h("b", { text: r.name }), h("small", { text: r.status === "error" ? r.error : r.note }), ...(((r.extra && r.extra.samples) || []).map(sample)), (r.extra && r.extra.proof && r.extra.proof.length) ? F.proofGallery(r.extra.proof, { first: 2 }) : null));
    };
    const pv = runBar(main, "Preview matches", "Shows how many places would change in each file and a few examples. Nothing is changed.", async () => { const v = collect(); if (!v) return null; return post("/api/tools/replace", { paths: F.state.sources, recursive: true, options: { ...v, dry: true }, output: F.outputBody() }); },
      { noun: "file", renderItem: previewItem });
    pv.go.className = "btn";
    const hostGo = h("div"); const panel = new F.JobPanel(hostGo, { noun: "file", onDone: () => { go.disabled = false; F.refreshUndo && F.refreshUndo(); } });
    const go = h("button", { class: "primary", tip: "Makes the changes in a copy of each file (or in the file itself if you ticked the Recycle Bin option)." }, "Replace now");
    pv.go.parentElement.append(go); main.append(hostGo);
    go.onclick = async () => {
      const v = collect(); if (!v) return;
      if (v.inplace && !confirm("Replace the original files? The old versions go to the Recycle Bin.")) return;
      try { go.disabled = true; const r = await post("/api/tools/replace", { paths: F.state.sources, recursive: true, options: v, output: F.outputBody() }); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); }
    };
  });

  // ================================================================== STAMP & SIGN (shared builder)
  const POS = [["tl", "↖"], ["tc", "↑"], ["tr", "↗"], ["ml", "←"], ["c", "●"], ["mr", "→"], ["bl", "↙"], ["bc", "↓"], ["br", "↘"]];
  const POS_NAMES = { tl: "top left", tc: "top middle", tr: "top right", ml: "middle left", c: "the centre", mr: "middle right", bl: "bottom left", bc: "bottom middle", br: "bottom right" };

  function fileToDataUrl(file) { return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); }); }
  const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  function stampTool(mode) {
    const sign = mode === "sign";
    reg({ id: sign ? "sign" : "stamp", group: "edit", icon: sign ? "✍️" : "🔖", label: sign ? "Sign" : "Stamp",
      blurb: sign ? "Put your signature on PDFs and pictures: draw it, type it, or clean up a photo of your real signature, then place it where you want." : "Put a stamp, watermark or page numbers on PDFs and pictures: ready-made words like APPROVED, your own words, or your own picture such as a company seal.",
      hint: "Add the PDFs, pictures or documents to " + (sign ? "sign." : "stamp.") }, (main) => {
      main.append(F.titleBlock(sign ? "Sign" : "Stamp & watermark", sign
        ? "Make your signature once, keep it in your library, and put it on any PDF or picture. This is the picture of your signature on the page, like signing a printout. Word, Excel and PowerPoint files are turned into a PDF first. The original is never changed."
        : "Put a stamp on every page, or a faint watermark across the whole page, or page numbers like 'Page 3 of 10'. Word, Excel and PowerPoint files are turned into a PDF first. The original is never changed."));
      const sel = { item: null, render: null, preview: "" };           // what is chosen
      const lib = h("div", { class: "libgrid" });
      const prevImg = h("img", { class: "mk-prev", alt: "" });
      const setPreview = (src) => { sel.preview = src; prevImg.src = src || ""; prevImg.hidden = !src; updateOverlay(); };

      // ---- the library of saved pictures
      const libCard = h("div", { class: "card-box" }, h("h3", { text: sign ? "My signatures" : "My stamps" }), lib);
      async function loadLib() {
        try {
          const r = await api("/api/stamp/items"); presets = r.presets;
          const mine = r.items.filter((x) => x.kind === (sign ? "signature" : "stamp"));
          lib.replaceChildren(...(mine.length ? mine.map((it) => h("div", { class: "tile" + (sel.item === it.id ? " on" : ""), tip: "Click to use this " + (sign ? "signature" : "stamp") + "." },
            h("img", { src: it.thumb, alt: it.name, onclick: () => { sel.item = it.id; sel.render = null; setPreview(it.thumb); loadLib(); } }), h("span", { text: it.name }),
            h("button", { class: "x", tip: "Deletes it from your library.", onclick: async (e) => { e.stopPropagation(); if (!confirm(`Delete "${it.name}" from your library?`)) return; await post("/api/stamp/delete", { id: it.id }); if (sel.item === it.id) { sel.item = null; setPreview(""); } loadLib(); } }, "✕")))
            : [h("p", { class: "hint", text: sign ? "No signatures yet. Make one below." : "No saved stamps yet. Pick a ready-made one or make your own below, then press 'Save to my stamps'." })]));
        } catch (e) { lib.replaceChildren(h("p", { class: "hint", text: e.message })); }
      }
      let presets = [];

      // ---- making new ones
      const maker = h("div", { class: "card-box" }, h("h3", { text: sign ? "Make a signature" : "Make a stamp" }));
      const saveName = h("input", { type: "text", placeholder: "Name (optional)", style: "max-width:220px", tip: "A name to find it again in your library." });
      const saveBtn = h("button", { class: "btn", tip: "Keeps this in your library so you can use it again any time." }, sign ? "Save to my signatures" : "Save to my stamps");
      let currentSpec = null;
      async function render(spec) {
        currentSpec = spec;
        try { const r = await post("/api/stamp/render", { spec }); if (currentSpec === spec) { sel.item = null; sel.render = spec.render || null; sel.data = spec.data ? spec : null; setPreview(r.png); } }
        catch (e) { F.toast(e.message); }
      }
      const rerender = debounce((spec) => render(spec), 300);
      saveBtn.onclick = async () => {
        if (!currentSpec) return F.toast("Make one first.");
        try { const r = await post("/api/stamp/save", { spec: currentSpec, name: saveName.value, kind: sign ? "signature" : "stamp" }); sel.item = r.id; sel.render = null; F.toast("Saved."); await loadLib(); } catch (e) { F.toast(e.message); }
      };
      const importBox = (cleanDefault) => {
        const file = h("input", { type: "file", accept: "image/*", tip: "Choose a picture file." });
        const f = F.form([{ id: "clean", type: "check", label: sign ? "Remove the paper (keep only the ink)" : "Remove the background", value: cleanDefault, tip: "On: the white paper or background becomes see-through so only the ink or drawing shows. Best for a photo or scan of a signature.\nOff: the picture is used exactly as it is." },
          { id: "ink", type: "select", label: "Ink colour", value: "keep", options: [{ v: "keep", l: "As in the picture" }, { v: "black", l: "Black" }, { v: "blue", l: "Pen blue" }], tip: "Changes the colour of the ink when the paper is removed." },
          { id: "strength", type: "range", label: "How much to remove", min: 5, max: 95, value: 50, fmt: (v) => v + "%", tip: "Low: keeps faint pen lines but may leave grey paper marks.\nHigh: cleaner background but thin lines can fade." }], () => go());
        let data = "";
        const go = debounce(() => { if (!data) return; const v = f.values(); render({ data, remove_bg: v.clean, ink: v.ink, strength: v.strength }); }, 250);
        file.onchange = async () => { if (file.files[0]) { data = await fileToDataUrl(file.files[0]); go(); } };
        return h("div", {}, h("div", { class: "field" }, h("div", { class: "lab", text: sign ? "A photo or scan of your signature (or any picture)" : "A picture (your logo or seal)" }), file), f.el);
      };
      if (sign) {
        // type
        const tName = h("input", { type: "text", placeholder: "Type your name", tip: "Your name, written in a handwriting style." });
        const tf = F.form([{ id: "font", type: "choice", label: "Style", value: "script", options: [{ v: "script", l: "Handwriting", tip: "A flowing handwriting style." }, { v: "formal", l: "Formal", tip: "An elegant, classic writing style." }, { v: "casual", l: "Casual", tip: "A quick, informal pen style." }, { v: "brush", l: "Brush", tip: "A bold brush-pen style." }] },
          { id: "color", type: "select", label: "Ink colour", value: "#1b3a8c", options: [{ v: "#1b3a8c", l: "Pen blue" }, { v: "#111111", l: "Black" }, { v: "#4a1d8a", l: "Purple" }, { v: "#0b6b3a", l: "Green" }], tip: "The colour of the writing." }], () => typed());
        const typed = () => { if (tName.value.trim()) { const v = tf.values(); rerender({ render: { text: tName.value, font: v.font, style: "plain", color: v.color, bold: false, size: 220 } }); } };
        tName.addEventListener("input", typed);
        // draw
        const cv = h("canvas", { class: "sigpad", width: 900, height: 300, tip: "Draw your signature here with the mouse, a pen or your finger." });
        const ctx = cv.getContext("2d"); let drawing = false, last = null, strokes = [];
        const pt = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height, e.pressure && e.pressure > 0 ? e.pressure : 0.5]; };
        const redraw = () => { ctx.clearRect(0, 0, cv.width, cv.height); ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = inkSel.value; for (const s of strokes) { for (let i = 1; i < s.length; i++) { ctx.lineWidth = 3 + s[i][2] * 4; ctx.beginPath(); ctx.moveTo(s[i - 1][0], s[i - 1][1]); ctx.lineTo(s[i][0], s[i][1]); ctx.stroke(); } if (s.length === 1) { ctx.beginPath(); ctx.arc(s[0][0], s[0][1], 3, 0, 7); ctx.fillStyle = inkSel.value; ctx.fill(); } } };
        const inkSel = h("select", { tip: "The colour of the pen." }, [["#1b3a8c", "Pen blue"], ["#111111", "Black"], ["#4a1d8a", "Purple"]].map(([v, l]) => h("option", { value: v, text: l })));
        const push = debounce(() => { if (!strokes.length) return; render({ data: cv.toDataURL("image/png") }); }, 200);
        cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture(e.pointerId); drawing = true; strokes.push([pt(e)]); redraw(); });
        cv.addEventListener("pointermove", (e) => { if (!drawing) return; strokes[strokes.length - 1].push(pt(e)); redraw(); });
        const end = () => { if (drawing) { drawing = false; push(); } };
        cv.addEventListener("pointerup", end); cv.addEventListener("pointercancel", end);
        inkSel.onchange = () => { redraw(); push(); };
        const draw = h("div", {}, cv, h("div", { class: "row", style: "margin-top:8px" }, h("button", { class: "btn small", tip: "Removes the last stroke.", onclick: () => { strokes.pop(); redraw(); strokes.length ? push() : null; } }, "Undo stroke"), h("button", { class: "btn small", tip: "Wipes the pad clean.", onclick: () => { strokes = []; redraw(); } }, "Clear"), inkSel));
        const tabs = h("div", { class: "tabs2" }); const body = h("div", { style: "margin-top:12px" });
        const panes = { draw: draw, type: h("div", {}, h("div", { class: "field" }, tName), tf.el), photo: importBox(true) };
        const names = { draw: "✏️ Draw it", type: "⌨️ Type it", photo: "📷 From a photo or scan" };
        const show = (k) => { [...tabs.children].forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === k))); body.replaceChildren(panes[k]); };
        for (const k of Object.keys(panes)) tabs.append(h("button", { class: "choice", "data-k": k, tip: { draw: "Draw it with the mouse, a pen or your finger.", type: "Type your name and choose a handwriting style.", photo: "Take a photo or scan of your real signature on white paper. Fathom removes the paper." }[k], onclick: () => show(k) }, h("b", { text: names[k] })));
        maker.append(tabs, body); show("draw");
      } else {
        // ready-made presets
        const chips = h("div", { class: "chips" });
        const tText = h("textarea", { rows: 2, placeholder: "Your words (a new line starts a second line)", tip: "The words on the stamp. You can use {date}, {time}, {page}, {pages} and {file}, which are filled in for you." });
        tText.value = "APPROVED\n{date}";
        const tf = F.form([{ id: "style", type: "select", label: "Look", value: "box", options: [{ v: "box", l: "Box" }, { v: "double", l: "Double box" }, { v: "round", l: "Rounded" }, { v: "banner", l: "Solid banner" }, { v: "underline", l: "Underlined" }, { v: "plain", l: "Just the words" }], tip: "The frame around the words." },
          { id: "font", type: "select", label: "Letters", value: "sans", options: [{ v: "sans", l: "Plain" }, { v: "serif", l: "Classic" }, { v: "mono", l: "Typewriter" }, { v: "script", l: "Handwriting" }], tip: "The style of the letters." },
          { id: "color", type: "select", label: "Colour", value: "#1e8449", options: [{ v: "#1e8449", l: "Green" }, { v: "#b03a2e", l: "Red" }, { v: "#1f4e9c", l: "Blue" }, { v: "#d35400", l: "Orange" }, { v: "#444444", l: "Dark grey" }, { v: "#7f8c8d", l: "Grey" }, { v: "#111111", l: "Black" }], tip: "The colour of the ink." },
          { id: "worn", type: "check", label: "Worn, inked look", value: false, tip: "On: tiny gaps like a real rubber stamp.\nOff: perfectly clean." }], () => typed());
        const typed = () => { const v = tf.values(); rerender({ render: { text: tText.value || "STAMP", style: v.style, font: v.font, color: v.color, worn: v.worn, size: 160 } }); };
        tText.addEventListener("input", typed);
        const fill = (p) => { tText.value = p.text; tf.set("color", p.color); typed(); };
        api("/api/stamp/items").then((r) => { for (const p of r.presets) chips.append(h("button", { tip: "Uses the ready-made stamp '" + p.text.replace("\n", " ") + "'.", onclick: () => fill(p) }, p.text.split("\n")[0])); chips.append(h("button", { tip: "Page numbers like 'Page 3 of 10' on every page.", onclick: () => { tText.value = "Page {page} of {pages}"; tf.set("style", "plain"); tf.set("color", "#444444"); tf.set("font", "sans"); typed(); setPlace({ position: "bc", size: 16 }); } }, "Page numbers"), h("button", { tip: "A faint diagonal word repeated over the whole page.", onclick: () => { tText.value = "CONFIDENTIAL"; tf.set("style", "plain"); tf.set("color", "#7f8c8d"); typed(); setPlace({ tile: true, opacity: 25, rotation: 35, size: 22 }); } }, "Watermark")); }).catch(() => {});
        const tabs = h("div", { class: "tabs2" }); const body = h("div", { style: "margin-top:12px" });
        const panes = { text: h("div", {}, chips, h("div", { class: "field", style: "margin-top:10px" }, tText), tf.el), pic: importBox(false) };
        const names = { text: "🔤 Words", pic: "🖼 My own picture" };
        const show = (k) => { [...tabs.children].forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === k))); body.replaceChildren(panes[k]); if (k === "text") typed(); };
        for (const k of Object.keys(panes)) tabs.append(h("button", { class: "choice", "data-k": k, tip: { text: "Ready-made or your own words, in a frame.", pic: "Use your own logo, seal or any picture. A transparent PNG works best." }[k], onclick: () => show(k) }, h("b", { text: names[k] })));
        maker.append(tabs, body); show("text");
      }
      maker.append(h("div", { class: "row", style: "margin-top:12px" }, saveName, saveBtn));
      main.append(libCard, maker);

      // ---- where and how
      const place = { position: sign ? "br" : "c", tile: false };
      const pp = F.previewPicker({ label: "Preview on", size: 1100, onChange: () => { updateOverlay(); } });   // a real page of one of your files (or a blank page)
      const pagesSpec = { id: "pagesel", type: "pages", label: "On which pages", value: sign ? "last" : "", source: pp, tip: "Which pages of a PDF get it. Pictures always get it.\nType numbers (1,3,5), ranges (5-8), 'end', 'odd', 'even', 'every 3', or '!2' for 'not page 2'. Empty means every page. Or click the pages." };
      const pf = F.form([
        { id: "size", type: "range", label: "Size", min: 3, max: 100, value: sign ? 28 : 38, fmt: (v) => v + "% of the page width", tip: "Low: small.\nHigh: big. 100 covers the whole width." },
        { id: "opacity", type: "range", label: "Opacity", min: 5, max: 100, value: sign ? 100 : 85, fmt: (v) => v + "%", tip: "Low: faint and see-through, good for watermarks.\nHigh: solid and clear." },
        { id: "rotation", type: "range", label: "Turn", min: -180, max: 180, value: sign ? 0 : -12, fmt: (v) => v + "°", tip: "Tilts it. Negative tilts it left, positive right. 0 keeps it straight." },
        { id: "dx", type: "range", label: "Nudge sideways", min: -50, max: 50, value: 0, fmt: (v) => v + "%", tip: "Moves it left (negative) or right (positive) from the chosen place." },
        { id: "dy", type: "range", label: "Nudge up/down", min: -50, max: 50, value: 0, fmt: (v) => v + "%", tip: "Moves it up (negative) or down (positive) from the chosen place." },
        { id: "cx", type: "number", label: "Exact: centre across", unit: "% from the left", min: 0, max: 100, step: "any", placeholder: "from the arrows", tip: "The exact place of its centre, as a percent of the page width. Dragging fills this in. Empty = use the arrows." },
        { id: "cy", type: "number", label: "Exact: centre down", unit: "% from the top", min: 0, max: 100, step: "any", placeholder: "from the arrows", tip: "The exact place of its centre, as a percent of the page height. Dragging fills this in. Empty = use the arrows." },
        { id: "tile", type: "check", label: "Repeat it over the whole page (watermark)", value: false, tip: "On: copies of it cover the page in a diagonal pattern.\nOff: it is placed once, where you put it." },
        pagesSpec,
        ...(sign ? [{ id: "name", type: "text", label: "Signed by (line under it)", placeholder: "e.g. John Smith", tip: "Optional small text under the signature. Leave empty for none." }, { id: "with_date", type: "check", label: "Add today's date under it", value: false, tip: "On: the date is printed under the signature." }] : [])], () => updateOverlay());
      const isFree = () => { const v = pf.values(); return v.cx !== "" && v.cy !== "" && v.cx != null && v.cy != null; };
      const grid = h("div", { class: "posgrid" }, POS.map(([k, ch]) => h("button", { type: "button", "data-p": k, tip: "Puts it at " + POS_NAMES[k] + ".", onclick: () => { place.position = k; pf.set("cx", ""); pf.set("cy", ""); pf.set("dx", 0); pf.set("dy", 0); paintGrid(); updateOverlay(); } }, ch)));
      const paintGrid = () => grid.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(!isFree() && b.dataset.p === place.position)));
      function setPlace(p) { Object.assign(place, p); for (const k of ["size", "opacity", "rotation", "tile"]) if (p[k] !== undefined) pf.set(k, p[k]); if (p.position) { pf.set("cx", ""); pf.set("cy", ""); } paintGrid(); updateOverlay(); }
      paintGrid();

      // the stamp lies on the page preview and can be dragged (corner handle = size, top handle = turn)
      const hSize = h("span", { class: "hnd hsize", tip: "Drag to make it bigger or smaller." }); const hRot = h("span", { class: "hnd hrot", tip: "Drag to turn it." });
      const gV = h("div", { class: "guide gv" }), gH = h("div", { class: "guide gh" });
      const pvOver = h("div", { class: "pvover", tabindex: "0", tip: "Drag it where you want it. Arrow keys move it a little (hold Shift for more). The round handles change its size and turn." }, prevImg, hSize, hRot);
      const badge = h("div", { class: "pvbadge" });
      pp.layer.append(gV, gH, pvOver, badge);
      const readout = h("p", { class: "hint pv-read" });
      function updateOverlay() {
        const v = pf.values(); const stage = pp.stage; const W = stage.clientWidth, H = stage.clientHeight; if (!W || !H) return;
        const w = Math.max(8, W * v.size / 100); const aspect = (prevImg.naturalHeight || 1) / (prevImg.naturalWidth || 1); const hh = w * aspect;
        prevImg.style.width = w + "px"; prevImg.style.opacity = String(v.opacity / 100); prevImg.style.transform = `rotate(${v.rotation}deg)`;
        const pk = pagesSpec.picker, pg = pp.state.path ? pp.state.page : 0;
        badge.hidden = !(pk && pp.state.path && pp.state.pages > 1 && !pk.includes(pg)); badge.textContent = `Page ${pg + 1} is not one of the pages you chose, so nothing would be put on it.`;
        if (v.tile) { pvOver.style.cssText = "inset:0;left:0;top:0;width:auto;height:auto;pointer-events:none"; pvOver.classList.add("tiled"); pvOver.style.backgroundImage = sel.preview ? `url(${sel.preview})` : ""; prevImg.style.display = "none"; pvOver.style.backgroundSize = w + "px"; pvOver.style.opacity = String(v.opacity / 100); hSize.hidden = hRot.hidden = true; paintGrid(); return; }
        pvOver.classList.remove("tiled"); pvOver.style.cssText = ""; pvOver.style.backgroundImage = ""; prevImg.style.display = ""; hSize.hidden = hRot.hidden = false;
        let cx, cy;
        if (isFree()) { cx = v.cx / 100 * W; cy = v.cy / 100 * H; }
        else { const A = { tl: [0, 0], tc: [.5, 0], tr: [1, 0], ml: [0, .5], c: [.5, .5], mr: [1, .5], bl: [0, 1], bc: [.5, 1], br: [1, 1] }[place.position]; const m = 0.04 * Math.min(W, H); cx = m + w / 2 + A[0] * (W - 2 * m - w) + v.dx / 100 * W; cy = m + hh / 2 + A[1] * (H - 2 * m - hh) + v.dy / 100 * H; }
        pvOver.style.left = (cx - w / 2) + "px"; pvOver.style.top = (cy - hh / 2) + "px"; pvOver.style.width = w + "px"; pvOver.style.height = hh + "px";
        readout.textContent = `Centre: ${(cx / W * 100).toFixed(1)}% across, ${(cy / H * 100).toFixed(1)}% down  ·  width ${v.size}% of the page  ·  turned ${v.rotation}°`;
        paintGrid();
      }
      let drag = null;
      pvOver.addEventListener("pointerdown", (e) => {
        if (pvOver.classList.contains("tiled")) return;
        const r = pp.stage.getBoundingClientRect(); const o = pvOver.getBoundingClientRect(); const cxp = o.left + o.width / 2, cyp = o.top + o.height / 2;
        const kind = e.target === hSize ? "size" : e.target === hRot ? "rot" : "move";
        drag = { kind, dx: e.clientX - cxp, dy: e.clientY - cyp, r, cx: cxp, cy: cyp };
        pvOver.setPointerCapture(e.pointerId); e.preventDefault(); pvOver.focus();
        if (kind === "move" && !isFree()) { pf.set("cx", +((cxp - r.left) / r.width * 100).toFixed(1)); pf.set("cy", +((cyp - r.top) / r.height * 100).toFixed(1)); }
      });
      pvOver.addEventListener("pointermove", (e) => {
        if (!drag) return; const { r } = drag;
        if (drag.kind === "move") {
          let x = (e.clientX - drag.dx - r.left) / r.width * 100, y = (e.clientY - drag.dy - r.top) / r.height * 100;
          x = Math.max(0, Math.min(100, x)); y = Math.max(0, Math.min(100, y));
          const sx = Math.abs(x - 50) < 1.5, sy = Math.abs(y - 50) < 1.5; if (sx) x = 50; if (sy) y = 50; gV.classList.toggle("on", sx); gH.classList.toggle("on", sy);
          pf.set("cx", +x.toFixed(1)); pf.set("cy", +y.toFixed(1));
        } else if (drag.kind === "size") {
          const halfW = Math.abs(e.clientX - drag.cx) * 2; pf.set("size", Math.max(3, Math.min(100, Math.round(halfW / r.width * 100))));
        } else {
          const ang = Math.atan2(e.clientY - drag.cy, e.clientX - drag.cx) * 180 / Math.PI + 90; let d = Math.round(ang > 180 ? ang - 360 : ang); if (Math.abs(d) < 4) d = 0; pf.set("rotation", Math.max(-180, Math.min(180, d)));
        }
        updateOverlay();
      });
      const endDrag = () => { drag = null; gV.classList.remove("on"); gH.classList.remove("on"); };
      pvOver.addEventListener("pointerup", endDrag); pvOver.addEventListener("pointercancel", endDrag);
      pvOver.addEventListener("keydown", (e) => {
        const k = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key]; if (!k) return; e.preventDefault();
        const step = e.shiftKey ? 5 : 0.5; const r = pp.stage; const o = pvOver.getBoundingClientRect(), pr = r.getBoundingClientRect();
        const cx = isFree() ? pf.values().cx : (o.left + o.width / 2 - pr.left) / pr.width * 100, cy = isFree() ? pf.values().cy : (o.top + o.height / 2 - pr.top) / pr.height * 100;
        pf.set("cx", +Math.max(0, Math.min(100, cx + k[0] * step)).toFixed(1)); pf.set("cy", +Math.max(0, Math.min(100, cy + k[1] * step)).toFixed(1)); updateOverlay();
      });
      prevImg.addEventListener("load", updateOverlay); window.addEventListener("resize", updateOverlay);
      main.append(h("div", { class: "card-box" }, h("h3", { text: "Where it goes" }), pp.el, h("div", { class: "pvbox" }, pp.stage), readout,
        h("p", { class: "hint", text: "Drag it on the page to put it exactly where you want. The page shown is a real page of your file, so what you see is what you get." }),
        h("div", { class: "placerow" }, h("div", {}, h("div", { class: "lab", text: "Or pick a spot" }), grid), pf.el)));
      loadLib();
      const onShowPrev = F.tools.find((x) => x.id === (sign ? "sign" : "stamp")); onShowPrev.onShow = () => { loadLib(); pp.reload(); setTimeout(updateOverlay, 80); };

      runBar(main, sign ? "Sign the files" : "Stamp the files", "Puts it on a copy of each file. Your originals are not changed.", async () => {
        if (!F.needFiles()) return null;
        if (!sel.item && !sel.render && !sel.data) { F.toast(sign ? "Make or choose a signature first." : "Make or choose a stamp first."); return null; }
        const v = pf.values();
        const spec = { position: place.position, size: v.size, opacity: v.opacity, rotation: v.rotation, dx: v.dx, dy: v.dy, tile: v.tile, pages: v.pagesel ? "custom" : "all", pages_spec: v.pagesel || "", margin: 4, as: mode };
        if (isFree() && !v.tile) { spec.free = true; spec.x = v.cx / 100; spec.y = v.cy / 100; spec.dx = 0; spec.dy = 0; }
        if (sel.item) spec.item = sel.item; else if (sel.data) spec.make = sel.data; else spec.render = sel.render;
        if (sign) { spec.name = v.name || ""; const cap = [v.name, v.with_date ? "{date}" : ""].filter(Boolean).join("  ·  "); if (cap) spec.caption = cap; }
        return post("/api/tools/stamp", { paths: F.state.sources, recursive: true, spec, output: F.outputBody() });
      }, { noun: "file" });
    });
  }
  stampTool("stamp");
  stampTool("sign");

  // ================================================================== PRINT (digital -> paper)
  async function printerPicker(host) {
    const sel = h("select", { tip: "The printer to use." }); const note = h("p", { class: "hint" });
    const load = async () => {
      try {
        const r = await api("/api/print/printers");
        sel.replaceChildren(...r.printers.map((p) => h("option", { value: p.name, text: p.name + (p.default ? "  (default)" : "") + (p.offline ? "  (offline)" : "") })));
        const d = r.printers.find((p) => p.default); if (d) sel.value = d.name;
        note.textContent = r.printers.length ? "" : (r.notes[0] || "No printers found. Add one in your system settings first.");
      } catch (e) { note.textContent = e.message; }
    };
    const btn = h("button", { class: "btn small", tip: "Looks for printers again.", onclick: load }, "Refresh");
    host.append(h("div", { class: "field" }, h("div", { class: "lab", text: "Printer" }), h("div", { class: "inline", style: "display:flex;gap:8px" }, sel, btn)), note);
    await load();
    return { get value() { return sel.value; } };
  }
  const printOptions = (extra = []) => F.form([
    { id: "copies", type: "number", label: "Copies", value: 1, min: 1, max: 999, tip: "How many copies of each file." },
    { id: "color", type: "select", label: "Colour", value: "1", options: [{ v: "1", l: "Colour" }, { v: "0", l: "Black and white" }], tip: "Black and white saves colour ink." },
    { id: "duplex", type: "select", label: "Both sides", value: "", options: [{ v: "", l: "One side" }, { v: "long", l: "Both sides (flip on the long edge)" }, { v: "short", l: "Both sides (flip on the short edge)" }], tip: "Prints on the front and back of the paper if the printer can." },
    { id: "paper", type: "select", label: "Paper", value: "", options: [{ v: "", l: "Printer's choice" }, { v: "A4", l: "A4" }, { v: "Letter", l: "Letter" }, { v: "Legal", l: "Legal" }, { v: "A3", l: "A3" }, { v: "A5", l: "A5" }], tip: "The size of paper (macOS and Linux; Windows uses the printer's setting)." },
    { id: "orientation", type: "select", label: "Direction", value: "auto", options: [{ v: "auto", l: "Automatic" }, { v: "portrait", l: "Upright" }, { v: "landscape", l: "Sideways" }], tip: "Which way the page is turned." },
    { id: "fit", type: "select", label: "Size on the paper", value: "fit", options: [{ v: "fit", l: "Fit to the page" }, { v: "fill", l: "Fill the page (may crop)" }, { v: "actual", l: "Actual size" }], tip: "Fit: the whole picture is shown. Fill: no empty margins, edges may be cut. Actual size: as big as it really is." },
    { id: "pages", type: "pages", label: "Only these pages", value: "", tip: "Empty = every page. Type pages like 1-3,5, 'odd', 'last', or click the pages. Works for PDFs (and documents on macOS and Linux)." }, ...extra]);
  reg({ id: "print", group: "edit", icon: "🖨️", label: "Print", blurb: "Digital to paper: send PDFs, pictures and documents to a printer, many files at once, with copies, both sides and colour choices.", output: false, hint: "Add the files to print." }, async (main) => {
    main.append(F.titleBlock("Print", "Sends your files to a real printer. Documents like Word and Excel are printed through the program Windows uses for them, or turned into a PDF first on Mac and Linux. Nothing about the files changes."));
    const pbox = h("div", { class: "card-box" }); main.append(pbox);
    const pp = await printerPicker(pbox); const form = printOptions(); pbox.append(form.el);
    runBar(main, "Print", "Sends every file on the left to the printer.", async () => { if (!F.needFiles()) return null; const v = form.values(); return post("/api/tools/print", { paths: F.state.sources, recursive: true, options: { printer: pp.value, copies: +v.copies || 1, color: v.color === "1", duplex: v.duplex, paper: v.paper, orientation: v.orientation, fit: v.fit, pages: v.pages } }); }, { noun: "file" });
  });

  // ================================================================== PHOTOCOPY (paper -> paper)
  reg({ id: "copy", group: "edit", icon: "📠", label: "Photocopy", blurb: "Paper to paper: scan a page on your scanner and print it straight away, like a copy machine.", files: false, output: false }, async (main) => {
    main.append(F.titleBlock("Photocopy", "Put a page on your scanner, press the button, and Fathom scans it and prints copies. Use 'Keep a scan' if you also want the scanned file saved."));
    const card = h("div", { class: "card-box" }); main.append(card);
    const scSel = h("select", { tip: "The scanner to use." }); const scNote = h("p", { class: "hint" });
    const hostBox = h("input", { type: "text", placeholder: "Optional SANE server, e.g. 192.168.1.20", value: F.load("scanhost", ""), tip: "Only for scanners on another computer running the SANE service." });
    const load = async () => { scNote.textContent = "Looking for scanners…"; try { const hh = hostBox.value.trim(); const r = await api("/api/lab/scanner/list" + (hh ? "?host=" + encodeURIComponent(hh) : "")); scSel.replaceChildren(...(r.scanners || []).map((s) => h("option", { value: s.id, text: s.name + "  ·  " + s.kind }))); scNote.textContent = !r.available ? r.why : (r.scanners || []).length ? "" : "No scanner found. Make sure it is on and connected."; } catch (e) { scNote.textContent = e.message; } };
    card.append(h("div", { class: "field" }, h("div", { class: "lab", text: "Scanner" }), h("div", { style: "display:flex;gap:8px" }, scSel, h("button", { class: "btn small", tip: "Looks for scanners again.", onclick: load }, "Refresh"))), scNote, h("div", { class: "field" }, h("div", { class: "lab", text: "SANE server (optional)" }), hostBox));
    const pp = await printerPicker(card);
    const form = printOptions([{ id: "dpi", type: "select", label: "Scan quality", value: "300", options: [{ v: "150", l: "150 DPI — draft" }, { v: "300", l: "300 DPI — normal" }, { v: "600", l: "600 DPI — fine" }], tip: "Higher is sharper but slower." },
      { id: "feeder", type: "check", label: "Copy every sheet in the feeder (TWAIN scanners)", value: false, tip: "Keeps scanning while the automatic feeder has paper." },
      { id: "keep", type: "text", label: "Keep a scan in this folder (optional)", placeholder: "Leave empty to keep nothing", tip: "If you type a folder, the scanned PDF is saved there as well as printed." }]);
    card.append(form.el); load();
    runBar(main, "Copy", "Scans the page and prints it.", async () => { if (!scSel.value) { F.toast("Choose a scanner first."); return null; } const v = form.values(); try { F.save("scanhost", hostBox.value.trim()); } catch {}
      return post("/api/tools/copy", { options: { scanner: scSel.value, printer: pp.value, copies: +v.copies || 1, dpi: +v.dpi, mode: v.color === "1" ? "color" : "gray", host: hostBox.value.trim(), color: v.color === "1", duplex: v.duplex, paper: v.paper, orientation: v.orientation, fit: v.fit, feeder: v.feeder, keep_dir: v.keep } }); }, { noun: "copy" });
  });
})();
