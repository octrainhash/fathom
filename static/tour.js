/* First-run tour, help button, keyboard shortcuts, screen-reader names, "Save a problem report". */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h;
  const label = () => document.querySelectorAll("[data-tip]").forEach((el) => {
    if (el.getAttribute("aria-label") || !/^(BUTTON|INPUT|SELECT|TEXTAREA|A)$/.test(el.tagName)) return;
    const t = (el.getAttribute("data-tip") || "").split("\n")[0].slice(0, 160);
    if (t && !(el.textContent || "").trim() && !el.labels?.length) el.setAttribute("aria-label", t); else if (t) el.setAttribute("aria-description", t);
  });
  let pend = 0;
  new MutationObserver(() => { if (!pend) pend = setTimeout(() => { pend = 0; label(); }, 500); }).observe(document.body, { childList: true, subtree: true });
  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "");
    if (e.altKey && /^[1-9]$/.test(e.key)) { const g = F.groups[+e.key - 1], t = g && F.tools.find((x) => x.group === g.id); if (t) { e.preventDefault(); F.show(t.id); } }
    if (e.key === "?" && !typing && !e.ctrlKey) { e.preventDefault(); tour(); }
  });
  const STEPS = [
    ["Welcome to Fathom", "One place for anything to do with files. The bar along the top has groups; each group holds tools, and every tool has its own page. Hover over any button or box to read what it does in plain words."],
    ["Add your files", "On the left of most tools you add files or whole folders (use the button, or drag them in). The same list is used by every tool, so you add things once."],
    ["Nothing changes behind your back", "Results are saved as new files next to your originals unless you tick “Replace the original”. Proof pictures show what changed, and Tidy › Activity & Undo takes any change back."],
    ["Talk to the Assistant", "Press Ctrl+J anywhere. Type or press 🎤 Talk and speak in any language; it answers in writing and out loud. Press 👁 Watch my screen and it sees what you see. It can make PDFs, pictures and videos, run any tool, read handwriting, and build new tools."],
    ["Shortcuts", "Ctrl+K finds any tool by typing what you want. Ctrl+J opens the Assistant. Alt+1…9 jump between top-bar groups. Press ? any time to see this tour again."],
  ];
  function tour() {
    let i = 0;
    const box = h("div", { class: "modal tour" }), back = h("div", { class: "modal-back", role: "dialog", "aria-modal": "true", "aria-label": "Fathom tour", style: "position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:100" }, box);
    box.style.cssText = "background:var(--panel,#fff);color:var(--ink,#151833);border:1px solid var(--line);box-shadow:var(--shadow,0 10px 34px rgba(0,0,0,.4));border-radius:16px;padding:24px 24px 20px;max-width:460px;width:90%;max-height:86vh;overflow:auto;box-sizing:border-box";
    const close = () => { back.remove(); document.removeEventListener("keydown", key); F.save("tour", 1); };
    const next = () => { if (i < STEPS.length - 1) { i++; draw(); } else close(); };
    const key = (e) => { if (e.key === "Escape") close(); else if (e.key === "ArrowRight" || e.key === "Enter") next(); };
    const draw = () => {
      const nb = h("button", { class: "primary", onclick: next }, i === STEPS.length - 1 ? "Start using Fathom" : "Next"); F.tip(nb, "Go to the next tip.");
      const sk = h("button", { class: "btn", onclick: close }, "Skip"); F.tip(sk, "Close the tour. Press ? to open it again.");
      box.replaceChildren(h("div", { class: "muted", text: `${i + 1} of ${STEPS.length}` }), h("h2", { text: STEPS[i][0], style: "margin:6px 0 4px" }), h("p", { text: STEPS[i][1], style: "margin:10px 0 26px;line-height:1.55" }), h("div", { style: "display:flex;justify-content:flex-end;gap:10px;padding-top:6px" }, sk, nb));
      nb.focus();
    };
    document.body.append(back); document.addEventListener("keydown", key); draw();
  }
  F.tour = tour;
  F.onBoot = F.onBoot || [];
  F.onBoot.push(() => {
    label();
    const ver = h("div", { class: "muted", style: "padding:4px 10px;font-size:12px;max-width:300px;word-break:break-all" }, "Fathom");
    const menu = h("div", { hidden: true, style: "position:fixed;right:14px;top:56px;background:var(--bg2,#fff);border:1px solid var(--line,#ccc);border-radius:12px;padding:6px;z-index:60;display:flex;flex-direction:column;gap:4px;box-shadow:0 12px 40px rgba(0,0,0,.25)" },
      h("button", { class: "btn small", onclick: () => { menu.hidden = true; tour(); } }, "Show the tour"),
      h("button", { class: "btn small", onclick: async () => { menu.hidden = true; try { const r = await F.api("/api/support/bundle", { method: "POST" }); F.toast("Saved: " + r.path); if (!F.isServe || !F.isServe()) F.reveal(r.path); } catch (e) { F.toast(e.message); } } }, "Save a problem report"),
      ver);
    F.api("/api/info").then((i) => { ver.textContent = "Fathom " + i.version + " · created by The Fathomist" + (i.folder ? " · running from " + i.folder : ""); }).catch(() => {});
    const help = h("button", { class: "btn small help-btn", "aria-label": "Help", "aria-haspopup": "menu", onclick: () => { menu.hidden = !menu.hidden; } }, "?");
    F.tip(help, "Help: see the tour again, or save a problem report (a zip of Fathom's log files, no file contents or keys) to your Downloads folder.");
    const right = document.querySelector(".top-right");
    if (right) right.insertBefore(help, right.firstChild); else document.body.append(help);
    document.body.append(menu);
    document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target) && e.target !== help) menu.hidden = true; });
    if (!F.load("tour", 0) && !navigator.webdriver) setTimeout(tour, 700);
  });
})();
