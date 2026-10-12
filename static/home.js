/* Home (every tool at a glance, with a search box and a theme switch) and the Ctrl+K quick-find. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h;
  const GROUPS = () => Object.fromEntries(F.groups.map((g) => [g.id, g.label]));
  const applyTheme = (t) => { if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t); else document.documentElement.removeAttribute("data-theme"); };
  applyTheme(F.load("theme", "auto"));

  F.addTool({ id: "home", group: "home", icon: "🏠", label: "All tools", blurb: "Every tool in Fathom on one page, with a search box.", el: F.makeView("home", false), build: (sec) => {
    const view = F.standardView("home", { files: false, output: false });
    sec.replaceWith(view.sec); F.tools.find((x) => x.id === "home").el = view.sec; view.sec.classList.add("on");
    const main = view.main;
    main.append(F.titleBlock("Everything Fathom can do", "Click any tool to open it. Press Ctrl+K at any time to jump to a tool by typing what you want to do (for example 'sign', 'shrink' or 'torrent')."));
    const q = h("input", { type: "search", placeholder: "What do you want to do?  e.g. replace a word, sign a PDF, make a QR code…", style: "width:100%;max-width:560px", tip: "Type to filter the tools below." });
    const theme = h("select", { tip: "Auto follows your Windows setting. Light and Dark force one look." }, [["auto", "Match Windows"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => h("option", { value: v, text: l })));
    theme.value = F.load("theme", "auto"); theme.onchange = () => { F.save("theme", theme.value); applyTheme(theme.value); };
    main.append(h("div", { class: "row", style: "gap:14px;flex-wrap:wrap;margin-top:6px" }, q, h("label", {}, "Look ", theme)));
    const host = h("div"); main.append(host);
    const draw = () => {
      const term = q.value.trim().toLowerCase(); host.replaceChildren(); const G = GROUPS();
      for (const g of F.groups.filter((x) => x.id !== "home")) {
        const tools = F.tools.filter((t) => t.group === g.id && (!term || (t.label + " " + t.blurb + " " + g.label).toLowerCase().includes(term)));
        if (!tools.length) continue;
        host.append(h("div", { class: "homegroup", text: G[g.id] }), h("div", { class: "homegrid" }, tools.map((t) => h("button", { class: "homecard", tip: t.blurb, onclick: () => F.show(t.id) }, h("b", { text: t.icon + "  " + t.label }), h("span", { text: t.blurb })))));
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
