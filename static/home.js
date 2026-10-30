/* Home (every tool at a glance, with a search box and a theme switch) and the Ctrl+K quick-find. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h;
  const GROUPS = () => Object.fromEntries(F.groups.map((g) => [g.id, g.label]));
  if (F.applyLook) F.applyLook();

  F.addTool({ id: "home", group: "home", icon: "🏠", label: "All tools", blurb: "Every tool in Fathom on one page, with a search box.", el: F.makeView("home", false), build: (sec) => {
    const view = F.standardView("home", { files: false, output: false });
    sec.replaceWith(view.sec); F.tools.find((x) => x.id === "home").el = view.sec; view.sec.classList.add("on");
    const main = view.main;
    main.append(F.titleBlock("Everything Fathom can do", "Click any tool to open it. Press Ctrl+K at any time to jump to a tool by typing what you want to do (for example 'sign', 'shrink' or 'torrent')."));
    const q = h("input", { type: "search", placeholder: "What do you want to do?  e.g. replace a word, sign a PDF, make a QR code…", style: "width:100%;max-width:560px", tip: "Type to filter the tools below." });
    const theme = h("button", { class: "btn small", tip: "Colours, text size, roundness, spacing, fonts, animations and more.", onclick: () => F.show("mine") }, "🎛️ Make it yours");
    main.append(h("div", { class: "row", style: "gap:14px;flex-wrap:wrap;margin-top:6px" }, q, theme));
    // "What are you working with?": quick filter by kind of file
    const KINDS = [["all", "Everything", null], ["pdf", "PDF", /pdf/], ["pic", "Pictures", /picture|photo|image|jpg|png|\bgif\b|webp|icon|collage|meme|face/], ["vid", "Video", /video|movie|\bgif\b|slideshow|subtitle|clip/], ["snd", "Sound", /sound|song|audio|voice|music|speech|recording|volume|silence/],
      ["tab", "Tables & data", /csv|table|excel|spreadsheet|json|data|database/], ["doc", "Documents", /word|document|text|office|powerpoint|markdown|e-?book|translate/], ["file", "Files & folders", /file|folder|archive|zip|rename|duplicate|disk|drive|torrent|backup|sync/]];
    let kind = "all";
    const NEW = new Set(["pdfcrop", "pdfflatten", "pdfmarkdown", "pdffillable", "blurfaces", "meme", "gif", "speed", "loudness", "mute", "pdfheader", "pdftables", "pdfclean", "pdfbookmarks", "pdfresize", "collage", "frame", "icon", "transparent", "picsgif", "slideshow", "videocrop", "reverse", "silence", "fade", "addaudio", "videomark", "csvclean"]);
    const chips = h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:14px" }, KINDS.map(([id, label]) => h("button", { class: "kindchip", "data-k": id, "aria-pressed": String(id === kind), onclick: () => { kind = id; for (const c of chips.children) c.setAttribute("aria-pressed", String(c.dataset.k === id)); draw(); } }, label)));
    main.append(chips);
    const host = h("div"); main.append(host);
    const kindOk = (t, g) => { const k = KINDS.find((x) => x[0] === kind); if (k && k[2] && (t.id === "assistant" || t.id === "find" || t.id === "convert")) return false; return !k || !k[2] || k[2].test((t.label + " " + t.blurb + " " + t.id).toLowerCase()); };
    const draw = () => {
      const term = q.value.trim().toLowerCase(); host.replaceChildren(); const G = GROUPS();
      for (const g of F.groups.filter((x) => x.id !== "home")) {
        const tools = F.tools.filter((t) => t.group === g.id && kindOk(t, g) && (!term || (t.label + " " + t.blurb + " " + g.label).toLowerCase().includes(term)));
        if (!tools.length) continue;
        host.append(h("div", { class: "homegroup", text: G[g.id] }), h("div", { class: "homegrid" }, tools.map((t) => h("button", { class: "homecard", tip: t.blurb, onclick: () => F.show(t.id) }, h("b", { text: t.icon + "  " + t.label }, NEW.has(t.id) ? h("em", { class: "newtag", text: "new" }) : null), h("span", { text: t.blurb })))));
      }
      if (!host.children.length) host.append(h("p", { class: "hint", text: "Nothing matches that. Try another word." }));
    };
    q.addEventListener("input", draw); draw();
  } });

  // ---- Ctrl+K quick-find
  let open = null;
  function palette() {
    if (open) return close();
    const back = h("div", { class: "palette-back", onclick: (e) => { if (e.target === back) close(); } });
    const input = h("input", { type: "text", placeholder: "Jump to a tool…  (type what you want to do)", spellcheck: "false" });
    const ul = h("ul"); let items = [], act = 0;
    const score = (t, term) => { const hay = (t.label + " " + t.blurb).toLowerCase(); if (!term) return 1; let s = 0; for (const w of term.split(/\s+/)) { if (t.label.toLowerCase().startsWith(w)) s += 5; else if (t.label.toLowerCase().includes(w)) s += 3; else if (hay.includes(w)) s += 1; else return 0; } return s; };
    const G = GROUPS();
    const render = () => { const term = input.value.trim().toLowerCase(); items = F.tools.map((t) => [t, score(t, term)]).filter(([, s]) => s > 0).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([t]) => t); act = Math.min(act, Math.max(0, items.length - 1));
      ul.replaceChildren(...items.map((t, i) => h("li", { class: i === act ? "on" : "", onclick: () => go(t), onmousemove: () => { act = i; [...ul.children].forEach((c, j) => c.classList.toggle("on", j === act)); } }, h("b", { text: `${t.icon}  ${t.label}` }), h("small", { text: `${G[t.group] || ""} · ${t.blurb.slice(0, 110)}` })))); };
    const go = (t) => { close(); F.show(t.id); };
    input.addEventListener("input", () => { act = 0; render(); });
    input.addEventListener("keydown", (e) => { if (e.key === "ArrowDown") { e.preventDefault(); act = Math.min(items.length - 1, act + 1); render(); } else if (e.key === "ArrowUp") { e.preventDefault(); act = Math.max(0, act - 1); render(); } else if (e.key === "Enter" && items[act]) go(items[act]); else if (e.key === "Escape") close(); });
    back.append(h("div", { class: "palette" }, input, ul)); document.body.append(back); open = back; render(); input.focus();
  }
  function close() { if (open) { open.remove(); open = null; } }
  window.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette(); } });
  F.palette = palette;
  const qb = document.getElementById("quickfind"); if (qb) qb.onclick = palette;
})();
