/* Activity & Undo: everything Fathom changed on disk, with a one-click undo for each change. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  const when = (t) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const show0 = F.show;
  F.show = function (id, ...a) { const r = show0.call(this, id, ...a); if (id === "history") { const t = F.tools.find((x) => x.id === "history"); setTimeout(() => t && t.el && t.el._load && t.el._load(), 50); } return r; };
  F.addTool({ id: "history", group: "tidy", icon: "↩️", label: "Activity & Undo", blurb: "Everything Fathom changed on your files, newest first. Take any change back with one click.", el: F.makeView("history", false), build: (sec) => {
    const view = F.standardView("history", { files: false, output: false });
    sec.replaceWith(view.sec); F.tools.find((x) => x.id === "history").el = view.sec; view.sec.classList.add("on");
    const main = view.main;
    main.append(F.titleBlock("Activity & Undo", "Every change Fathom made to your files. Undo puts originals back, moves renamed files back, and sends files Fathom made to the Recycle Bin. A file you edited yourself afterwards is never touched."));
    const q = h("input", { type: "search", placeholder: "Search the list (a file name, a tool…)", class: "grow" });
    F.tip(q, "Type part of a file name or tool name to narrow the list.");
    const info = h("div", { class: "muted", style: "margin:6px 0" });
    const list = h("div", { class: "hist-list" });
    const keep = h("select", {}, ...[["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["365", "1 year"], ["0", "Forever"]].map(([v, t]) => h("option", { value: v, text: t })));
    F.tip(keep, "How long Fathom keeps the safety copies of originals it replaced. After that the change stays in the list but can no longer be undone for those files.");
    const on = h("input", { type: "checkbox" });
    F.tip(on.closest("label") || on, "Off: Fathom stops writing this list and stops keeping safety copies. Replaced originals still go to the Recycle Bin.");
    const clear = h("button", { class: "btn", text: "Clear the list", onclick: async () => { if (!confirm("Clear the whole list and delete the safety copies? Undo will no longer be possible for these changes.")) return; await api("/api/history/settings", { method: "POST", body: { clear: true } }); load(); } });
    F.tip(clear, "Forgets every change and deletes the safety copies of replaced originals to free room. Your files are not touched.");
    main.append(h("div", { class: "row", style: "gap:8px;align-items:center;flex-wrap:wrap" }, q, h("label", {}, "Keep safety copies for ", keep), h("label", {}, on, " Record changes"), clear), info, list);
    const showResult = (r) => {
      const lines = [...r.done.map((d) => `✔ ${d.what}: ${d.path}`), ...r.kept.map((d) => `• ${d.why} (${d.path})`), ...r.failed.map((d) => `✘ ${d.path}: ${d.error}`)];
      F.toast(`Undone: ${r.done.length} item${r.done.length === 1 ? "" : "s"}` + (r.kept.length ? `, ${r.kept.length} left alone` : "") + (r.failed.length ? `, ${r.failed.length} failed` : ""));
      if (lines.length) alert(r.title + "\n\n" + lines.slice(0, 40).join("\n"));
    };
    const row = (e) => {
      const files = [...e.made.map((m) => m.path), ...e.removed.map((m) => m.orig), ...e.moves.map((m) => m.to)];
      const det = h("div", { class: "hist-det", hidden: true }, ...files.slice(0, 60).map((p) => h("div", { class: "hist-file" }, h("span", { text: p }), h("button", { class: "lnk", text: "Show", title: "Show this file in its folder", onclick: () => F.reveal(p) }))), e.more ? h("div", { class: "muted", text: `…and ${e.more} more` }) : "");
      const undo = h("button", { class: "btn", text: e.undone ? "Undone" : "Undo", disabled: !e.can_undo, onclick: async () => {
        undo.disabled = true;
        try { showResult(await api("/api/history/undo", { method: "POST", body: { id: e.id } })); } catch (x) { F.toast(x.message); }
        load();
      } });
      F.tip(undo, e.can_undo ? "Take this change back: originals return, renamed files return, files Fathom made go to the Recycle Bin." : e.undone ? "This change was already taken back." : "Nothing in this change can be restored (no safety copy was kept).");
      const more = h("button", { class: "lnk", text: `${files.length + e.more} file${files.length + e.more === 1 ? "" : "s"}`, onclick: () => { det.hidden = !det.hidden; } });
      F.tip(more, "Show or hide the files involved.");
      return h("div", { class: "hist-row" + (e.undone ? " done" : "") }, h("div", { class: "hist-top" }, h("b", { text: e.title }), h("span", { class: "muted", text: when(e.time) }), h("span", { class: "grow", text: e.what }), more, undo), det);
    };
    let t;
    const load = async () => {
      let d; try { d = await api("/api/history?q=" + encodeURIComponent(q.value)); } catch (x) { info.textContent = x.message; return; }
      keep.value = String(d.settings.keep_days); on.checked = d.settings.enabled;
      info.textContent = d.items.length ? `${d.items.length} shown of ${d.total}. Safety copies use ${F.fmtBytes(d.copies_bytes)}.` : "Nothing yet. Changes Fathom makes will appear here.";
      list.replaceChildren(...d.items.map(row));
    };
    q.oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
    keep.onchange = async () => { await api("/api/history/settings", { method: "POST", body: { keep_days: +keep.value } }); load(); };
    on.onchange = async () => { await api("/api/history/settings", { method: "POST", body: { enabled: on.checked } }); load(); };
    load(); view.sec._load = load;
  } });
})();
