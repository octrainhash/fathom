/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* Server mode: when Fathom runs on another computer (or in Docker) and you use it from a phone, tablet or browser,
   "Add files" browses the server's folders, files from THIS device are uploaded, and "Show/Open" downloads. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  F.ready = api("/api/info").then((i) => { F.info = i; document.documentElement.dataset.serve = i.serve ? "1" : "0"; return i; }).catch(() => (F.info = { serve: false }));
  const isServe = () => !!(F.info && F.info.serve);
  F.isServe = isServe;
  const fmt = (n) => (n ? F.fmtBytes(n) : "");

  F.uploadFiles = async (files, onProgress) => {
    const out = [], CH = 1024 * 1024;
    for (const f of [...files]) {
      const id = Math.random().toString(36).slice(2) + Date.now().toString(36);
      const n = Math.max(1, Math.ceil(f.size / CH));
      for (let i = 0; i < n; i++) {
        const data = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f.slice(i * CH, (i + 1) * CH)); });
        const r = await api("/api/fs/upload", { method: "POST", body: { id, name: f.name, index: i, last: i === n - 1, data } });
        onProgress && onProgress(f.name, (i + 1) / n);
        if (i === n - 1) out.push(r.path);
      }
    }
    return out;
  };

  F.browse = (kind) => new Promise((resolve) => {
    const wantDir = kind === "folder" || kind === "outfolder", multi = kind === "files" || kind === "pictures";
    const chosen = new Set(); let cur = F.load("browse.path", ""), showHidden = false;
    const path = h("input", { type: "text", class: "grow", "aria-label": "Folder path", spellcheck: "false" }); F.tip(path, "The folder you are looking at. Type or paste a path and press Enter to go there.");
    const list = h("div", { class: "br-list" }), msg = h("span", { class: "muted" });
    const up = h("button", { class: "btn small", onclick: () => go(parent) }, "⬆ Up"); F.tip(up, "Go to the folder above this one.");
    const home = h("button", { class: "btn small", onclick: () => go("") }, "🏠 Places"); F.tip(home, "Back to the list of drives and starting places.");
    const hid = h("label", { class: "muted" }, h("input", { type: "checkbox", onchange: (e) => { showHidden = e.target.checked; go(cur); } }), " hidden");
    const ok = h("button", { class: "primary", onclick: () => finish(wantDir ? [cur] : [...chosen]) }, wantDir ? "Choose this folder" : "Add selected"); F.tip(ok, wantDir ? "Use the folder you are looking at." : "Add the ticked files.");
    const cancel = h("button", { class: "btn", onclick: () => finish([]) }, "Cancel");
    const file = h("input", { type: "file", multiple: true, hidden: true, onchange: async () => { if (!file.files.length) return; msg.textContent = "Uploading…"; try { const p = await F.uploadFiles(file.files, (n, f) => { msg.textContent = `Uploading ${n} ${Math.round(f * 100)}%`; }); finish(p); } catch (e) { msg.textContent = e.message; } } });
    const upBtn = h("button", { class: "btn small", onclick: () => file.click(), hidden: wantDir }, "📤 Upload from this device"); F.tip(upBtn, "Send files from the phone, tablet or computer you are using to the Fathom computer, then work on them.");
    const box = h("div", { class: "modal browse" }, h("h3", { text: wantDir ? "Choose a folder on the Fathom computer" : "Choose files on the Fathom computer" }),
      h("div", { class: "row", style: "gap:6px;align-items:center;flex-wrap:wrap" }, home, up, path, hid), list, h("div", { class: "row", style: "gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px" }, upBtn, file, msg, h("span", { style: "flex:1" }), cancel, ok));
    const back = h("div", { class: "modal-back", role: "dialog", "aria-modal": "true", style: "position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:200" }, box);
    box.style.cssText = "background:var(--bg2,#fff);color:inherit;border-radius:16px;padding:18px;width:min(720px,96vw);max-height:90vh;display:flex;flex-direction:column";
    const finish = (r) => { back.remove(); F.save("browse.path", cur); resolve(r); };
    let parent = "";
    async function go(p) {
      msg.textContent = "";
      try {
        const r = await api("/api/fs/list", { method: "POST", body: { path: p, show_hidden: showHidden } });
        cur = r.path; parent = r.parent; path.value = r.path; up.disabled = !r.path; ok.disabled = wantDir && !r.path;
        list.replaceChildren(...r.entries.map((e) => {
          const row = h("div", { class: "br-row" + (e.dir ? " dir" : "") });
          if (!e.dir && multi) { const c = h("input", { type: "checkbox", checked: chosen.has(e.path), onclick: (ev) => { ev.stopPropagation(); c.checked ? chosen.add(e.path) : chosen.delete(e.path); ok.textContent = chosen.size ? `Add ${chosen.size} selected` : "Add selected"; } }); row.append(c); }
          row.append(h("span", { class: "ic", text: e.dir ? "📁" : "📄" }), h("span", { class: "nm", text: e.name }), h("span", { class: "muted", text: fmt(e.size) }));
          row.onclick = () => { if (e.dir) go(e.path); else if (!wantDir && !multi) finish([e.path]); else if (multi) { chosen.has(e.path) ? chosen.delete(e.path) : chosen.add(e.path); const c = row.querySelector("input"); if (c) c.checked = chosen.has(e.path); ok.textContent = chosen.size ? `Add ${chosen.size} selected` : "Add selected"; } };
          if (e.dir && !wantDir) { const addDir = h("button", { class: "lnk", text: "add folder", onclick: (ev) => { ev.stopPropagation(); finish([e.path]); } }); F.tip(addDir, "Add this whole folder."); row.append(addDir); }
          return row;
        }));
        if (!r.entries.length) list.append(h("p", { class: "muted", text: "Nothing here." }));
      } catch (e) { msg.textContent = e.message; if (p) go(""); }
    }
    path.addEventListener("keydown", (e) => { if (e.key === "Enter") go(path.value.trim()); });
    document.body.append(back); go(cur);
  });

  // ---- make the shared tray use it
  const pick0 = F.pickOne;
  F.pickOne = async (kind) => { await F.ready; if (!isServe()) return pick0(kind); return (await F.browse(kind))[0] || ""; };
  F.pickPaths = async (kind) => { await F.ready; if (isServe()) return F.browse(kind); return (await api("/api/pick", { method: "POST", body: { kind } })).paths || []; };
  const download = (p) => { const a = document.createElement("a"); a.href = `/api/fs/download?path=${encodeURIComponent(p)}&t=${encodeURIComponent(F.TOKEN)}`; a.download = ""; document.body.append(a); a.click(); a.remove(); };
  const reveal0 = F.reveal, open0 = F.openFile;
  F.reveal = (p) => (isServe() ? download(p) : reveal0(p));
  F.openFile = (p) => (isServe() ? download(p) : open0(p));
  F.downloadFile = download;
})();
