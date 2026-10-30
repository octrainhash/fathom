/* "Make it yours": looks and behaviour you can set exactly, down to the pixel. Applied the moment the page loads and live while you move a slider. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h;
  const DEF = { theme: "auto", accent: "", scale: 100, font: "ui", weight: 400, lineh: 1.5, radius: 14, gap: 100, motion: true, notify: false, sound: false, contrast: false, tips: true, blurbs: true, shadows: true, glass: true, cardw: 240, start: "last", bigclick: false, focus: true, css: "" };
  const FONTS = { ui: ["Windows default (Segoe UI)", 'var(--ui)'], system: ["Your system font", 'system-ui, sans-serif'], serif: ["Serif (Georgia)", 'Georgia, "Times New Roman", serif'], mono: ["Typewriter (Cascadia / Consolas)", 'var(--mono)'], read: ["Easy reading (Verdana)", 'Verdana, Tahoma, sans-serif'], dys: ["Dyslexia-friendly (Comic Sans / Trebuchet)", '"Comic Sans MS", "Trebuchet MS", sans-serif'] };
  const ACCENTS = [["", "Fathom violet"], ["#2f6bff", "Blue"], ["#0aa5c2", "Teal"], ["#17a34a", "Green"], ["#e8a100", "Amber"], ["#f0562b", "Orange"], ["#e0245e", "Rose"], ["#8a3ffc", "Purple"], ["#5b6178", "Slate"]];
  const get = () => Object.assign({}, DEF, F.load("look", {}) || {});
  const set = (patch) => { const v = Object.assign(get(), patch); F.save("look", v); apply(v); return v; };
  const mix = (hex, to, p) => { const n = (s) => [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16)); const a = n(hex), b = n(to); return "#" + a.map((x, i) => Math.round(x + (b[i] - x) * p).toString(16).padStart(2, "0")).join(""); };
  const valid = (c) => /^#[0-9a-f]{6}$/i.test(c || "");
  let style = null;
  function apply(v = get()) {
    const root = document.documentElement;
    const t = F.load("theme", "auto");
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t); else if (t === "black") root.setAttribute("data-theme", "dark"); else root.removeAttribute("data-theme");
    root.setAttribute("data-black", t === "black" ? "1" : "0");
    root.style.zoom = v.scale === 100 ? "" : String(v.scale / 100);
    if (!style) { style = document.createElement("style"); style.id = "mine-css"; document.head.appendChild(style); }
    const c = [];
    if (valid(v.accent)) c.push(`html:root:root:root{--acc:${v.accent}!important;--acc2:${mix(v.accent, "#ffffff", .3)}!important;--accg:linear-gradient(135deg,${mix(v.accent, "#000000", .12)},${mix(v.accent, "#ffffff", .22)})!important;--focus:${v.accent}!important;}`,
      `.primary{box-shadow:0 8px 24px color-mix(in srgb,${v.accent} 45%,transparent)!important}.brand img{box-shadow:0 4px 14px color-mix(in srgb,${v.accent} 45%,transparent)!important}`);
    c.push(`:root{--r:${v.radius}px}`);
    c.push(`body{font-family:${FONTS[v.font] ? FONTS[v.font][1] : FONTS.ui[1]};font-weight:${v.weight};line-height:${v.lineh}}`);
    if (v.gap !== 100) c.push(`.card-box{padding:${Math.round(18 * v.gap / 100)}px}.field{margin-top:${Math.round(14 * v.gap / 100)}px}.card-box{margin-top:${Math.round(16 * v.gap / 100)}px}`);
    if (!v.motion) c.push(`*,*::before,*::after{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important;scroll-behavior:auto!important}`);
    if (v.contrast) c.push(`html:root:root:root{--muted:var(--ink)!important;--line:color-mix(in srgb,var(--ink) 55%,transparent)!important}.btn,input,select,textarea,.card-box{border-width:2px!important}`);
    if (!v.shadows) c.push(`*{box-shadow:none!important}`);
    if (!v.glass) c.push(`*{backdrop-filter:none!important}body{background:var(--bg)!important}`);
    if (v.bigclick) c.push(`button,.btn,select,input:not([type=checkbox]):not([type=radio]){min-height:44px}`);
    if (!v.blurbs) c.push(`.homecard > :not(b){display:none!important}`);
    c.push(`.homegrid{grid-template-columns:repeat(auto-fill,minmax(${v.cardw}px,1fr))!important}`);
    if (!v.focus) c.push(`:focus-visible{outline:none!important}`);
    c.push(`:root[data-black="1"][data-theme]{--bg:#000!important;--bg2:#050507!important;--panel:#0a0a0f!important;--panel2:#101018!important}:root[data-black="1"] body{background:#000}`);
    if (v.css) c.push(v.css);
    style.textContent = c.join("\n");
    root.toggleAttribute("data-notips", !v.tips);
  }
  F.applyLook = apply; F.look = get;
  // tooltips off: the hover box checks this attribute
  document.addEventListener("mouseover", (e) => { if (document.documentElement.hasAttribute("data-notips")) { const t = document.getElementById("tip"); if (t) t.classList.remove("on"); } }, true);
  apply();
  // tell me when a job ends: a desktop notification, a short chime and the tab title, only if the page is not in front
  F.jobFinished = (s, noun) => {
    const v = get(); if (!v.notify && !v.sound) return;
    const bad = s && s.counts ? s.counts.error : 0, n = s && s.counts ? s.counts.done : 0;
    const msg = n + " " + (noun || "file") + (n === 1 ? "" : "s") + " done" + (bad ? ", " + bad + " could not be done" : "");
    if (v.notify && document.hidden && "Notification" in window && Notification.permission === "granted") { try { new Notification("Fathom is finished", { body: msg, icon: "/static/icon-192.png" }); } catch (e) { /* ignore */ } }
    if (v.sound) { try { const a = new (window.AudioContext || window.webkitAudioContext)(), o = a.createOscillator(), g = a.createGain(); o.connect(g); g.connect(a.destination); o.frequency.value = 880; g.gain.setValueAtTime(.12, a.currentTime); g.gain.exponentialRampToValueAtTime(.0001, a.currentTime + .5); o.start(); o.stop(a.currentTime + .5); } catch (e) { /* ignore */ } }
    if (document.hidden) { const t = document.title; document.title = "✔ " + msg; const back = () => { document.title = t; document.removeEventListener("visibilitychange", back); }; document.addEventListener("visibilitychange", back); }
  };

  F.addTool({ id: "mine", group: "tidy", icon: "🎛️", label: "Make it yours", blurb: "Colours, text size, roundness, spacing, fonts, motion, contrast and your own style rules: set every detail of how Fathom looks.", el: F.makeView("mine", false), build: (sec) => {
    const view = F.standardView("mine", { files: false, output: false });
    sec.replaceWith(view.sec); F.tools.find((x) => x.id === "mine").el = view.sec; view.sec.classList.add("on");
    const main = view.main;
    main.append(F.titleBlock("Make it yours", "Everything here changes Fathom the moment you touch it, and is remembered. Nothing is hidden: every size, colour and switch is yours to set."));
    const v0 = get();
    const card = (title, sub, ...kids) => h("div", { class: "card-box" }, h("h3", { text: title }), sub ? h("p", { class: "hint", text: sub }) : null, ...kids);
    const row = (label, ctl, tip) => h("div", { class: "field" }, h("div", { class: "lab", text: label, tip }), ctl);
    // slider with a typed number box: both always agree, and a reset arrow
    const slider = (key, label, min, max, step, unit, tip) => {
      const cur = () => get()[key];
      const r = h("input", { type: "range", min, max, step, value: cur(), style: "flex:1;min-width:160px" });
      const n = h("input", { type: "number", min, max, step, value: cur(), style: "width:84px" });
      const sync = (val) => { val = Math.min(max, Math.max(min, Number(val))); if (Number.isNaN(val)) return; r.value = val; n.value = val; set({ [key]: val }); };
      r.oninput = () => sync(r.value); n.onchange = () => sync(n.value);
      const rs = h("button", { class: "btn small", tip: "Put this back to the standard value.", onclick: () => sync(DEF[key]) }, "↺");
      return row(label, h("div", { class: "inline" }, r, n, h("span", { class: "hint", style: "margin:0", text: unit }), rs), tip);
    };
    const toggle = (key, label, tip) => { const c = h("input", { type: "checkbox" }); c.checked = !!get()[key]; c.onchange = () => set({ [key]: c.checked }); return h("label", { class: "inline", style: "gap:8px;margin-top:12px", tip }, c, label); };
    // theme
    const themeSel = h("select", { tip: "Auto follows Windows. Pure black saves battery on dark screens." }, [["auto", "Match Windows"], ["light", "Light"], ["dark", "Dark"], ["black", "Pure black"]].map(([v, l]) => h("option", { value: v, text: l })));
    themeSel.value = F.load("theme", "auto"); themeSel.onchange = () => { F.save("theme", themeSel.value); apply(); };
    // accent
    const sw = h("div", { class: "inline", style: "gap:8px" });
    const picker = h("input", { type: "color", value: valid(v0.accent) ? v0.accent : "#7c6cff", style: "width:44px;height:34px;padding:0;border:0;background:none", tip: "Pick any colour." });
    const hex = h("input", { type: "text", value: v0.accent, placeholder: "#7c6cff", maxlength: 7, style: "width:96px", tip: "Type a colour as #RRGGBB." });
    const mark = () => { for (const b of sw.children) b.style.outline = (b.dataset.c === get().accent) ? "2px solid var(--ink)" : "none"; };
    for (const [c, n] of ACCENTS) sw.append(h("button", { class: "btn small", "data-c": c, tip: n, style: `width:30px;height:30px;padding:0;border-radius:50%;background:${c || "linear-gradient(135deg,#5b4bff,#9b6bff)"}`, onclick: () => { set({ accent: c }); hex.value = c; if (c) picker.value = c; mark(); } }));
    picker.oninput = () => { set({ accent: picker.value }); hex.value = picker.value; mark(); };
    hex.onchange = () => { const t = hex.value.trim(); if (t === "" || valid(t)) { set({ accent: t }); if (t) picker.value = t; mark(); } else F.toast("Type a colour like #2f6bff"); };
    main.append(card("Colours", "", row("Theme", themeSel), row("Main colour", h("div", { class: "inline", style: "gap:10px" }, sw, picker, hex), "Buttons, highlights, links and the glowing bits."),
      toggle("contrast", "High contrast: stronger text and borders", "Easier to read in bright rooms or with low vision.")));
    mark();
    // size and text
    const fontSel = h("select", {}, Object.entries(FONTS).map(([k, [l]]) => h("option", { value: k, text: l })));
    fontSel.value = get().font; fontSel.onchange = () => set({ font: fontSel.value });
    main.append(card("Size and text", "Everything scales together, so nothing breaks.",
      slider("scale", "Whole window size", 70, 200, 5, "%", "Makes every button, word and picture bigger or smaller. 100% is standard."),
      row("Font", fontSel), slider("weight", "Text weight", 300, 700, 100, "", "300 is thin, 400 normal, 700 bold."),
      slider("lineh", "Space between lines", 1.2, 2, 0.05, "×", "More space is easier on the eyes.")));
    main.append(card("Shape and space", "",
      slider("radius", "Roundness of corners", 0, 30, 1, "px", "0 gives sharp square corners. 30 is very round."),
      slider("gap", "Spacing inside boxes", 50, 180, 5, "%", "Pack more on screen, or give everything room."),
      slider("cardw", "Width of tool cards", 160, 420, 10, "px", "Narrow cards fit more tools on a row."),
      toggle("bigclick", "Bigger buttons (at least 44 pixels tall)", "Good for touch screens and shaky hands.")));
    const nt = toggle("notify", "Desktop notification when a long job finishes", "Shows a message from Windows if Fathom is in the background."); nt.querySelector("input").addEventListener("change", (e) => { if (e.target.checked && "Notification" in window && Notification.permission === "default") Notification.requestPermission(); });
    main.append(card("Tell me when it is done", "Useful when you start a big batch and do something else.", nt, toggle("sound", "Play a short chime", "A soft beep when a job ends.")));
    main.append(card("Comfort", "",
      toggle("motion", "Smooth animations", "Off stops sliding, fading and glowing."), toggle("shadows", "Shadows under boxes", "Off gives a flat look."),
      toggle("glass", "Frosted glass and soft background glow", "Off makes plain solid backgrounds; a little faster on old PCs."),
      toggle("tips", "Help bubbles when you hover", "Turn off once you know your way around."),
      toggle("blurbs", "Descriptions on the home page cards", "Off gives a compact list of names only."),
      toggle("focus", "Outline around the thing the keyboard is on", "Keep this on if you use Tab to move around.")));
    // startup
    const st = h("select", { tip: "Which tool Fathom opens on." }, [["last", "The tool I used last"], ["home", "Always All tools"]].map(([v, l]) => h("option", { value: v, text: l })));
    st.value = get().start; st.onchange = () => set({ start: st.value });
    main.append(card("When Fathom opens", "", row("Open on", st)));
    // custom css
    const ta = h("textarea", { rows: 8, spellcheck: "false", placeholder: "/* Your own style rules, for example: */\n.primary { border-radius: 0; }\n.top { background: #111; }", style: "width:100%;font-family:var(--mono);font-size:12.5px", tip: "Plain CSS. Applied on top of everything else, live." });
    ta.value = get().css; let tm = null; ta.oninput = () => { clearTimeout(tm); tm = setTimeout(() => set({ css: ta.value }), 250); };
    main.append(card("Your own style rules (for experts)", "Any CSS you type here is applied at once, so you can change any pixel of the window. Clear the box to undo it.", ta));
    // backup
    const exp = h("button", { class: "btn", tip: "Copies all your choices as text you can keep or paste on another PC.", onclick: async () => { const s = JSON.stringify({ look: get(), theme: F.load("theme", "auto") }); try { await navigator.clipboard.writeText(s); F.toast("Settings copied"); } catch { box.value = s; } } }, "Copy my settings");
    const box = h("textarea", { rows: 2, placeholder: "Paste settings here, then press Use these", style: "width:100%;margin-top:8px;font-family:var(--mono);font-size:12px" });
    const imp = h("button", { class: "btn", onclick: () => { try { const o = JSON.parse(box.value); if (o.theme) F.save("theme", o.theme); set(o.look || {}); F.toast("Settings applied"); F.show("mine"); } catch { F.toast("That is not a settings text"); } } }, "Use these");
    const rst = h("button", { class: "btn danger", tip: "Back to how Fathom looked when you first installed it.", onclick: () => { F.save("look", {}); F.save("theme", "auto"); apply(); F.toast("Everything is back to standard"); F.show("home"); } }, "Reset everything to standard");
    main.append(card("Keep, share or reset", "", h("div", { class: "inline", style: "gap:8px" }, exp, imp, rst), box));
  } });
})();
