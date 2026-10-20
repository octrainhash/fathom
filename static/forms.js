/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* A tiny form builder so every tool's options are built the same way, each with a plain-words tooltip. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h;
  let uid = 0;
  /** spec: {id,type,label,tip,small,options:[{v,l,tip,s}],value,min,max,step,unit,show(vals),placeholder,inline}
   *  types: check | number | range | select | text | password | datetime | textarea | choice | note | multi (checkbox list) | pages (which pages, with page pictures) */
  F.form = (specs, onChange, opts = {}) => {
    const root = h("div", { class: opts.compact ? "opts" : "" });
    const items = [];
    const vals = () => Object.fromEntries(items.filter((i) => i.spec.id).map((i) => [i.spec.id, i.get()]));
    const refresh = () => { const v = vals(); for (const i of items) if (i.spec.show) i.el.hidden = !i.spec.show(v); };
    const changed = () => { refresh(); onChange && onChange(vals()); };
    for (const spec of specs) {
      const id = "f" + ++uid; let get = () => null, set = () => {}, el;
      const lab = (txt) => h("label", { for: id, text: txt });
      if (spec.type === "check") {
        const i = h("input", { type: "checkbox", id }); i.checked = !!spec.value;
        el = h("div", { class: "field" }, h("label", { tip: spec.tip }, i, spec.label, spec.small ? h("small", { text: "  " + spec.small }) : null));
        i.addEventListener("change", changed); get = () => i.checked; set = (v) => { i.checked = !!v; };
      } else if (spec.type === "number" || spec.type === "text" || spec.type === "password" || spec.type === "datetime") {
        const i = h("input", { type: spec.type === "datetime" ? "datetime-local" : spec.type, id, value: spec.value ?? "", placeholder: spec.placeholder || "", min: spec.min, max: spec.max, step: spec.step, autocomplete: "off", spellcheck: "false", style: spec.type === "number" ? "width:130px" : "" });
        F.tip(i, spec.tip);
        el = h("div", { class: "field" }, lab(spec.label), h("div", { class: "inline" }, i, spec.unit ? h("small", { text: spec.unit }) : null, spec.small ? h("small", { text: spec.small }) : null));
        i.addEventListener("input", changed);
        get = () => (spec.type === "number" ? (i.value === "" ? "" : parseFloat(i.value)) : i.value); set = (v) => { i.value = v ?? ""; };
      } else if (spec.type === "textarea") {
        const i = h("textarea", { id, placeholder: spec.placeholder || "", rows: spec.rows || 3 }); i.value = spec.value || "";
        F.tip(i, spec.tip); el = h("div", { class: "field" }, lab(spec.label), i, spec.small ? h("small", { text: spec.small }) : null);
        i.addEventListener("input", changed); get = () => i.value; set = (v) => { i.value = v ?? ""; };
      } else if (spec.type === "range") {
        const i = h("input", { type: "range", id, min: spec.min, max: spec.max, step: spec.step || 1, value: spec.value }); const out = h("output");
        const fmt = () => (out.textContent = spec.fmt ? spec.fmt(+i.value) : i.value);
        F.tip(i, spec.tip); el = h("div", { class: "field" }, h("label", { for: id }, spec.label, out), i); fmt();
        i.addEventListener("input", () => { fmt(); changed(); }); get = () => +i.value; set = (v) => { i.value = v; fmt(); };
      } else if (spec.type === "select") {
        const i = h("select", { id }, spec.options.map((o) => h("option", { value: o.v, text: o.l }))); i.value = spec.value ?? spec.options[0].v;
        F.tip(i, () => { const o = spec.options.find((x) => String(x.v) === i.value); return [spec.tip, o && o.tip ? "Now: " + o.tip : ""].filter(Boolean).join("\n"); });
        el = h("div", { class: "field" }, lab(spec.label), h("div", { class: "inline" }, i, spec.small ? h("small", { text: spec.small }) : null));
        i.addEventListener("change", changed); get = () => i.value; set = (v) => { i.value = v; };
      } else if (spec.type === "color") {
        // a colour picker: preset swatches, the system colour palette, and a hex box (any colour, not a short fixed list)
        const norm = (c) => { c = String(c || "").trim().replace(/^#?/, "#"); if (/^#[0-9a-f]{3}$/i.test(c)) c = "#" + [...c.slice(1)].map((x) => x + x).join(""); return /^#[0-9a-f]{6}$/i.test(c) ? c.toLowerCase() : null; };
        const presets = spec.options && spec.options.length ? spec.options : ["#000000", "#1b3a8c", "#1f4e9c", "#0b6b3a", "#1e8449", "#b03a2e", "#d35400", "#7a1f1f", "#4a1d8a", "#444444", "#7f8c8d", "#ffffff"].map((v) => ({ v, l: v }));
        let cur = norm(spec.value) || "#000000";
        const pick = h("input", { type: "color", id, value: cur, class: "colorpick", "aria-label": spec.label + " (colour palette)" });
        const hex = h("input", { type: "text", class: "hexbox", maxlength: 7, value: cur, spellcheck: "false", "aria-label": spec.label + " (hex code)" });
        const sws = presets.map((o) => [h("button", { type: "button", class: "swatch", style: "background:" + o.v, "aria-label": o.l, tip: o.l, onclick: () => { put(o.v); changed(); } }), o]);
        const paint = () => sws.forEach(([b, o]) => b.setAttribute("aria-pressed", String(norm(o.v) === cur)));
        const put = (v, typing) => { const n = norm(v); if (!n) return false; cur = n; pick.value = n; if (!typing) hex.value = n; paint(); return true; };
        pick.addEventListener("input", () => { put(pick.value); changed(); });
        hex.addEventListener("input", () => { if (put(hex.value, true)) changed(); });
        hex.addEventListener("blur", () => { hex.value = cur; });
        F.tip(pick, spec.tip); F.tip(hex, "Type any colour as a hex code, like #1b3a8c.");
        el = h("div", { class: "field" }, h("label", { for: id, text: spec.label }), h("div", { class: "colorrow" }, pick, hex, h("span", { class: "swatches" }, sws.map(([b]) => b)))); paint();
        get = () => cur; set = (v) => { put(v); };
      } else if (spec.type === "choice") {
        let cur = spec.value ?? spec.options[0].v; const btns = [];
        const paint = () => btns.forEach(([b, o]) => b.setAttribute("aria-pressed", String(o.v) === String(cur)));
        const box = h("div", { class: "cards" }, spec.options.map((o) => { const b = h("button", { type: "button", class: "choice", tip: o.tip, onclick: () => { cur = o.v; paint(); changed(); } }, h("b", { text: o.l }), o.s ? h("span", { text: o.s }) : null); btns.push([b, o]); return b; }));
        el = h("div", { class: "field" }, spec.label ? h("div", { class: "lab", text: spec.label }) : null, box); paint();
        get = () => cur; set = (v) => { cur = v; paint(); };
      } else if (spec.type === "multi") {
        const checks = spec.options.map((o) => { const c = h("input", { type: "checkbox", value: o.v }); c.checked = (spec.value || []).includes(o.v); c.addEventListener("change", changed); return [c, o]; });
        el = h("div", { class: "field" }, h("div", { class: "lab", text: spec.label }), h("div", { class: "opts", style: "margin-top:4px" }, checks.map(([c, o]) => h("label", { tip: o.tip }, c, o.l))));
        get = () => checks.filter(([c]) => c.checked).map(([, o]) => o.v); set = (v) => checks.forEach(([c, o]) => (c.checked = (v || []).includes(o.v)));
      } else if (spec.type === "pages") {
        const pp = F.pagePicker(spec, changed);
        el = h("div", { class: "field" }, spec.label ? h("div", { class: "lab", text: spec.label }) : null, pp.el, spec.small ? h("small", { text: spec.small }) : null);
        get = pp.get; set = pp.set; spec.picker = pp;
      } else if (spec.type === "note") {
        el = h("p", { class: "hint", text: spec.label }); if (spec.cls) el.className = spec.cls;
      } else continue;
      root.append(el); items.push({ spec, el, get, set });
    }
    refresh();
    return { el: root, values: vals, pagePicker: (id) => { const i = items.find((x) => x.spec.id === id); return i && i.spec.picker; }, set: (id, v) => { const i = items.find((x) => x.spec.id === id); if (i) { i.set(v); refresh(); } }, refresh,
             hideAll(on) { root.hidden = on; } };
  };
})();
