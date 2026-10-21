/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* Visual editor: every shape, line, arrow, picture and piece of text on a PDF page can be picked, dragged, resized, recoloured, copied or deleted,
   and new ones added. The page picture always comes from the real file with the edits applied (the engine is app/pdfobjects.py). */
(() => {
  const F = window.Fathom, h = F.h, api = F.api;
  const post = (path, body) => api(path, { method: "POST", body });
  try {
    F.addTool({ id: "visual", group: "edit", icon: "🖱️", label: "Visual editor", blurb: "Drag, resize, recolour, copy and delete every object in a PDF, PowerPoint slide or SVG drawing, and add layers to pictures. No subscription, nothing locked.", el: F.makeView("visual"),
      build: (sec) => {
        const view = F.standardView("visual", { output: true }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "visual").el = view.sec; view.sec.classList.add("on");
        const main = view.main;
        main.append(F.titleBlock("Visual editor", "Add a PDF, PowerPoint (.pptx), SVG or picture on the left and press “Open”. Click an object to select it (Shift adds more, or drag a box around several). Hold Alt while clicking a box to pick it together with everything inside it. Drag to move, pull the corner dot to resize, and use the panel to change colours and text. Double-click text to retype it. Your original file is never changed; Save makes a copy."));
        const S = { u: 1, type: "", path: "", total: 0, page: 1, info: null, pages: {}, sel: new Set(), hist: [], fut: [], tool: "select", k: 1.4, seq: 0 };
        const pg = () => (S.pages[S.page] ||= { mods: {}, adds: [] });
        const snap = () => { S.hist.push(JSON.stringify(S.pages)); if (S.hist.length > 80) S.hist.shift(); S.fut = []; };
        const open = h("button", { class: "primary", tip: "Loads the first PDF on the left and shows its page for editing." }, "Open");
        const tools = [["select", "↖ Select", "Click to select, drag to move."], ["text", "T Text", "Click the page to add text."], ["rect", "▭ Box", "Drag on the page to draw a box."], ["round", "▢ Rounded box", "Drag to draw a box with rounded corners."], ["ellipse", "◯ Oval", "Drag to draw an oval."], ["line", "╱ Line", "Drag to draw a straight line."], ["arrow", "➜ Arrow", "Drag to draw an arrow."]];
        const toolBtns = tools.map(([id, l, tip]) => h("button", { class: "btn small", "data-tool": id, tip, onclick: () => setTool(id) }, l));
        const bPic = h("button", { class: "btn small", tip: "Adds a picture from your computer as a layer you can move and resize." }, "🖼 Picture");
        const picIn = h("input", { type: "file", accept: "image/*", hidden: true });
        const bDup = h("button", { class: "btn small", tip: "Copies the selected objects (Ctrl+D)." }, "Duplicate");
        const bDel = h("button", { class: "btn small danger", tip: "Deletes the selected objects (Delete key)." }, "Delete");
        const bUndo = h("button", { class: "btn small", tip: "Takes back the last change (Ctrl+Z)." }, "↶ Undo");
        const bRedo = h("button", { class: "btn small", tip: "Puts back what you took back (Ctrl+Y)." }, "↷ Redo");
        const zi = h("button", { class: "btn small", tip: "Bigger." }, "＋"), zo = h("button", { class: "btn small", tip: "Smaller." }, "－");
        const prev = h("button", { class: "btn small", tip: "Previous page." }, "◀"), next = h("button", { class: "btn small", tip: "Next page." }, "▶");
        const pageLab = h("span", { class: "hint", style: "margin:0 6px" });
        const save = h("button", { class: "primary", tip: "Saves the edited PDF as a new file. The original stays as it is." }, "Save a copy");
        const bar = h("div", { class: "row", style: "gap:6px;flex-wrap:wrap;align-items:center;margin-top:12px" }, open, ...toolBtns, bPic, picIn, bDup, bDel, bUndo, bRedo, zo, zi, prev, pageLab, next, save);
        const form = F.form([
          { id: "nofill", type: "check", label: "No fill (see-through inside)", value: false },
          { id: "fill", type: "color", label: "Fill / text colour", value: "#dbeafe", options: [{ v: "#dbeafe", l: "Light blue" }, { v: "#e0f3ec", l: "Mint" }, { v: "#fde68a", l: "Yellow" }, { v: "#fecaca", l: "Rose" }, { v: "#ffffff", l: "White" }, { v: "#111111", l: "Black" }], tip: "The colour inside a shape, or the colour of text." },
          { id: "nostroke", type: "check", label: "No outline", value: false },
          { id: "stroke", type: "color", label: "Outline / line colour", value: "#2563eb", options: [{ v: "#2563eb", l: "Blue" }, { v: "#dc2626", l: "Red" }, { v: "#16a34a", l: "Green" }, { v: "#111111", l: "Black" }, { v: "#6b7280", l: "Grey" }], tip: "The colour of outlines, lines and arrows." },
          { id: "lw", type: "number", label: "Line thickness", value: 2, tip: "In points. 0.5 is thin, 4 is bold." },
          { id: "size", type: "number", label: "Text size", value: 16, tip: "In points. Only for text." },
          { id: "text", type: "textarea", label: "Text", rows: 3, tip: "Retypes the selected text. New text is written in a standard font (Helvetica, Times or Courier)." }], () => fromForm());
        const note = h("div", { class: "hint", text: "Nothing selected." });
        const stage = h("div", { style: "position:relative;display:inline-block;touch-action:none;user-select:none;margin-top:10px;border:1px solid var(--line);background:#fff;line-height:0" });
        const img = h("img", { alt: "PDF page", draggable: "false", style: "display:block;width:100%" });
        const ov = h("div", { style: "position:absolute;inset:0" });
        stage.append(img, ov);
        main.append(bar, h("div", { style: "display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap" }, h("div", { style: "overflow:auto;max-width:100%" }, stage), h("div", { class: "card-box", style: "min-width:260px;flex:1" }, note, form.el)));
        const status = h("div", { class: "hint" }); main.append(status);

        function setTool(t) { S.tool = t; toolBtns.forEach((b) => b.setAttribute("aria-pressed", b.dataset.tool === t)); stage.style.cursor = t === "select" ? "default" : "crosshair"; }
        setTool("select");

        // ---- geometry of every object as the screen shows it
        const boxOf = (key) => {
          const [k, id] = [key[0], +key.slice(2)];
          if (k === "o") { const o = S.info.objects.find((x) => x.id === id); if (!o) return null; const m = pg().mods[id] || {}; if (m.delete) return null; return { x: o.x + (m.dx || 0), y: o.y + (m.dy || 0), w: o.w * (m.sx || 1), h: o.h * (m.sy || 1), o, m }; }
          const a = pg().adds.find((x) => x.id === id); if (!a) return null;
          if (a.type === "line" || a.type === "arrow") return { x: Math.min(a.x, a.x2), y: Math.min(a.y, a.y2), w: Math.abs(a.x2 - a.x), h: Math.abs(a.y2 - a.y), a };
          if (a.type === "text") { const ls = String(a.text || "").split("\n"); return { x: a.x, y: a.y, w: Math.max(...ls.map((l) => l.length)) * a.size * 0.55 + 2, h: ls.length * a.size * 1.3, a }; }
          return { x: a.x, y: a.y, w: a.w, h: a.h, a };
        };
        const allKeys = () => [...S.info.objects.map((o) => "o:" + o.id), ...pg().adds.map((a) => "a:" + a.id)];
        const K = () => S.k;

        function draw() {
          ov.replaceChildren();
          for (const key of allKeys()) {
            const b = boxOf(key); if (!b) continue;
            const kind = key[0] === "o" ? b.o.kind : b.a.type; const thin = Math.max(b.w * K(), 0) < 8 || Math.max(b.h * K(), 0) < 8;
            const d = h("div", { "data-key": key, class: "vobj", style: `position:absolute;left:${b.x * K() - (thin && b.w * K() < 8 ? 4 : 0)}px;top:${b.y * K() - (thin && b.h * K() < 8 ? 4 : 0)}px;width:${Math.max(b.w * K(), 8)}px;height:${Math.max(b.h * K(), 8)}px;box-sizing:border-box;cursor:move;border:1px solid ${S.sel.has(key) ? "#7c6cff" : "transparent"};background:${S.sel.has(key) ? "rgba(124,108,255,.10)" : "transparent"}` });
            d.title = kind === "text" ? "Text" : kind === "image" ? "Picture" : kind === "group" ? "Group" : "Shape";
            ov.append(d);
          }
          const one = S.sel.size === 1 ? [...S.sel][0] : null;
          if (one) { const b = boxOf(one); if (b) { const hd = (cx, cy, id) => ov.append(h("div", { "data-handle": id, style: `position:absolute;left:${cx - 6}px;top:${cy - 6}px;width:12px;height:12px;border-radius:50%;background:#7c6cff;border:2px solid #fff;cursor:nwse-resize;box-shadow:0 1px 4px rgba(0,0,0,.4)` }));
            if (b.a && (b.a.type === "line" || b.a.type === "arrow")) { hd(b.a.x * K(), b.a.y * K(), "p1"); hd(b.a.x2 * K(), b.a.y2 * K(), "p2"); } else hd((b.x + b.w) * K(), (b.y + b.h) * K(), "se"); } }
          pageLab.textContent = `Page ${S.page} of ${S.total}`;
          note.textContent = S.sel.size ? `${S.sel.size} selected.` : "Nothing selected. Click an object, or drag a box around several.";
        }

        async function refresh() {
          const my = ++S.seq;
          try {
            const r = await post("/api/pdfobj/preview", { paths: [S.path], number: S.page, rows: [pageRows()], options: { dpi: 110 } });
            if (my !== S.seq) return;
            img.src = r.png; stage.style.width = S.info.w * K() + "px"; status.textContent = "";
          } catch (e) { status.textContent = e.message; }
        }
        const pageRows = () => { const p = pg(); return { page: S.page, mods: Object.values(p.mods), adds: p.adds }; };
        const commit = () => { draw(); refresh(); };

        // ---- loading
        async function loadPage(n) {
          try {
            const r = await post("/api/pdfobj/open", { paths: [S.path], number: n });
            S.info = r; S.page = n; S.total = r.total; S.type = r.type; S.sel.clear(); if (n === 1 || !S.kset) { S.k = Math.min(1.4, 900 / r.w); S.kset = true; } S.u = Math.max(1, r.w / 600); stage.style.width = r.w * K() + "px"; if (n === 1 && S.u > 1) { form.set("lw", Math.round(2 * S.u)); form.set("size", Math.round(16 * S.u)); } draw(); refresh(); if (r.note) F.toast(r.note);
            if (r.capped) F.toast("This page has a very large number of objects; only the first ones can be picked.");
          } catch (e) { F.toast(e.message); }
        }
        open.onclick = () => { const p = (F.state.sources || []).find((s) => /\.(pdf|pptx|svg|png|jpe?g|webp|bmp|gif|tiff?)$/i.test(s)); if (!p) return F.toast("Add a PDF, PowerPoint (.pptx), SVG or picture on the left first."); S.path = p; S.kset = false; S.pages = {}; S.hist = []; S.fut = []; loadPage(1); };
        prev.onclick = () => S.info && S.page > 1 && loadPage(S.page - 1);
        next.onclick = () => S.info && S.page < S.total && loadPage(S.page + 1);
        zi.onclick = () => { S.k = Math.min(4, S.k * 1.2); S.info && (stage.style.width = S.info.w * K() + "px", draw()); };
        zo.onclick = () => { S.k = Math.max(0.5, S.k / 1.2); S.info && (stage.style.width = S.info.w * K() + "px", draw()); };

        // ---- changing things
        const modFor = (id) => (pg().mods[id] ||= { id });
        function eachSel(fn) { for (const key of S.sel) { const id = +key.slice(2); if (key[0] === "o") fn(modFor(id), key, null); else { const a = pg().adds.find((x) => x.id === id); if (a) fn(a, key, a); } } }
        function fromForm() {
          if (!S.sel.size || fromForm.lock) return; snap(); const v = form.values();
          eachSel((t, key, add) => {
            const ob = add ? null : S.info.objects.find((x) => x.id === +key.slice(2)), kind = add ? add.type : ob.kind;
            if (ob && ob.textable && kind !== "text") { if (v.text !== (ob.text || "")) t.text = v.text; }
            if (kind === "text") { t.fill = v.fill; if (add) { t.color = v.fill; t.size = +v.size || 14; } if (v.text !== "" && v.text != null && (add || v.text !== (S.info.objects.find((x) => x.id === +key.slice(2)).text || ""))) t.text = v.text; }
            else if (kind === "image" || kind === "group") { /* pictures keep their pixels */ }
            else { t.fill = v.nofill ? "" : v.fill; t.stroke = v.nostroke ? "" : v.stroke; t.lw = +v.lw || 1; if (add && (add.type === "line" || add.type === "arrow")) { t.stroke = v.stroke; t.fill = ""; } }
          });
          commit();
        }
        function syncForm() {
          fromForm.lock = true;
          const key = [...S.sel][0]; if (key) { const b = boxOf(key); const src = b.a || { ...b.o, ...(b.m || {}) };
            if (src.fill) form.set("fill", src.fill); form.set("nofill", !src.fill && (b.a ? b.a.type !== "text" : b.o.kind === "shape")); if (src.stroke) form.set("stroke", src.stroke); form.set("nostroke", !src.stroke && (b.a ? b.a.type !== "text" : b.o.kind === "shape"));
            if (src.lw != null) form.set("lw", src.lw); if (src.size) form.set("size", src.size); form.set("text", src.text || ""); }
          fromForm.lock = false;
        }
        bDel.onclick = () => { if (!S.sel.size) return; snap(); for (const key of S.sel) { const id = +key.slice(2); if (key[0] === "o") modFor(id).delete = true; else pg().adds = pg().adds.filter((a) => a.id !== id); } S.sel.clear(); commit(); };
        bDup.onclick = () => { if (!S.sel.size) return; snap(); const ns = new Set(); for (const key of S.sel) { const id = +key.slice(2); if (key[0] === "o") { const m = modFor(id); m.dup = { dx: 14 * S.u, dy: 14 * S.u }; } else { const a = pg().adds.find((x) => x.id === id); if (a) { const c = { ...a, id: ++S.nid, x: a.x + 14 * S.u, y: a.y + 14 * S.u }; if (a.x2 != null) { c.x2 = a.x2 + 14 * S.u; c.y2 = a.y2 + 14 * S.u; } pg().adds.push(c); ns.add("a:" + c.id); } } } S.sel = ns.size ? ns : S.sel; commit(); F.toast("Copied. Copies of original objects can be moved after you save and reopen the file."); };
        bUndo.onclick = () => { if (!S.hist.length) return; S.fut.push(JSON.stringify(S.pages)); S.pages = JSON.parse(S.hist.pop()); S.sel.clear(); commit(); };
        bRedo.onclick = () => { if (!S.fut.length) return; S.hist.push(JSON.stringify(S.pages)); S.pages = JSON.parse(S.fut.pop()); S.sel.clear(); commit(); };
        S.nid = 0;
        bPic.onclick = () => { if (!S.info) return F.toast("Open a file first."); picIn.value = ""; picIn.click(); };
        picIn.onchange = () => { const f = picIn.files[0]; if (!f) return; const rd = new FileReader(); rd.onload = () => { const im = new Image(); im.onload = () => { snap(); const w = Math.min(S.info.w * 0.4, im.width), hh = w * im.height / im.width, id = ++S.nid;
          pg().adds.push({ id, type: "image", x: S.info.w * 0.3, y: S.info.h * 0.3, w, h: hh, data: rd.result }); S.sel = new Set(["a:" + id]); commit(); }; im.src = rd.result; }; rd.readAsDataURL(f); };

        // ---- mouse and touch
        const pos = (e) => { const r = ov.getBoundingClientRect(); return [(e.clientX - r.left) / K(), (e.clientY - r.top) / K()]; };
        let drag = null;
        ov.addEventListener("pointerdown", (e) => {
          if (!S.info) return; ov.setPointerCapture(e.pointerId);
          const p = pos(e), hd = e.target.dataset && e.target.dataset.handle, key = e.target.dataset && e.target.dataset.key;
          if (hd) { snap(); const k1 = [...S.sel][0]; drag = { type: "resize", hd, key: k1, p, b: boxOf(k1) }; return; }
          if (S.tool !== "select") {
            snap(); const id = ++S.nid, t = S.tool, v = form.values(), u = S.u;
            const base = { id, type: t, x: p[0], y: p[1], stroke: v.nostroke ? "" : v.stroke, fill: v.nofill ? "" : v.fill, lw: +v.lw || 2 };
            if (t === "text") { Object.assign(base, { text: "Text", size: (+v.size || 16), color: v.fill && v.fill !== "#dbeafe" ? v.fill : "#111111", fill: "" }); pg().adds.push(base); S.sel = new Set(["a:" + id]); setTool("select"); syncForm(); commit(); return; }
            if (t === "line" || t === "arrow") { Object.assign(base, { x2: p[0], y2: p[1], stroke: v.stroke, fill: "" }); } else Object.assign(base, { w: 1, h: 1 });
            pg().adds.push(base); S.sel = new Set(["a:" + id]); drag = { type: "draw", id, p }; return;
          }
          if (key && e.altKey) { const b0 = boxOf(key); S.sel = new Set(allKeys().filter((k2) => { const b = boxOf(k2); return b && b.x >= b0.x - 0.5 && b.y >= b0.y - 0.5 && b.x + b.w <= b0.x + b0.w + 0.5 && b.y + b.h <= b0.y + b0.h + 0.5; })); S.sel.add(key); syncForm(); snap(); drag = { type: "move", p, moved: false }; draw(); return; }
          if (key) { if (e.shiftKey) { S.sel.has(key) ? S.sel.delete(key) : S.sel.add(key); } else if (!S.sel.has(key)) S.sel = new Set([key]); syncForm(); snap(); drag = { type: "move", p, moved: false }; draw(); return; }
          if (!e.shiftKey) S.sel.clear(); drag = { type: "marquee", p, box: h("div", { style: "position:absolute;border:1px dashed #7c6cff;background:rgba(124,108,255,.08);pointer-events:none" }) }; ov.append(drag.box); draw();
        });
        ov.addEventListener("pointermove", (e) => {
          if (!drag) return; const p = pos(e), dx = p[0] - drag.p[0], dy = p[1] - drag.p[1];
          if (drag.type === "move") { drag.moved = true; for (const d of ov.querySelectorAll(".vobj")) if (S.sel.has(d.dataset.key)) d.style.transform = `translate(${dx * K()}px,${dy * K()}px)`; drag.dx = dx; drag.dy = dy; }
          else if (drag.type === "draw") { const a = pg().adds.find((x) => x.id === drag.id); if (a.type === "line" || a.type === "arrow") { a.x2 = p[0]; a.y2 = p[1]; if (e.shiftKey) { if (Math.abs(a.x2 - a.x) > Math.abs(a.y2 - a.y)) a.y2 = a.y; else a.x2 = a.x; } } else { a.x = Math.min(drag.p[0], p[0]); a.y = Math.min(drag.p[1], p[1]); a.w = Math.abs(dx); a.h = Math.abs(dy); } draw(); }
          else if (drag.type === "resize") {
            const k = drag.key, id = +k.slice(2);
            if (k[0] === "a") { const a = pg().adds.find((x) => x.id === id);
              if (drag.hd === "p1") { a.x = p[0]; a.y = p[1]; } else if (drag.hd === "p2") { a.x2 = p[0]; a.y2 = p[1]; }
              else if (a.type === "text") { const s = Math.max(0.2, (drag.b.w + dx) / drag.b.w); a.size = Math.max(4, Math.round(drag.b.a.size * s * 10) / 10); }
              else { a.w = Math.max(2, drag.b.w + dx); a.h = Math.max(2, drag.b.h + dy); } }
            else { const m = modFor(id), o = drag.b.o; if (o.kind === "text") { m.sx = m.sy = Math.max(0.2, (drag.b.w + dx) / o.w); } else { m.sx = Math.max(0.05, (drag.b.w + dx) / o.w); m.sy = Math.max(0.05, (drag.b.h + dy) / o.h); } }
            draw();
          } else if (drag.type === "marquee") { const x = Math.min(drag.p[0], p[0]) * K(), y = Math.min(drag.p[1], p[1]) * K(); Object.assign(drag.box.style, { left: x + "px", top: y + "px", width: Math.abs(dx) * K() + "px", height: Math.abs(dy) * K() + "px" }); drag.q = [Math.min(drag.p[0], p[0]), Math.min(drag.p[1], p[1]), Math.max(drag.p[0], p[0]), Math.max(drag.p[1], p[1])]; }
        });
        ov.addEventListener("pointerup", () => {
          if (!drag) return; const d = drag; drag = null;
          if (d.type === "move") { if (d.moved && (Math.abs(d.dx) > 0.2 || Math.abs(d.dy) > 0.2)) nudge(d.dx, d.dy); else { S.hist.pop(); draw(); } return; }
          if (d.type === "marquee") { if (d.q) for (const key of allKeys()) { const b = boxOf(key); if (b && b.x >= d.q[0] && b.y >= d.q[1] && b.x + b.w <= d.q[2] && b.y + b.h <= d.q[3]) S.sel.add(key); } syncForm(); draw(); return; }
          if (d.type === "draw") setTool("select");
          syncForm(); commit();
        });
        function nudge(dx, dy) {
          for (const key of S.sel) { const id = +key.slice(2); if (key[0] === "o") { const m = modFor(id); m.dx = Math.round(((m.dx || 0) + dx) * 100) / 100; m.dy = Math.round(((m.dy || 0) + dy) * 100) / 100; } else { const a = pg().adds.find((x) => x.id === id); if (a) { a.x += dx; a.y += dy; if (a.x2 != null) { a.x2 += dx; a.y2 += dy; } } } }
          commit();
        }
        ov.addEventListener("dblclick", (e) => { const key = e.target.dataset && e.target.dataset.key; if (!key) return; S.sel = new Set([key]); syncForm(); draw(); const ta = form.el.querySelector("textarea"); ta && ta.focus(); });
        sec.addEventListener("keydown", (e) => {
          if (!S.info || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ""))) return;
          if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); bDel.onclick(); }
          else if (e.ctrlKey && e.key.toLowerCase() === "z") { e.preventDefault(); bUndo.onclick(); }
          else if (e.ctrlKey && e.key.toLowerCase() === "y") { e.preventDefault(); bRedo.onclick(); }
          else if (e.ctrlKey && e.key.toLowerCase() === "d") { e.preventDefault(); bDup.onclick(); }
          else if (e.key.startsWith("Arrow") && S.sel.size) { e.preventDefault(); snap(); const s = e.shiftKey ? 10 : 1; nudge(e.key === "ArrowLeft" ? -s : e.key === "ArrowRight" ? s : 0, e.key === "ArrowUp" ? -s : e.key === "ArrowDown" ? s : 0); }
        });
        sec.tabIndex = 0;

        save.onclick = async () => {
          if (!S.info) return F.toast("Open a PDF first.");
          const pages = Object.entries(S.pages).map(([n, p]) => ({ page: +n, mods: Object.values(p.mods), adds: p.adds })).filter((p) => p.mods.length || p.adds.length);
          if (!pages.length) return F.toast("Nothing has been changed yet.");
          try { const r = await post("/api/editor/save", { path: S.path, kind: "pdfobj", payload: { pages }, output: F.outputBody(), replace: false }); F.toast("Saved a copy"); status.replaceChildren(h("span", { text: "Saved: " + r.path + "  " }), h("button", { class: "btn small", onclick: () => F.openFile(r.path) }, "Open"), " ", h("button", { class: "btn small", onclick: () => F.reveal(r.path) }, "Show folder")); }
          catch (e) { F.toast(e.message); }
        };
      } });
  } catch (e) { console.warn("Fathom: the visual editor could not load", e); }
})();
