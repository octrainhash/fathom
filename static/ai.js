/* The Assistant: a chat that can see what you are doing in Fathom, use every tool, make documents, pictures and videos, read your files, and add new tools
   to the app ("My tools"). Also: the floating "Ask Fathom" button, screen awareness, and the settings. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api, $ = F.$;
  const post = (p, b) => api(p, { method: "POST", body: b || {} });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const KIND_ICON = { pdf: "📕", image: "🖼", video: "🎞", audio: "🎵", text: "📝", office: "📄", file: "📄" };
  const PREVIEWABLE = new Set(["pdf", "image", "office"]);

  /* ================= what you are doing (sent to the assistant so it knows) ================= */
  F.activity = [];
  const logAct = (what) => { F.activity.push({ time: new Date().toLocaleTimeString(), what }); if (F.activity.length > 30) F.activity.shift(); schedule(); };
  const SKIP = /^\/api\/(ai|thumb|pdf\/page|preview\/|editor\/image|health|tools\/undo|capabilities|drives\/health|torrent\/status)/;
  const seen = new Set();
  const _fetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const res = await _fetch(input, init);
    try {
      const url = (typeof input === "string" ? input : input.url).replace(location.origin, "");
      const method = ((init && init.method) || "GET").toUpperCase();
      if (url.startsWith("/api/") && !SKIP.test(url)) {
        if (method === "POST" && !/\/cancel$/.test(url)) {
          let b = {}; try { b = JSON.parse(init.body || "{}"); } catch { /* not json */ }
          const bits = [];
          if (b.paths) bits.push(`${b.paths.length} file(s)`);
          for (const k of ["mode", "kind", "value", "text", "number"]) if (b[k] !== undefined && b[k] !== "" && b[k] !== 0 && b[k] !== false) bits.push(`${k}=${String(b[k]).slice(0, 60)}`);
          if (b.options) bits.push("options=" + JSON.stringify(b.options).slice(0, 160));
          logAct(`Started ${url} ${bits.join(", ")}`);
        } else if (method === "GET" && /^\/api\/(ops|jobs)\/[0-9a-f]+/.test(url)) {
          const id = url.split("/")[3].split("?")[0];
          if (!seen.has(id)) res.clone().json().then((s) => {
            if (s && ["done", "failed", "cancelled"].includes(s.status) && !seen.has(id)) {
              seen.add(id); const c = s.counts || {};
              const outs = (s.results || []).flatMap((r) => (r.outputs || []).map((o) => o.path)).slice(0, 4);
              logAct(`${s.title || s.kind || "Job"} ${s.status}` + (c.done !== undefined ? `: ${c.done} done, ${c.error || 0} problems` : "") + (outs.length ? ` → ${outs.join("; ")}` : ""));
            }
          }).catch(() => {});
        }
      }
    } catch { /* never break the app */ }
    return res;
  };

  const labelOf = (el) => {
    const f = el.closest(".field, label, .row");
    const l = (el.id && document.querySelector(`label[for="${el.id}"]`)) || (f && f.querySelector("label"));
    return ((l && l.textContent) || el.getAttribute("aria-label") || el.placeholder || el.name || el.id || "").trim().slice(0, 70);
  };
  function snapshot() {
    const t = F.currentTool, view = t && t.el, form = {};
    if (view) {
      let n = 0;
      for (const el of view.querySelectorAll("input,select,textarea")) {
        if (n > 70 || el.closest(".ai-root") || el.type === "password" || el.type === "file" || el.hidden || el.closest("[hidden]")) continue;
        let v;
        if (el.type === "checkbox") v = el.checked; else if (el.type === "radio") { if (!el.checked) continue; v = labelOf(el) || el.value; }
        else if (el.tagName === "SELECT") v = el.selectedOptions[0] ? el.selectedOptions[0].textContent : el.value; else v = (el.value || "").slice(0, 300);
        if (v === "" || v == null) continue;
        let k = labelOf(el) || "field"; while (k in form) k += "'"; form[k] = v; n++;
      }
    }
    const title = view && view.querySelector(".page-title");
    return {
      tool: t ? { id: t.id, label: t.label, group: t.group, what_it_does: t.blurb } : null, screen_title: title ? title.textContent : "", form_values: form,
      files_added_on_the_left: F.state.sources.slice(0, 200), files_added_count: F.state.sources.length, where_results_go: F.state.output,
      recent_activity: F.activity.slice(-20), assistant_tools_added_by_user: (F.ai && F.ai.pluginIds) || [],
    };
  }
  let ctxTimer = 0;
  function schedule() { clearTimeout(ctxTimer); ctxTimer = setTimeout(() => { post("/api/ai/context", { context: snapshot() }).catch(() => {}); }, 500); }
  document.addEventListener("input", (e) => { if (!e.target.closest(".ai-root")) schedule(); }, true);
  document.addEventListener("change", (e) => { if (!e.target.closest(".ai-root")) schedule(); }, true);
  const _show = F.show; F.show = (id) => { _show(id); schedule(); setTimeout(updateFab, 0); };
  F.watchSources && F.watchSources(schedule);
  setInterval(schedule, 15000);

  /* ================= tiny, safe Markdown ================= */
  function inline(text, into) {
    const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(!\[[^\]]*\]\([^)]+\))|(\[[^\]]+\]\([^)]+\))|(?<![\w*])(\*[^*\s][^*]*\*)(?![\w*])|(https?:\/\/[^\s)<]+)/g;
    let pos = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > pos) into.append(text.slice(pos, m.index));
      const s = m[0];
      if (m[1]) into.append(h("code", { text: s.slice(1, -1) }));
      else if (m[2]) { const b = h("strong"); inline(s.slice(2, -2), b); into.append(b); }
      else if (m[3]) { const mm = /!\[([^\]]*)\]\(([^)]+)\)/.exec(s); const src = /^https?:/.test(mm[2]) ? mm[2] : F.thumbUrl(mm[2], 1200); into.append(h("img", { class: "ai-img", src, alt: mm[1], tip: "Click to open it larger.", onclick: () => preview({ path: mm[2], name: mm[1] || F.baseName(mm[2]), kind: "image" }) })); }
      else if (m[4]) { const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(s); into.append(/^https?:/.test(mm[2]) ? h("a", { href: mm[2], target: "_blank", rel: "noopener", text: mm[1] }) : h("button", { class: "link", tip: "Opens this file.", onclick: () => F.openFile(mm[2]) }, mm[1])); }
      else if (m[5]) { const i = h("em"); inline(s.slice(1, -1), i); into.append(i); }
      else if (m[6]) into.append(h("a", { href: s, target: "_blank", rel: "noopener", text: s }));
      pos = m.index + s.length;
    }
    if (pos < text.length) into.append(text.slice(pos));
  }
  function markdown(src) {
    const root = h("div", { class: "md" }); const lines = String(src).replace(/\r/g, "").split("\n"); let i = 0;
    while (i < lines.length) {
      const ln = lines[i], s = ln.trim();
      if (!s) { i++; continue; }
      if (/^```/.test(s)) { const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i].trim())) buf.push(lines[i++]); i++; root.append(h("pre", {}, h("code", { text: buf.join("\n") }), h("button", { class: "copy", tip: "Copies this text.", onclick: () => { navigator.clipboard && navigator.clipboard.writeText(buf.join("\n")); F.toast("Copied"); } }, "Copy"))); continue; }
      let m = /^(#{1,4})\s+(.*)$/.exec(s);
      if (m) { const e = h("h" + (m[1].length + 2)); inline(m[2], e); root.append(e); i++; continue; }
      if (/^([-*_])(\s*\1){2,}$/.test(s)) { root.append(h("hr")); i++; continue; }
      if (s.startsWith(">")) { const buf = []; while (i < lines.length && lines[i].trim().startsWith(">")) buf.push(lines[i++].replace(/^\s*>\s?/, "")); const q = h("blockquote"); inline(buf.join(" "), q); root.append(q); continue; }
      if (s.includes("|") && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(lines[i + 1] || "") && (lines[i + 1] || "").includes("|")) {
        const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const tb = h("table", { class: "tbl" }), head = h("tr"); cells(ln).forEach((c) => { const th = h("th"); inline(c, th); head.append(th); }); tb.append(head); i += 2;
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) { const tr = h("tr"); cells(lines[i++]).forEach((c) => { const td = h("td"); inline(c, td); tr.append(td); }); tb.append(tr); }
        root.append(h("div", { class: "tbl-wrap" }, tb)); continue;
      }
      m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(ln);
      if (m) {
        const ordered = /\d/.test(m[2]), list = h(ordered ? "ol" : "ul"); const base = m[1].length;
        while (i < lines.length) { const mm = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]); if (!mm) break; const li = h("li"); if (mm[1].length > base + 1) li.style.marginLeft = "18px"; inline(mm[3], li); list.append(li); i++; }
        root.append(list); continue;
      }
      const buf = [s]; i++;
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\s*([-*+]|\d+[.)])\s)/.test(lines[i])) buf.push(lines[i++].trim());
      const p = h("p"); inline(buf.join(" "), p); root.append(p);
    }
    return root;
  }

  /* ================= previews and file cards ================= */
  function previewUrl(f, page = 0, size = 900) { return PREVIEWABLE.has(f.kind) ? `/api/preview/page?path=${encodeURIComponent(f.path)}&page=${page}&size=${size}&t=${encodeURIComponent(F.TOKEN)}` : ""; }
  function preview(f) {
    if (!PREVIEWABLE.has(f.kind)) return F.openFile(f.path);
    let page = 0, pages = 1;
    const img = h("img", { alt: f.name, style: "max-width:100%;max-height:100%;border-radius:8px;background:#fff" });
    const lab = h("span", { class: "hint" });
    const load = () => { img.src = previewUrl(f, page, 1600); fetch(img.src).then((r) => { pages = +r.headers.get("X-Pages") || 1; lab.textContent = pages > 1 ? `Page ${page + 1} of ${pages}` : ""; prev.disabled = page <= 0; next.disabled = page >= pages - 1; }).catch(() => {}); };
    const prev = h("button", { class: "btn small", onclick: () => { page = Math.max(0, page - 1); load(); } }, "‹ Previous"), next = h("button", { class: "btn small", onclick: () => { page = Math.min(pages - 1, page + 1); load(); } }, "Next ›");
    const close = () => back.remove();
    const back = h("div", { class: "ai-modal", onclick: (e) => { if (e.target === back) close(); } },
      h("div", { class: "ai-modal-box" }, h("div", { class: "row", style: "gap:10px;align-items:center" }, h("b", { text: f.name }), lab, h("span", { style: "flex:1" }), prev, next, h("button", { class: "btn small", onclick: () => F.openFile(f.path), tip: "Opens it in your usual program." }, "Open"), h("button", { class: "btn small", onclick: close }, "Close ✕")), h("div", { class: "ai-modal-stage" }, img)));
    document.body.append(back); load();
    const esc = (e) => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); } }; document.addEventListener("keydown", esc);
  }
  function fileCard(f) {
    const pv = PREVIEWABLE.has(f.kind);
    return h("div", { class: "ai-file" },
      pv ? h("img", { class: "th", src: previewUrl(f, 0, 360), alt: "", loading: "lazy", onerror: (e) => e.target.replaceWith(h("div", { class: "th ic", text: KIND_ICON[f.kind] || "📄" })), onclick: () => preview(f) }) : h("div", { class: "th ic", text: KIND_ICON[f.kind] || "📄" }),
      h("div", { class: "fi" }, h("b", { text: f.name, title: f.path }), h("small", { text: [f.kind !== "file" ? f.kind : "", f.bytes ? F.fmtBytes(f.bytes) : ""].filter(Boolean).join(" · ") }),
        h("div", { class: "row", style: "gap:6px;flex-wrap:wrap;margin-top:6px" },
          pv ? h("button", { class: "btn small", tip: "Look at it here, page by page.", onclick: () => preview(f) }, "Preview") : null,
          h("button", { class: "btn small", tip: "Opens the file in your usual program.", onclick: () => F.openFile(f.path) }, "Open"),
          h("button", { class: "btn small", tip: "Opens the folder with the file selected.", onclick: () => F.reveal(f.path) }, "Show"),
          h("button", { class: "btn small", tip: "Adds this file to the list on the left so you can use it in any Fathom tool.", onclick: () => F.addPaths([f.path]) }, "Use in Fathom"),
          f.kind !== "image" && f.kind !== "video" && f.kind !== "audio" && F.editFile ? h("button", { class: "btn small", tip: "Opens the file in Fathom's editor so you can change what is inside it by hand.", onclick: () => F.editFile(f.path) }, "Edit") : null)));
  }

  /* ================= the chat ================= */
  const ai = F.ai = { sid: F.load("ai.sid", ""), since: 0, running: false, pending: [], pluginIds: [], listeners: [], decorators: [], settingsCards: [] };
  let chat = null;

  function buildChat(compact) {
    const root = h("div", { class: "ai-root" + (compact ? " compact" : "") });
    const title = h("b", { class: "ai-title", text: "New chat" });
    const approval = h("select", { tip: "When the assistant asks you first.\nAsk before changes: it asks before changing your files, running code or adding tools.\nAsk before everything: it asks before reading too.\nNever ask: it just does it (careful!).", onchange: () => post("/api/ai/settings", { settings: { approval: approval.value } }).catch((e) => F.toast(e.message)) },
      [["ask_changes", "Ask before changes"], ["ask_all", "Ask before everything"], ["never", "Never ask"]].map(([v, l]) => h("option", { value: v, text: l })));
    const histBtn = h("button", { class: "btn small", tip: "Your earlier chats. Pick one to continue it.", onclick: () => history() }, "History");
    const newBtn = h("button", { class: "btn small", tip: "Starts a fresh conversation. The old one is saved in History.", onclick: () => newChat() }, "New chat");
    const setBtn = h("button", { class: "btn small", tip: "Choose the AI model and add your key, set up pictures and voice.", onclick: () => F.show("aisettings") }, "Settings");
    const head = h("div", { class: "ai-head" }, title, h("span", { style: "flex:1" }), approval, histBtn, newBtn, setBtn);
    const list = h("div", { class: "ai-list", "aria-live": "polite" });
    const welcome = h("div", { class: "ai-welcome" });
    const chips = h("div", { class: "ai-attached" });
    const ta = h("textarea", { rows: 2, placeholder: "Ask anything… “make a PDF report from my files”, “add a tool that renames by date”, “read this handwriting”", tip: "Type what you want, then press Enter. Shift+Enter makes a new line. You can paste pictures, and drop files here." });
    const attach = h("button", { class: "btn small", tip: "Attach files for the assistant to work from: documents, pictures, anything. It can read them and use them.", onclick: async () => { try { const r = { paths: await F.pickPaths("files") }; addAttach((r.paths || []).map((p) => ({ path: p }))); } catch (e) { F.toast(e.message); } } }, "📎 Files");
    const attachDir = h("button", { class: "btn small", tip: "Attach a whole folder.", onclick: async () => { try { const r = { paths: await F.pickPaths("folder") }; addAttach((r.paths || []).map((p) => ({ path: p }))); } catch (e) { F.toast(e.message); } } }, "📁 Folder");
    const useList = h("button", { class: "btn small", tip: "Attach the files and folders in your Fathom list on the left.", onclick: () => { if (!F.state.sources.length) return F.toast("Your list on the left is empty."); addAttach(F.state.sources.map((p) => ({ path: p }))); } }, "Use my list");
    const sendBtn = h("button", { class: "primary", tip: "Sends your message.", onclick: () => submit() }, "Send");
    const stopBtn = h("button", { class: "btn danger", hidden: true, tip: "Stops the assistant. Anything already finished is kept.", onclick: () => { if (ai.beforeStop) ai.beforeStop(); stop(); } }, "Stop");
    const composer = h("div", { class: "ai-composer" }, chips, ta, h("div", { class: "row", style: "gap:8px;margin-top:8px;flex-wrap:wrap" }, attach, attachDir, useList, h("span", { style: "flex:1" }), stopBtn, sendBtn));
    const voiceRow = h("div", { class: "ai-voice" });
    composer.insertBefore(voiceRow, ta);
    root.append(head, h("div", { class: "ai-scroll" }, welcome, list), composer);
    const st = { ph: ta.placeholder, root, list, welcome, ta, chips, title, sendBtn, stopBtn, approval, cur: null, curRaw: "", tools: new Map(), think: null };
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
    st.voiceRow = voiceRow; for (const fn of ai.decorators) { try { fn(st); } catch (e) { console.error(e); } }
    ta.addEventListener("paste", async (e) => {
      const files = [...(e.clipboardData?.files || [])]; if (!files.length) return; e.preventDefault();
      for (const f of files) addAttach([await uploadFile(f)]);
    });
    root.addEventListener("dragover", (e) => { e.preventDefault(); e.stopPropagation(); root.classList.add("drag"); });
    root.addEventListener("dragleave", () => root.classList.remove("drag"));
    root.addEventListener("drop", async (e) => {
      e.preventDefault(); e.stopPropagation(); root.classList.remove("drag");
      for (const f of [...(e.dataTransfer?.files || [])]) { if (f.path) addAttach([{ path: f.path }]); else addAttach([await uploadFile(f)]); }
    });
    return st;
  }
  async function uploadFile(f) {
    const data = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
    return post("/api/ai/upload", { name: f.name || "pasted.png", data });
  }
  function addAttach(items) {
    for (const it of items) { if (it && it.path && !ai.pending.some((p) => p.path === it.path)) ai.pending.push({ path: it.path, name: it.name || F.baseName(it.path) }); }
    drawChips();
  }
  function drawChips() {
    for (const c of allChats()) {
      c.chips.replaceChildren(...ai.pending.map((p, i) => h("span", { class: "ai-chip", title: p.path }, "📎 " + p.name, h("button", { "aria-label": "Remove", tip: "Take this out of the message.", onclick: () => { ai.pending.splice(i, 1); drawChips(); } }, "×"))));
    }
  }
  const instances = [];
  const allChats = () => instances;

  async function submit(text, opts) {
    const c = chat; const t = (text !== undefined ? text : c.ta.value).trim();
    if (ai.running) { F.toast("The assistant is still working. Wait for it, or press Stop."); return; }
    if (!t && !ai.pending.length) return;
    const atts = ai.pending.splice(0); drawChips(); c.ta.value = "";
    try {
      setRunning(true);
      const r = await post("/api/ai/send", { sid: ai.sid, text: t, attachments: atts, voice: !!(opts && opts.voice), lang: (opts && opts.lang) || "" });
      if (r.sid !== ai.sid) { ai.sid = r.sid; ai.since = 0; F.save("ai.sid", ai.sid); }
      poll();
    } catch (e) { setRunning(false); F.toast(e.message); ai.pending.unshift(...atts); drawChips(); c.ta.value = t; }
  }
  ai.submit = submit; ai.isRunning = () => ai.running; ai.stop = () => stop();
  F.askAssistant = (text, files) => { F.show("aichat"); if (files) addAttach(files.map((p) => ({ path: p }))); if (text) { chat.ta.value = text; chat.ta.focus(); } };
  async function stop() { try { await post("/api/ai/stop", { sid: ai.sid }); } catch (e) { F.toast(e.message); } }
  function setRunning(on) {
    ai.running = on;
    for (const c of instances) { c.sendBtn.disabled = on; c.stopBtn.hidden = !on; c.ta.placeholder = on ? "Working… you can press Stop at any time." : c.ph; }
    updateFab();
  }

  async function poll() {
    if (ai.polling) return; ai.polling = true;
    try {
      while (ai.sid) {
        let r;
        try { r = await api(`/api/ai/events?sid=${ai.sid}&since=${ai.since}&wait=15`); } catch (e) { if (/not found/i.test(e.message)) break; await sleep(1500); continue; }
        for (const ev of r.events) { apply(ev); ai.since = ev.seq; }
        if (r.title) for (const c of instances) c.title.textContent = r.title;
        if (r.status === "idle" && !r.events.length) { setRunning(false); break; }
        if (r.status === "idle" && r.events.some((e) => e.type === "done")) { setRunning(false); break; }
      }
    } finally { ai.polling = false; }
  }

  /* each event is drawn into every open chat view (the tab and the side panel stay in step) */
  const per = (fn) => { for (const c of instances) fn(c); };
  const scrollDown = (c) => { const s = c.root.querySelector(".ai-scroll"); if (s) { const near = s.scrollHeight - s.scrollTop - s.clientHeight < 260; if (near) s.scrollTop = s.scrollHeight; } };
  function clearThink(c) {
    if (c.think) { c.think.remove(); c.think = null; }
    if (c.thinkTimer) { clearInterval(c.thinkTimer); c.thinkTimer = null; }
  }
  /* "Please wait, this takes time": shown under the three dots when an answer is slow; the time left comes from earlier answers on this PC */
  let answersThisSession = 0;     // the first answer after Fathom opens is the slow one (the model is still loading)
  function thinkNote(c) {
    const t0 = Date.now(); c.thinkT0 = t0;
    const first = answersThisSession === 0, key = first ? "assistant_first" : "assistant";
    const note = h("div", { class: "waitnote", hidden: true });
    c.think.querySelector(".bub").append(note);
    c.thinkTimer = setInterval(() => {
      const el = (Date.now() - t0) / 1000;
      if (el < 5) return;
      const typ = (F.typical ? F.typical(key) : null) || (first ? 90 : 15);        // seconds; learned on this PC, else a sensible guess
      let t = F.waitText ? F.waitText(el, typ, null) : "";
      if (first) t += " The first answer after Fathom opens is the slowest; the next ones are much faster.";
      note.textContent = t; note.hidden = false;
      c.think.querySelector(".bub").classList.add("long");
    }, 1000);
    c.thinkKey = key;
  }
  function apply(ev, replay) {
    for (const fn of ai.listeners) { try { fn(ev, replay); } catch (e) { console.error(e); } }
    per((c) => {
      c.welcome.hidden = true;
      if (ev.type !== "thinking") { if (c.thinkT0 && !replay && F.remember) { const d = (Date.now() - c.thinkT0) / 1000; if (d > 6) F.remember(c.thinkKey || "assistant", d); } c.thinkT0 = 0; clearThink(c); if ((ev.type === "text" || ev.type === "tool") && !replay) answersThisSession = 1; }
      switch (ev.type) {
        case "user": {
          c.cur = null;
          const b = h("div", { class: "ai-msg user" }, h("div", { class: "bub" }, ev.text ? (() => { const d = h("div"); d.textContent = ev.text; return d; })() : null,
            ...(ev.attachments || []).map((f) => h("span", { class: "ai-chip", title: f.path }, (KIND_ICON[f.kind] || "📄") + " " + f.name))));
          c.list.append(b); break;
        }
        case "text": {
          if (!c.cur) { c.curRaw = ""; const bub = h("div", { class: "bub" }); c.cur = bub; c.list.append(h("div", { class: "ai-msg bot" }, bub)); }
          c.curRaw += ev.delta; c.cur.replaceChildren(markdown(c.curRaw)); break;
        }
        case "thinking": if (!c.think) { c.think = h("div", { class: "ai-msg bot" }, h("div", { class: "bub think" }, h("div", { class: "dots" }, h("i"), h("i"), h("i")))); c.list.append(c.think); if (!replay) thinkNote(c); } break;
        case "tool": {
          c.cur = null;
          const status = h("span", { class: "st" }, h("i", { class: "spin" })), sum = h("div", { class: "sum", hidden: true }), sub = h("small", { class: "sub" });
          const card = h("div", { class: "ai-tool run" }, h("div", { class: "line", onclick: () => { sum.hidden = !sum.hidden && !!sum.textContent ? true : !sum.textContent; card.classList.toggle("open", !sum.hidden); } }, status, h("span", { class: "lbl", text: friendly(ev.name, ev.label) }), sub), sum);
          card._st = status; card._sum = sum; card._sub = sub; c.tools.set(ev.id, card); c.list.append(card); c.running = card; break;
        }
        case "progress": if (c.running) c.running._sub.textContent = ev.message ? " · " + ev.message + (ev.fraction ? ` (${Math.round(ev.fraction * 100)}%)` : "") : ""; break;
        case "tool_done": {
          const card = c.tools.get(ev.id); if (!card) break;
          card.classList.remove("run"); card.classList.add(ev.ok ? "ok" : "bad"); card._st.textContent = ev.ok ? "✓" : "⚠"; card._sub.textContent = "";
          card._sum.textContent = ev.summary || ""; card._sum.hidden = true;
          if (!ev.ok) { card._sum.hidden = false; card.classList.add("open"); }
          if (ev.thumbs && ev.thumbs.length) card.append(h("div", { class: "ai-thumbs" }, ...ev.thumbs.map((u) => h("img", { src: u, alt: "", onclick: () => window.open(u) }))));
          if (ev.files && ev.files.length) c.list.append(h("div", { class: "ai-files" }, ...ev.files.map(fileCard)));
          c.running = null; break;
        }
        case "proof": if (F.proofGallery) c.list.append(h("div", { class: "ai-proof" }, F.proofGallery(ev.items))); break;
        case "approval": {
          const card = h("div", { class: "ai-ask warn" }, h("b", { text: ev.risk === "run" ? "Run something on your computer?" : "Change your files?" }), h("pre", { text: ev.text }),
            h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:8px" },
              ...[["yes", "Allow", "primary", "Lets the assistant do just this."], ["always", "Allow this kind for this chat", "btn", "Stops asking about this kind of action until you start a new chat."], ["no", "Don't allow", "btn danger", "The assistant will not do it and will try another way."]].map(([v, l, cls, tip]) =>
                h("button", { class: cls === "primary" ? "primary" : cls, tip, onclick: () => { card.classList.add("done"); card.querySelectorAll("button").forEach((b) => (b.disabled = true)); post("/api/ai/answer", { sid: ai.sid, id: ev.id, answer: v }).catch((e) => F.toast(e.message)); } }, l))));
          card.setAttribute("data-id", ev.id); c.list.append(card); break;
        }
        case "ask": {
          const inp = h("input", { type: "text", placeholder: "Or type your own answer…" });
          const reply = (v) => { card.classList.add("done"); card.querySelectorAll("button,input").forEach((b) => (b.disabled = true)); post("/api/ai/answer", { sid: ai.sid, id: ev.id, answer: v }).catch((e) => F.toast(e.message)); };
          inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && inp.value.trim()) reply(inp.value.trim()); });
          const card = h("div", { class: "ai-ask" }, h("b", { text: ev.question }), h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:8px" }, ...(ev.choices || []).map((ch) => h("button", { class: "btn", onclick: () => reply(ch) }, ch)), inp, h("button", { class: "btn small", onclick: () => inp.value.trim() && reply(inp.value.trim()) }, "Answer")));
          card.setAttribute("data-id", ev.id); c.list.append(card); break;
        }
        case "answered": { const el = c.list.querySelector(`[data-id="${ev.id}"]`); if (el) { el.classList.add("done"); el.querySelectorAll("button,input").forEach((b) => (b.disabled = true)); } break; }
        case "ui": if (!replay) uiAction(ev); break;
        case "notice": c.list.append(h("div", { class: "ai-note", text: ev.text })); break;
        case "error": c.list.append(h("div", { class: "ai-note err" }, ev.message, ev.message && /key|Settings/i.test(ev.message) ? h("button", { class: "btn small", style: "margin-left:10px", onclick: () => F.show("aisettings") }, "Open settings") : null)); break;
        case "done": c.cur = null; break;
        default: break;
      }
      scrollDown(c);
    });
  }
  const FRIENDLY = { get_screen_context: "Looking at what you are doing", list_files: "Looking in a folder", read_file: "Reading a file", view_image: "Looking at a picture", search_files: "Searching your files", write_file: "Writing a file", edit_file: "Editing a file", file_operation: "Organising files",
    create_document: "Making a document", create_presentation: "Making a presentation", create_spreadsheet: "Making a spreadsheet", create_chart: "Drawing a chart", design_image: "Designing a picture", generate_image: "Making a picture", text_to_speech: "Making a voice recording", make_video: "Making a video",
    web_search: "Searching the web", web_fetch: "Reading a web page", run_python: "Running code", run_shell: "Running a command", fathom_tools: "Checking Fathom's tools", fathom_tool_info: "Checking how a tool works", fathom_run: "Using a Fathom tool", open_in_fathom: "Opening it in Fathom",
    create_tool: "Adding a new tool to Fathom", test_tool: "Testing the new tool", list_my_tools: "Checking your tools", read_my_tool: "Reading a tool", delete_my_tool: "Removing a tool", remember: "Remembering that", ask_user: "Asking you", show_files: "Showing files" };
  function friendly(name, label) { const f = FRIENDLY[name] || name; const detail = label && label !== name && !label.startsWith(name + " {") ? label.split("\n")[0].replace(/^(Run this (Python code|command):?)/, "").trim() : ""; return detail && name !== "get_screen_context" ? `${f}: ${detail.slice(0, 90)}` : f; }

  function uiAction(ev) {
    if (ev.action === "open") { if (ev.paths && ev.paths.length) F.addPaths(ev.paths); if (ev.tool && F.tools.some((t) => t.id === ev.tool)) F.show(ev.tool); }
    else if (ev.action === "tools_changed") loadPlugins(ev.open);
  }

  async function newChat() { ai.sid = ""; ai.since = 0; F.save("ai.sid", ""); resetViews(); }
  function resetViews() { for (const c of instances) { c.list.replaceChildren(); c.tools.clear(); c.cur = null; c.think = null; c.title.textContent = "New chat"; c.welcome.hidden = false; } setRunning(false); }
  async function openChat(sid) {
    try {
      const r = await api(`/api/ai/chat/${sid}`); ai.sid = sid; F.save("ai.sid", sid); resetViews();
      for (const c of instances) c.title.textContent = r.title || "Chat";
      for (const e of r.events) apply(e, true);
      ai.since = r.seq; if (r.status !== "idle") { setRunning(true); poll(); }
    } catch (e) { F.toast(e.message); }
  }
  async function history() {
    const r = await api("/api/ai/chats");
    const back = h("div", { class: "ai-modal", onclick: (e) => { if (e.target === back) back.remove(); } });
    const box = h("div", { class: "ai-modal-box small" }, h("div", { class: "row", style: "gap:10px" }, h("b", { text: "Your chats" }), h("span", { style: "flex:1" }), h("button", { class: "btn small", onclick: () => back.remove() }, "Close ✕")));
    if (!r.chats.length) box.append(h("p", { class: "hint", text: "No chats yet." }));
    for (const c of r.chats) box.append(h("div", { class: "ai-hist" }, h("button", { class: "link", onclick: () => { back.remove(); openChat(c.id); } }, c.title), h("small", { text: new Date(c.updated * 1000).toLocaleString() }),
      h("button", { class: "x", tip: "Deletes this chat for good.", "aria-label": "Delete chat", onclick: async (e) => { await post(`/api/ai/chat/${c.id}/delete`); e.target.closest(".ai-hist").remove(); if (c.id === ai.sid) newChat(); } }, "×")));
    back.append(box); document.body.append(back);
  }

  const SUGGEST = [
    ["📄 Make a PDF", "Make a polished PDF report from the files I added, with a summary and key points."],
    ["🧾 Summarise my files", "Read the files I added and give me a clear summary of each one."],
    ["✍️ Read handwriting", "Read the handwriting in the pictures or scans I added and type it out exactly."],
    ["🧰 Add a feature", "I want a new tool in Fathom that "],
    ["🎬 Make a video", "Make a short video presenting "],
    ["🖼 Make a poster", "Design a poster for "],
    ["📊 Analyse a table", "Analyse the spreadsheet I added and make a chart and a PDF of the findings."],
    ["🔎 Find something", "Look through my added files and tell me where "],
  ];
  function fillWelcome(c) {
    c.welcome.replaceChildren(h("h2", { text: "What would you like to do?" }), h("p", { class: "hint", text: "I can see what you are doing in Fathom, read and change your files, make PDFs, Word, Excel and PowerPoint files, draw pictures, make videos, use every Fathom tool, and add new tools to the app. Attach files or just tell me." }),
      h("div", { class: "ai-suggest" }, SUGGEST.map(([l, t]) => h("button", { class: "btn", tip: t, onclick: () => { c.ta.value = t; c.ta.focus(); } }, l))));
  }

  /* ================= tabs: Chat, Settings, and the floating button ================= */
  F.addTool({ id: "aichat", group: "ai", icon: "✨", label: "Assistant", blurb: "Chat with the AI: it sees what you are doing, reads your files, makes PDFs, pictures and videos, uses every tool, and can add new tools to Fathom.", el: F.makeView("aichat", false), build: (sec) => {
    const view = F.standardView("aichat", { files: false, output: false });
    sec.replaceWith(view.sec); F.tools.find((x) => x.id === "aichat").el = view.sec; view.sec.classList.add("on", "ai-view");
    if (!chat) { chat = buildChat(false); instances.push(chat); fillWelcome(chat); }
    view.main.append(chat.root);
    api("/api/ai/settings").then((s) => { chat.approval.value = s.approval; }).catch(() => {});
    if (ai.sid && !ai.restored) { ai.restored = true; openChat(ai.sid); }
  }, onShow: () => { if (chat) { mountTab(); } } });
  function mountTab() { const t = F.tools.find((x) => x.id === "aichat"); if (t && t.el && chat && chat.root.parentElement !== t.el.querySelector(".main")) t.el.querySelector(".main").append(chat.root); drawer.classList.remove("open"); setTimeout(() => { const s = chat.root.querySelector(".ai-scroll"); s.scrollTop = s.scrollHeight; }, 0); }

  const drawer = h("aside", { class: "ai-drawer", "aria-label": "Assistant" }, h("div", { class: "ai-drawer-bar" }, h("b", { text: "✨ Ask Fathom" }), h("span", { style: "flex:1" }), h("button", { class: "btn small", tip: "Opens the assistant as a full page.", onclick: () => F.show("aichat") }, "Full page"), h("button", { class: "btn small", onclick: () => toggleDrawer(false), "aria-label": "Close" }, "✕")), h("div", { class: "ai-drawer-body" }));
  const fab = h("button", { class: "ai-fab", tip: "Ask the assistant. It can see what you are doing right now and help with it.", onclick: () => toggleDrawer() }, "✨ Ask Fathom");
  function toggleDrawer(on) {
    const open = on === undefined ? !drawer.classList.contains("open") : on;
    if (open) {
      if (!chat) { chat = buildChat(false); instances.push(chat); fillWelcome(chat); if (ai.sid && !ai.restored) { ai.restored = true; openChat(ai.sid); } }
      drawer.querySelector(".ai-drawer-body").append(chat.root); schedule();
      api("/api/ai/settings").then((s) => { chat.approval.value = s.approval; }).catch(() => {});
      setTimeout(() => chat.ta.focus(), 50);
    }
    drawer.classList.toggle("open", open); fab.hidden = open; document.body.classList.toggle("ai-docked", open && ai.docked);
  }
  function updateFab() { const onTab = F.currentTool && (F.currentTool.id === "aichat"); fab.hidden = !!onTab || drawer.classList.contains("open"); fab.classList.toggle("busy", ai.running); }
  document.body.append(drawer, fab);
  // ---- drag the left edge to make the side chat wider or narrower; "Dock" pushes the app aside instead of covering it
  const MINW = 320, maxW = () => Math.max(MINW, window.innerWidth - 120);
  const grip = h("div", { class: "ai-grip", role: "separator", "aria-orientation": "vertical", "aria-label": "Drag to change the width of the assistant", tabindex: "0" });
  F.tip(grip, "Drag to make the assistant wider or narrower. Double-click to reset. Arrow keys also work when selected.");
  drawer.append(grip);
  const dock = h("button", { class: "btn small", onclick: () => setDock(!ai.docked) }, "Dock");
  F.tip(dock, "Dock: the assistant takes its own strip on the right and the app moves over, instead of covering it.");
  drawer.querySelector(".ai-drawer-bar").insertBefore(dock, drawer.querySelector(".ai-drawer-bar button"));
  ai.dw = Math.min(maxW(), Math.max(MINW, +F.load("ai.dw", 480) || 480)); ai.docked = !!F.load("ai.dock", false);
  function applyW() { drawer.style.width = Math.min(ai.dw, window.innerWidth) + "px"; document.documentElement.style.setProperty("--ai-dw", Math.min(ai.dw, window.innerWidth) + "px"); }
  function setDock(on) { ai.docked = on; F.save("ai.dock", on); dock.classList.toggle("on", on); document.body.classList.toggle("ai-docked", on && drawer.classList.contains("open")); }
  function setW(w, save) { ai.dw = Math.round(Math.min(maxW(), Math.max(MINW, w))); applyW(); if (save) F.save("ai.dw", ai.dw); }
  grip.addEventListener("pointerdown", (e) => { e.preventDefault(); grip.setPointerCapture(e.pointerId); document.body.classList.add("ai-resizing"); });
  grip.addEventListener("pointermove", (e) => { if (grip.hasPointerCapture(e.pointerId)) setW(window.innerWidth - e.clientX); });
  const endDrag = (e) => { if (grip.hasPointerCapture && grip.hasPointerCapture(e.pointerId)) grip.releasePointerCapture(e.pointerId); document.body.classList.remove("ai-resizing"); F.save("ai.dw", ai.dw); };
  grip.addEventListener("pointerup", endDrag); grip.addEventListener("pointercancel", endDrag);
  grip.addEventListener("dblclick", () => setW(480, true));
  grip.addEventListener("keydown", (e) => { if (e.key === "ArrowLeft") { e.preventDefault(); setW(ai.dw + 32, true); } else if (e.key === "ArrowRight") { e.preventDefault(); setW(ai.dw - 32, true); } else if (e.key === "Home") setW(480, true); });
  window.addEventListener("resize", () => setW(ai.dw));
  applyW(); setDock(ai.docked);
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") { e.preventDefault(); if (F.currentTool && F.currentTool.id === "aichat") chat && chat.ta.focus(); else toggleDrawer(); } });

  /* ---------- settings ---------- */
  F.addTool({ id: "aisettings", group: "ai", icon: "⚙️", label: "Settings", blurb: "Choose the AI model, add your key, set up picture-making and voice, and decide when the assistant must ask you first.", el: F.makeView("aisettings", false), build: async (sec) => {
    const view = F.standardView("aisettings", { files: false, output: false });
    sec.replaceWith(view.sec); F.tools.find((x) => x.id === "aisettings").el = view.sec; view.sec.classList.add("on");
    const main = view.main; main.append(F.titleBlock("Assistant settings", "Your keys are stored on this PC only, protected with Windows' own data protection. They are never shown again and never sent anywhere except to the service you choose."));
    let s = await api("/api/ai/settings");
    const keyNote = (n) => (s.has_key[n] ? "A key is saved. Leave empty to keep it, type a new one to replace it, or type - to remove it." : "No key saved yet.");
    const brain = F.form([
      { id: "provider", type: "select", label: "Which AI?", value: s.provider, options: [{ v: "anthropic", l: "Claude (Anthropic)", tip: "The strongest choice for this assistant. Needs an API key from console.anthropic.com." }, { v: "openai", l: "OpenAI or compatible", tip: "OpenAI, or any service that speaks the same language (OpenRouter, Groq, LM Studio, …)." }, { v: "ollama", l: "On my own PC (Ollama)", tip: "Free and private. Install Ollama from ollama.com and pull a model that can use tools and see pictures." }], tip: "Which AI does the thinking." },
      { id: "model", type: "text", label: "Model name", value: s.models[s.provider], tip: "The exact model name. Claude: claude-sonnet-5-5 or claude-opus-5-5. OpenAI: gpt-4.1. Ollama: qwen3-vl:4b-instruct (default, fast), qwen3-vl:8b-instruct (better, 6 GB), qwen3-vl:4b-thinking (slower: it thinks first), gemma3, …" },
      { id: "base", type: "text", label: "Service address", value: s.base_urls[s.provider], tip: "Where the service lives. Leave as it is unless you use another service or a different port." },
      { id: "key", type: "password", label: "Key", value: "", placeholder: s.has_key[s.provider] ? "saved ✓" : "paste your key here", tip: keyNote(s.provider) + "\nFor Ollama no key is needed." },
      { id: "approval", type: "select", label: "Ask me first…", value: s.approval, options: [{ v: "ask_changes", l: "before it changes things (recommended)", tip: "Reading and making new files is automatic. Changing your files, running code and adding tools asks you first." }, { v: "ask_all", l: "before everything", tip: "Asks even before reading files." }, { v: "never", l: "never (it just does it)", tip: "Fastest, but it can change and delete things without asking. Your originals are still backed up before overwriting." }], tip: "How careful the assistant is." },
      { id: "max_steps", type: "number", label: "Most steps per message", value: s.max_steps, min: 5, max: 400, tip: "How many actions it may take for one request before it stops and waits. 40 is plenty for most jobs." },
      { id: "web", type: "check", label: "Allow web search and reading web pages", value: s.web, tip: "Lets the assistant look things up online." },
      { id: "output_dir", type: "text", label: "Where it saves new files", value: s.output_dir, placeholder: "Documents\\Fathom AI", tip: "Leave empty for Documents\\Fathom AI." },
    ], (v) => { if (v.provider !== curProv) { curProv = v.provider; brain.set("model", s.models[v.provider]); brain.set("base", s.base_urls[v.provider]); brain.set("key", ""); } });
    let curProv = s.provider;
    const imgf = F.form([
      { id: "ip", type: "select", label: "Picture service", value: s.image.provider, options: [{ v: "none", l: "None (it draws posters and diagrams itself)", tip: "The assistant can still design posters, cards and diagrams with exact text, without any service." }, { v: "openai", l: "OpenAI pictures", tip: "Photo-style and artistic pictures from a description. Needs a key." }, { v: "a1111", l: "Stable Diffusion on my PC", tip: "A local Stable Diffusion server (AUTOMATIC1111 / Forge) running with --api. Free and private." }], tip: "Where pictures made from a description come from." },
      { id: "im", type: "text", label: "Picture model", value: s.image.model, show: (v) => v.ip === "openai", tip: "For example gpt-image-1." },
      { id: "iu", type: "text", label: "Address", value: s.image.base_url, show: (v) => v.ip !== "none", tip: "OpenAI: https://api.openai.com/v1.  Stable Diffusion: http://127.0.0.1:7860" },
      { id: "isz", type: "text", label: "Size", value: s.image.size, show: (v) => v.ip !== "none", tip: "For example 1024x1024 or 1536x1024." },
      { id: "ik", type: "password", label: "Picture key", value: "", show: (v) => v.ip === "openai", placeholder: s.has_key.image ? "saved ✓" : "same as the OpenAI key if empty", tip: "Leave empty to use your OpenAI key. Type - to remove." },
    ]);
    const voice = F.form([
      { id: "tp", type: "select", label: "Voice", value: s.tts.provider, options: [{ v: "system", l: "Windows voices (free, offline)", tip: "Uses the voices built into Windows." }, { v: "openai", l: "OpenAI voices", tip: "More natural voices. Needs a key." }], tip: "Used when the assistant reads text aloud or narrates a video." },
      { id: "tv", type: "text", label: "Voice name", value: s.tts.voice, placeholder: "e.g. Microsoft Zira Desktop, or alloy", tip: "Leave empty for the default voice." },
      { id: "tk", type: "password", label: "Voice key", value: "", show: (v) => v.tp === "openai", placeholder: s.has_key.tts ? "saved ✓" : "same as the OpenAI key if empty", tip: "Leave empty to use your OpenAI key." },
    ]);
    const hwHost = h("div"); const hwStatus = h("p", { class: "hint" });
    const hwInstall = h("button", { class: "btn small", tip: "Downloads the offline handwriting model (a few GB) and the engine it needs. Needs internet once. Afterwards nothing leaves your PC.", onclick: async () => { try { hwInstall.disabled = true; const r = await post("/api/handwriting/install", {}); const p = new F.JobPanel(hwHost, { noun: "step", summary: false, onDone: () => { hwInstall.disabled = false; hwRefresh(); } }); p.start(r.job); } catch (e) { hwInstall.disabled = false; F.toast(e.message); } } }, "Install the offline reader");
    const hwRefresh = async () => { try { const i = await api("/api/handwriting/info"); hwStatus.textContent = `AI reader: ${i.ai ? "ready" : "needs a key"}.  Offline reader: ${i.trocr ? "installed" : "not installed"}.  Currently used: ${({ ai: "AI", trocr: "offline reader", enhanced: "basic reader" })[i.chosen]}.`; } catch { /* ignore */ } };
    hwRefresh();
    const hw = F.form([{ id: "hw", type: "select", label: "Reading handwriting", value: s.handwriting, options: [{ v: "auto", l: "Choose the best available", tip: "Uses the AI's eyes when a key is set, otherwise the on-PC reader." }, { v: "ai", l: "Use the AI (best for messy writing)", tip: "Sends the page picture to your chosen AI model to read." }, { v: "trocr", l: "On my PC only (nothing leaves the PC)", tip: "Uses an offline handwriting model if it is installed." }, { v: "off", l: "Off", tip: "Only printed text is read." }], tip: "How handwriting in pictures and scans is read, in Search and the Handwriting tool." }]);
    const card = (title, sub, ...kids) => h("div", { class: "card-box" }, h("h3", { text: title }), sub ? h("p", { class: "hint", text: sub }) : null, ...kids);
    const status = h("p", { class: "hint" });
    const testBtn = h("button", { class: "btn", tip: "Sends a tiny test message to check the model and key work.", onclick: async () => { status.textContent = "Testing…"; try { const r = await post("/api/ai/test"); status.textContent = r.ok ? `✓ Works. ${r.reply || ""}` : "✗ " + r.error; } catch (e) { status.textContent = "✗ " + e.message; } } }, "Test the connection");
    const saveBtn = h("button", { class: "primary", tip: "Saves everything on this page.", onclick: async () => {
      const b = brain.values(), i = imgf.values(), t = voice.values(), w = hw.values();
      const keys = {}; const k = (name, v) => { if (v && v.trim()) keys[name] = v.trim() === "-" ? "" : v.trim(); };
      k(b.provider, b.key); k("image", i.ik); k("tts", t.tk);
      const settings = { provider: b.provider, models: { ...s.models, [b.provider]: b.model.trim() }, base_urls: { ...s.base_urls, [b.provider]: b.base.trim() }, approval: b.approval, max_steps: +b.max_steps || 40, web: !!b.web, output_dir: b.output_dir.trim(),
        image: { provider: i.ip, model: i.im || s.image.model, base_url: i.iu || s.image.base_url, size: i.isz || s.image.size }, tts: { ...s.tts, provider: t.tp, voice: t.tv }, handwriting: w.hw };
      try { s = await post("/api/ai/settings", { settings, keys }); F.toast("Saved"); status.textContent = "Saved."; brain.set("key", ""); imgf.set("ik", ""); voice.set("tk", ""); } catch (e) { F.toast(e.message); }
    } }, "Save settings");
    const memHost = h("div");
    const drawMem = () => { memHost.replaceChildren(...(s.memory.length ? s.memory.map((m, i) => h("div", { class: "ai-hist" }, h("span", { text: m }), h("button", { class: "x", tip: "Makes the assistant forget this.", "aria-label": "Forget", onclick: async () => { s = await post("/api/ai/settings", { settings: { memory: s.memory.filter((_, j) => j !== i) } }); drawMem(); } }, "×"))) : [h("p", { class: "hint", text: "Nothing yet. Tell the assistant “remember that …” and it shows up here." })])); };
    drawMem();
    main.append(card("The AI", "Claude is recommended. Any one of these works.", brain.el), card("Pictures", "Optional. Without a service the assistant still designs posters, cards, covers and diagrams itself.", imgf.el), card("Voice", "Used for reading aloud and narrating videos.", voice.el), card("Handwriting", "Used by Search (Also read handwriting) and the Read handwriting tool.", hw.el, hwStatus, hwInstall, hwHost),
      h("div", { class: "row", style: "gap:10px;margin:14px 0;align-items:center" }, saveBtn, testBtn, status), ...ai.settingsCards.map((fn) => fn()), card("What the assistant remembers", "Short notes it keeps between chats.", memHost));
  } });

  /* ================= My tools: features added by the assistant ================= */
  const mineTools = new Map();
  F.addTool({ id: "mytools", group: "mine", icon: "🧰", label: "My tools", blurb: "Tools you or the assistant added to Fathom. Describe a feature and the assistant builds it here.", el: F.makeView("mytools", false), build: (sec) => {
    const view = F.standardView("mytools", { files: false, output: false });
    sec.replaceWith(view.sec); F.tools.find((x) => x.id === "mytools").el = view.sec; view.sec.classList.add("on");
    const main = view.main; main.append(F.titleBlock("My tools", "Missing a feature? Describe it and the assistant builds it as a real tool inside Fathom, with its own page, options and results. It shows up here and in the bar above."));
    const ta = h("textarea", { rows: 3, placeholder: "Describe the tool you want… e.g. “A tool that renames my photos by the date taken and puts them in folders by month.”", tip: "Say what the tool should do, what files it works on, and any options you want to choose each time.", style: "width:100%" });
    main.append(h("div", { class: "card-box" }, h("h3", { text: "Build a new tool" }), ta, h("div", { class: "row", style: "margin-top:10px;gap:10px" }, h("button", { class: "primary", tip: "Sends your idea to the assistant, which writes the tool, tests it, and adds it to Fathom.", onclick: () => { if (!ta.value.trim()) return F.toast("Describe the tool first."); F.askAssistant("Add a new tool to Fathom (use create_tool, then test it with a real file): " + ta.value.trim()); setTimeout(() => submit(), 80); } }, "Build it ✨"), h("span", { class: "hint", text: "You will be asked before anything is added." }))));
    const host = h("div"); main.append(host); view.draw = host;
    drawMine();
  }, onShow: () => drawMine() });
  function drawMine() {
    const t = F.tools.find((x) => x.id === "mytools"); const host = t && t.el && t.el.querySelector(".main > div:last-child"); if (!host || !host.parentElement) return;
    host.replaceChildren();
    if (!mineTools.size) { host.append(h("p", { class: "hint", text: "No added tools yet. They will appear here." })); return; }
    host.append(h("div", { class: "homegrid" }, [...mineTools.values()].map((m) => h("div", { class: "homecard static" }, h("b", { text: m.icon + "  " + m.label }), h("span", { text: m.blurb }),
      h("div", { class: "row", style: "gap:6px;margin-top:8px;flex-wrap:wrap" }, h("button", { class: "btn small", tip: "Opens the tool.", onclick: () => F.show("mine-" + m.id) }, "Open"),
        h("button", { class: "btn small", tip: "Asks the assistant to change or improve this tool.", onclick: () => F.askAssistant(`Improve my tool "${m.label}" (id ${m.id}). Read it first with read_my_tool. What I want changed: `) }, "Improve with AI"),
        h("button", { class: "btn small danger", tip: "Removes this tool from Fathom.", onclick: async () => { if (!confirm(`Remove the tool "${m.label}"?`)) return; try { await post("/api/ai/plugins/delete", { id: m.id }); loadPlugins(); } catch (e) { F.toast(e.message); } } }, "Remove"))))));
  }
  function registerPlugin(m) {
    const id = "mine-" + m.id;
    const old = F.tools.findIndex((x) => x.id === id);
    if (old >= 0) { const o = F.tools[old]; if (o.el && o.el.remove) o.el.remove(); F.tools.splice(old, 1); }
    F.addTool({ id, group: "mine", icon: m.icon, label: m.label, blurb: m.blurb, el: F.makeView(id), build: (sec) => {
      const view = F.standardView(id, { output: true, files: m.needs_files !== false });
      sec.replaceWith(view.sec); F.tools.find((x) => x.id === id).el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock(m.title || m.label, m.sub || m.blurb));
      const form = F.form(m.fields || []); if ((m.fields || []).length) main.append(h("div", { class: "card-box" }, form.el));
      const go = h("button", { class: "primary", tip: m.blurb }, m.run || "Start"); const host = h("div");
      const panel = new F.JobPanel(host, { noun: m.mode === "each" ? "file" : "run", onDone: () => { go.disabled = false; }, renderItem: (r) => { const el = F.defaultItem(r); const tb = r.extra && r.extra.table; if (tb && tb.length) { const keys = Object.keys(tb[0]); el.append(h("div", { class: "tbl-wrap", style: "width:100%" }, h("table", { class: "tbl" }, h("tr", {}, keys.map((k) => h("th", { text: k }))), ...tb.slice(0, 40).map((row) => h("tr", {}, keys.map((k) => h("td", { text: String(row[k] ?? "") }))))))); } return el; } });
      main.append(h("div", { class: "row", style: "margin-top:16px;gap:10px" }, go, h("button", { class: "btn", tip: "Asks the assistant to change this tool.", onclick: () => F.askAssistant(`Improve my tool "${m.label}" (id ${m.id}). Read it first with read_my_tool. What I want changed: `) }, "Improve with AI")), host);
      go.onclick = async () => { if (m.needs_files !== false && !F.needFiles()) return; try { go.disabled = true; const r = await post("/api/ai/plugins/run", { id: m.id, paths: F.state.sources, recursive: true, output: F.outputBody(), inputs: form.values() }); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); } };
    } });
  }
  async function loadPlugins(open) {
    let r; try { r = await api("/api/ai/plugins"); } catch { return; }
    const ids = new Set(r.tools.map((m) => m.id));
    for (const old of [...mineTools.keys()]) if (!ids.has(old)) { mineTools.delete(old); const i = F.tools.findIndex((x) => x.id === "mine-" + old); if (i >= 0) { F.tools[i].el && F.tools[i].el.remove && F.tools[i].el.remove(); F.tools.splice(i, 1); } }
    for (const m of r.tools) { const prev = mineTools.get(m.id); if (!prev || prev.updated !== m.updated) { registerPlugin(m); } mineTools.set(m.id, m); }
    ai.pluginIds = [...mineTools.keys()];
    F.buildNav(); if (F.currentTool) { const g = F.currentTool.group; document.querySelectorAll("#groups button").forEach((b) => b.setAttribute("aria-selected", b.dataset.g === g)); }
    const cur = F.currentTool; if (cur && cur.group === "mine") F.show(open ? "mine-" + open : cur.id.startsWith("mine-") && !mineTools.has(cur.id.slice(5)) ? "mytools" : cur.id);
    drawMine(); schedule();
    if (open && mineTools.has(open)) F.toast(`New tool added: ${mineTools.get(open).label}`);
  }
  F.onBoot = F.onBoot || []; F.onBoot.push(() => { loadPlugins(); updateFab(); schedule(); });
})();
