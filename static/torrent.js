/* Torrent group: Downloads (client), Make a torrent, Torrent info, Download links. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  const post = (p, b) => api(p, { method: "POST", body: b });
  const reg = (t, build) => F.addTool({ ...t, el: F.makeView(t.id), build: (sec) => { const v = F.standardView(t.id, { files: !!t.files, output: !!t.output, hint: t.hint }); sec.replaceWith(v.sec); F.tools.find((x) => x.id === t.id).el = v.sec; v.sec.classList.add("on"); build(v.main, v); } });
  const RIGHTS = "Fathom is a plain BitTorrent client. It does not search for or point at any content. Only download and share files you have the right to, such as open-source software, public-domain works, your own files and things you have permission to use.";
  const speed = (b) => (b ? F.fmtBytes(b) + "/s" : "–");
  const eta = (s) => (!s ? "" : s < 90 ? s + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h");
  function runBar(main, label, tipText, start, panelOpts = {}) {
    const go = h("button", { class: "primary", tip: tipText }, label); const host = h("div");
    const panel = new F.JobPanel(host, { ...panelOpts, onDone: (s, items) => { go.disabled = false; panelOpts.onDone && panelOpts.onDone(s, items); } });
    main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
    go.onclick = async () => { try { go.disabled = true; const r = await start(); if (r) panel.start(r.job); else go.disabled = false; } catch (e) { go.disabled = false; F.toast(e.message); } };
    return { go, panel, host };
  }
  const folderRow = (key, label) => {
    const box = h("input", { type: "text", value: F.load(key, ""), placeholder: "Choose a folder…", spellcheck: "false", style: "flex:1;min-width:220px", tip: "The folder the downloads are saved into." });
    box.addEventListener("input", () => F.save(key, box.value));
    const btn = h("button", { class: "btn small", tip: "Opens a window to choose the folder.", onclick: async () => { const p = await F.pickOne("outfolder"); if (p) { box.value = p; F.save(key, p); } } }, "Browse…");
    return { el: h("div", { class: "field" }, h("div", { class: "lab", text: label }), h("div", { style: "display:flex;gap:8px" }, box, btn)), get: () => box.value.trim() };
  };

  // ================================================================== client
  reg({ id: "downloads", group: "torrent", icon: "⬇️", label: "Downloads", blurb: "Download and share files with BitTorrent: paste a magnet link or open a .torrent file, watch the speed, pause, choose which files to take.", files: false, output: false }, (main) => {
    main.append(F.titleBlock("Torrent downloads", "Paste a magnet link or open a .torrent file. Downloads keep going in the background and pick up again when you reopen Fathom. " + RIGHTS));
    const unavailable = h("div", { class: "warnbox", hidden: true });
    const magnet = h("input", { type: "text", placeholder: "magnet:?xt=urn:btih:…", spellcheck: "false", style: "flex:1;min-width:240px", tip: "Paste a magnet link here." });
    const save = folderRow("torsave", "Download into");
    const seq = h("input", { type: "checkbox" });
    const addMagnet = async (src) => { try { await post("/api/torrent/add", { source: src, save: save.get(), value: seq.checked }); magnet.value = ""; poll(); } catch (e) { F.toast(e.message); } };
    const add = h("div", { class: "card-box" }, h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, magnet,
      h("button", { class: "primary", tip: "Starts the download from the magnet link.", onclick: () => addMagnet(magnet.value) }, "Add link"),
      h("button", { class: "btn", tip: "Choose a .torrent file from this computer.", onclick: async () => { const p = await F.pickOne("files"); if (p) addMagnet(p); } }, "Open .torrent file…")),
      save.el, h("label", { tip: "On: pieces are fetched in order from the start, so a video can be watched while it downloads (a little slower overall).\nOff: the fastest order is used." }, seq, "Download in order (for watching while it downloads)"));
    const dl = h("input", { type: "number", min: 0, value: F.load("tordown", 0), style: "width:90px", tip: "Fastest speed allowed for downloading, in KB per second. 0 means no limit." });
    const ul = h("input", { type: "number", min: 0, value: F.load("torup", 0), style: "width:90px", tip: "Fastest speed allowed for uploading to others, in KB per second. 0 means no limit." });
    const setLim = async () => { F.save("tordown", +dl.value); F.save("torup", +ul.value); try { await post("/api/torrent/limits", { down: +dl.value || 0, up: +ul.value || 0 }); F.toast("Speed limits set."); } catch (e) { F.toast(e.message); } };
    const bar = h("div", { class: "row", style: "margin-top:14px;gap:12px;flex-wrap:wrap" }, h("span", { class: "chip", id: "tor-totals", text: "–" }), h("span", { class: "sp" }), h("label", { tip: "Limit for downloading, KB per second." }, "Down limit (KB/s) ", dl), h("label", { tip: "Limit for uploading, KB per second." }, "Up limit (KB/s) ", ul), h("button", { class: "btn small", tip: "Applies the speed limits.", onclick: setLim }, "Set"));
    const list = h("div", { class: "torlist" });
    main.append(unavailable, add, bar, list);
    let timer = null; const open = new Set(); const fileBoxes = {};
    async function poll() {
      clearTimeout(timer);
      if (F.currentTool && F.currentTool.id !== "downloads") { timer = setTimeout(poll, 1500); return; }
      try {
        const r = await api("/api/torrent/status");
        unavailable.hidden = r.available; if (!r.available) { unavailable.textContent = r.why; list.replaceChildren(); return; }
        document.getElementById("tor-totals") && (document.getElementById("tor-totals").textContent = `↓ ${speed(r.down)}   ↑ ${speed(r.up)}   ·   ${r.items.length} torrent${r.items.length === 1 ? "" : "s"}`);
        if (!r.items.length) list.replaceChildren(h("p", { class: "hint", text: "Nothing here yet. Paste a magnet link above." }));
        else list.replaceChildren(...r.items.map(item));
      } catch (e) { list.replaceChildren(h("p", { class: "hint", text: e.message })); }
      timer = setTimeout(poll, 1500);
    }
    function item(t) {
      const act = (action, value) => async () => { try { await post("/api/torrent/act", { id: t.id, action, value }); poll(); } catch (e) { F.toast(e.message); } };
      const fill = h("i"); fill.style.width = Math.round(t.progress * 100) + "%";
      const files = h("div", { class: "torfiles", hidden: !open.has(t.id) });
      const loadFiles = async () => {
        try { const r = await api("/api/torrent/files?id=" + t.id); const boxes = r.files.map((f) => { const c = h("input", { type: "checkbox" }); c.checked = f.wanted; return [c, f]; });
          files.replaceChildren(...boxes.map(([c, f]) => h("label", { class: "tf", tip: "Tick the files you want. Unticked files are not downloaded." }, c, h("span", { text: f.path }), h("small", { text: F.fmtBytes(f.size) + (f.size ? "  " + Math.round(f.done / f.size * 100) + "%" : "") }))),
            h("button", { class: "btn small", tip: "Downloads only the ticked files.", onclick: async () => { const wanted = boxes.filter(([c]) => c.checked).map(([, f]) => f.index); try { await post("/api/torrent/act", { id: t.id, action: "files", value: wanted }); F.toast("Saved."); } catch (e) { F.toast(e.message); } } }, "Apply file choice")); }
        catch (e) { files.replaceChildren(h("p", { class: "hint", text: e.message })); }
      };
      if (open.has(t.id)) loadFiles();
      return h("div", { class: "tor" }, h("div", { class: "tor-head" }, h("b", { text: t.name }), h("span", { class: "chip", text: t.state })),
        h("div", { class: "bar" + (t.progress >= 1 ? " idle" : "") }, fill),
        h("div", { class: "tor-meta" }, h("span", { text: `${Math.round(t.progress * 100)}%  ·  ${F.fmtBytes(t.done)} of ${F.fmtBytes(t.size)}` }), h("span", { text: `↓ ${speed(t.down)}  ↑ ${speed(t.up)}` }), h("span", { text: `${t.peers} peers · ${t.seeds} seeds` }), t.eta ? h("span", { text: "about " + eta(t.eta) + " left" }) : null, h("span", { text: "ratio " + t.ratio })),
        h("div", { class: "row", style: "margin-top:8px;gap:6px;flex-wrap:wrap" },
          h("button", { class: "btn small", tip: t.paused ? "Carries on downloading." : "Stops for now. You can resume later.", onclick: act(t.paused ? "resume" : "pause") }, t.paused ? "Resume" : "Pause"),
          h("button", { class: "btn small", tip: "Choose which files inside the torrent to take.", onclick: () => { if (open.has(t.id)) open.delete(t.id); else open.add(t.id); files.hidden = !open.has(t.id); if (!files.hidden) loadFiles(); } }, "Files"),
          h("button", { class: "btn small", tip: "Opens the folder the files are saved in.", onclick: () => F.reveal(t.save) }, "Show folder"),
          h("button", { class: "btn small", tip: "Checks the downloaded files again for damage.", onclick: act("recheck") }, "Check files"),
          h("button", { class: "btn small", tip: "Takes it off the list but keeps the downloaded files.", onclick: act("remove") }, "Remove"),
          h("button", { class: "btn small danger", tip: "Takes it off the list AND deletes the downloaded files.", onclick: () => { if (confirm("Delete the downloaded files too?")) act("delete")(); } }, "Remove + delete files")), files);
    }
    poll();
  });

  // ================================================================== make a torrent
  reg({ id: "mktorrent", group: "torrent", icon: "🧲", label: "Make a torrent", blurb: "Turn a file or folder into a .torrent file and a magnet link, so others can download it from you.", files: true, output: true, hint: "Add the file or folder to share." }, (main) => {
    main.append(F.titleBlock("Make a torrent", "Add a file or a whole folder on the left. Fathom makes a .torrent file (and a magnet link you can copy). Then open the .torrent in 'Downloads' to start sharing it. " + RIGHTS));
    const form = F.form([
      { id: "trackers", type: "textarea", label: "Trackers (optional, one per line)", rows: 3, placeholder: "udp://tracker.opentrackr.org:1337/announce", tip: "Addresses of tracker servers that help others find you. You can leave this empty: the DHT network works without any, as long as the torrent is not private." },
      { id: "comment", type: "text", label: "Comment (optional)", tip: "A short note stored inside the torrent." },
      { id: "piece", type: "select", label: "Piece size", value: "0", options: [{ v: "0", l: "Automatic" }, { v: "64", l: "64 KB" }, { v: "256", l: "256 KB" }, { v: "1024", l: "1 MB" }, { v: "4096", l: "4 MB" }, { v: "16384", l: "16 MB" }], tip: "Torrents are split into pieces. Automatic picks a good size for the total. Smaller: finer sharing but a bigger .torrent file." },
      { id: "private", type: "check", label: "Private torrent", value: false, tip: "On: only the trackers you list are used, no DHT or peer sharing outside them. Needed for private trackers.\nOff: anyone with the link can join." }]);
    main.append(h("div", { class: "card-box" }, form.el));
    runBar(main, "Make torrent", "Creates one .torrent file for each item on the left.", async () => { if (!F.needFiles()) return null; const v = form.values(); return post("/api/torrent/make", { paths: F.state.sources, trackers: (v.trackers || "").split(/\r?\n/), comment: v.comment || "", private: v.private, piece_kb: +v.piece || 0, output: F.outputBody() }); },
      { noun: "torrent", renderItem: (r) => { const el = F.defaultItem(r); const m = r.extra && r.extra.magnet; if (m) el.querySelector(".acts").append(h("button", { class: "btn small", tip: "Copies the magnet link.", onclick: () => F.copy(m) }, "Copy magnet")); return el; } });
  });

  // ================================================================== torrent info
  reg({ id: "torinfo", group: "torrent", icon: "🔎", label: "Torrent info", blurb: "Open a .torrent file and see what is inside before downloading: files, size, trackers and the magnet link.", files: false, output: false }, (main) => {
    main.append(F.titleBlock("Torrent info", "Choose a .torrent file to see its name, size, the files inside, and the trackers it uses. Nothing is downloaded."));
    const out = h("div");
    main.append(h("div", { class: "row" }, h("button", { class: "primary", tip: "Choose a .torrent file to look inside.", onclick: async () => { const p = await F.pickOne("files"); if (!p) return; try { show(await post("/api/torrent/info", { source: p })); } catch (e) { F.toast(e.message); } } }, "Choose a .torrent file…")), out);
    function show(i) {
      out.replaceChildren(h("div", { class: "card-box" }, h("h3", { text: i.name }),
        h("p", { class: "hint", text: `${F.fmtBytes(i.size)}  ·  ${i.files.length} file${i.files.length === 1 ? "" : "s"}  ·  ${i.pieces} pieces of ${F.fmtBytes(i.piece_length)}${i.private ? "  ·  private" : ""}` }),
        i.comment ? h("p", { text: i.comment }) : null, h("p", { class: "mono", text: "Info hash: " + i.hash }),
        h("div", { class: "row" }, h("button", { class: "btn small", tip: "Copies the magnet link so you can share it.", onclick: () => F.copy(i.magnet) }, "Copy magnet link")),
        h("table", { class: "tbl" }, h("tr", {}, h("th", { text: "File" }), h("th", { text: "Size" })), ...i.files.slice(0, 500).map((f) => h("tr", {}, h("td", { text: f.path }), h("td", { text: F.fmtBytes(f.size) })))),
        i.trackers.length ? h("p", { class: "hint", text: "Trackers: " + i.trackers.join("  ·  ") }) : h("p", { class: "hint", text: "No trackers (it relies on the DHT network)." })));
    }
  });

  // ================================================================== link downloader
  reg({ id: "links", group: "torrent", icon: "🌐", label: "Download links", blurb: "Download files from web links (http, https, ftp): paste one or many, they download side by side.", files: false, output: true }, (main) => {
    main.append(F.titleBlock("Download links", "Paste web links, one on each line. Fathom downloads them side by side into the folder you choose on the left."));
    const form = F.form([{ id: "urls", type: "textarea", label: "Links", rows: 6, placeholder: "https://example.com/file.zip", tip: "One link on each line." }, { id: "name", type: "text", label: "Save as (only when there is one link)", placeholder: "keep the original name", tip: "Rename the file as it is saved. Leave empty to keep its own name." }]);
    main.append(h("div", { class: "card-box" }, form.el));
    runBar(main, "Download", "Downloads every link.", async () => { const v = form.values(); return post("/api/torrent/links", { urls: (v.urls || "").split(/\r?\n/), output: F.outputBody(), name: v.name || "" }); }, { noun: "link" });
  });
})();
