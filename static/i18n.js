/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* Fathom language support (shared by the website, Fathom Online and the Windows app).
   The page is written in English. This file swaps every known piece of text for its translation when
   another language is chosen, keeps doing so for text the page creates later, and flips the layout for
   right-to-left languages. Text that has no translation stays in English. */
(() => {
  "use strict";
  // Languages that have a dictionary file in /lang (filled in by the build step).
  const AVAIL = /*AVAIL*/["en", "ar", "bn", "de", "es", "fa", "fr", "hi", "id", "it", "ja", "ko", "pt", "ru", "tr", "ur", "zh"]/*END*/;
  const NAMES = {
    en: "English", ur: "اردو", ar: "العربية", hi: "हिन्दी", es: "Español", fr: "Français", de: "Deutsch", pt: "Português",
    ru: "Русский", zh: "简体中文", "zh-TW": "繁體中文", ja: "日本語", ko: "한국어", tr: "Türkçe", id: "Bahasa Indonesia", it: "Italiano",
    bn: "বাংলা", fa: "فارسی", nl: "Nederlands", pl: "Polski", vi: "Tiếng Việt", th: "ไทย", sw: "Kiswahili", uk: "Українська",
    he: "עברית", ms: "Bahasa Melayu", fil: "Filipino", ta: "தமிழ்", te: "తెలుగు", mr: "मराठी", pa: "ਪੰਜਾਬੀ", gu: "ગુજરાતી",
    ro: "Română", cs: "Čeština", el: "Ελληνικά", hu: "Magyar", sv: "Svenska", da: "Dansk", fi: "Suomi", no: "Norsk", ps: "پښتو", sd: "سنڌي",
    kn: "ಕನ್ನಡ",
    ml: "മലയാളം",
    or: "ଓଡ଼ିଆ",
    as: "অসমীয়া",
    ne: "नेपाली",
    si: "සිංහල",
    ckb: "کوردیی ناوەندی",
    az: "Azərbaycanca",
    uz: "Oʻzbekcha",
    kk: "Қазақша",
    hy: "Հայերեն",
    ka: "ქართული",
    am: "አማርኛ",
    ha: "Hausa",
    yo: "Yorùbá",
    ig: "Igbo",
    zu: "isiZulu",
    xh: "isiXhosa",
    af: "Afrikaans",
    so: "Soomaali",
    rw: "Kinyarwanda",
    mg: "Malagasy",
    bg: "Български",
    sr: "Српски",
    hr: "Hrvatski",
    sk: "Slovenčina",
    sl: "Slovenščina",
    lt: "Lietuvių",
    lv: "Latviešu",
    et: "Eesti",
    ca: "Català",
    sq: "Shqip",
    mk: "Македонски",
    bs: "Bosanski",
    be: "Беларуская",
    is: "Íslenska",
    ga: "Gaeilge",
    cy: "Cymraeg",
    mt: "Malti",
    eu: "Euskara",
    gl: "Galego",
    lb: "Lëtzebuergesch",
    my: "မြန်မာ",
    km: "ខ្មែរ",
    lo: "ລາວ",
    mn: "Монгол",
    ug: "ئۇيغۇرچە",
    bo: "བོད་སྐད་",
    tg: "Тоҷикӣ",
    ky: "Кыргызча",
    tk: "Türkmençe",
    ku: "Kurdî",
    jv: "Basa Jawa",
    su: "Basa Sunda",
    ceb: "Cebuano",
    haw: "ʻŌlelo Hawaiʻi",
    mi: "Māori",
    sm: "Gagana Samoa",
    yi: "ייִדיש",
    la: "Latina",
    eo: "Esperanto",
    sa: "संस्कृतम्",
    bal: "بلوچی",
    skr: "سرائیکی",
    ks: "کٲشُر",
    brh: "براہوی",
    hnd: "ہندکو",
    bho: "भोजपुरी",
    mai: "मैथिली",
    sat: "ᱥᱟᱱᱛᱟᱲᱤ",
    kok: "कोंकणी",
    dv: "ދިވެހި",
    ti: "ትግርኛ",
    ny: "Chichewa",
    sn: "chiShona",
    st: "Sesotho",
    tn: "Setswana",
    wo: "Wolof",
    ln: "Lingála",
    lg: "Luganda",
    ee: "Eʋegbe",
    tw: "Twi",
    ht: "Kreyòl ayisyen",
    qu: "Runasimi",
    gn: "Avañe'ẽ",
    ay: "Aymar aru",
    fy: "Frysk",
    gd: "Gàidhlig",
    co: "Corsu",
    oc: "Occitan",
    br: "Brezhoneg",
    fo: "Føroyskt",
    hmn: "Hmoob",
    tt: "Татарча",
    ba: "Башҡортса",
    ce: "Нохчийн",
    cv: "Чӑвашла",
    ab: "Аҧсуа",
    os: "Ирон"
  };
  const RTL = new Set(["ar", "ur", "fa", "he", "ps", "sd", "ckb", "yi", "ug", "dv", "bal", "skr", "ks", "brh", "hnd"]);
  const KEY = "fathom-lang";
  const SKIP = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA", "NOSCRIPT", "SVG", "CANVAS", "KBD"]);
  const ATTRS = ["placeholder", "title", "aria-label", "alt", "data-tip"];
  const me = document.currentScript, base = me && me.src ? me.src.replace(/[^/]*$/, "") : "";
  const root = document.documentElement;
  let lang = "en", dict = null, tpl = null, mo = null;

  const store = { get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }, set(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* storage off */ } } };
  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const runs = /\d+/g;

  /** English text in, translated text out (the original when there is no translation). */
  function lookup(raw) {
    if (!dict) return null;
    const k = norm(raw);
    if (!k) return null;
    let o = dict[k];
    if (o !== undefined) return o;
    // a piece of a sentence with its dot, comma, bracket or dash left outside: translate the words, keep the marks
    const m = /^([.,;:)\]\s]*)(.*?)([(\[—–\-\s]*)$/.exec(k);
    if (m && m[2] && (m[1] || m[3]) && m[2] !== k) { const r = lookup(m[2]); if (r !== null) return m[1] + r + m[3]; }
    if (/\d/.test(k) && tpl) {
      const nums = k.match(runs);
      // number slots are numbered in order of appearance
      let n = 0;
      o = tpl[k.replace(runs, () => "{" + (n++) + "}")];
      if (o !== undefined) return o.replace(/\{(\d+)\}/g, (m, i) => nums[+i] !== undefined ? nums[+i] : m);
    }
    return null;
  }
  const t = (s) => { if (typeof s !== "string" || lang === "en") return s; const r = lookup(s); return r === null ? s : r; };

  function skipEl(el) {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (SKIP.has(e.tagName.toUpperCase()) || e.hasAttribute("data-no-i18n") || e.isContentEditable) return true;
    }
    return false;
  }
  function doText(n) {
    const d = n.data;
    const mine = n.__t !== undefined && d === n.__t;
    const orig = mine ? n.__o : d;
    let out = null;
    if (lang !== "en" && /\S/.test(orig)) {
      const r = lookup(orig);
      if (r !== null) out = (orig.match(/^\s*/)[0] ? " " : "") + r + (orig.match(/\s*$/)[0] ? " " : "");
    }
    if (out === null) { if (mine) { n.__t = undefined; n.__o = undefined; n.data = orig; } return; }
    n.__o = orig; n.__t = out;
    if (n.data !== out) n.data = out;
  }
  function doAttrs(el) {
    for (const a of ATTRS) {
      if (!el.hasAttribute(a)) continue;
      const v = el.getAttribute(a), st = el.__ia || (el.__ia = {}), rec = st[a];
      const mine = rec && v === rec.t, orig = mine ? rec.o : v;
      let out = null;
      if (lang !== "en") {
        if (a === "data-tip" && orig.indexOf("\n") >= 0) {
          // a help box: every line is translated by itself
          let hit = false;
          const lines = orig.split("\n").map((l) => { const r = l.trim() ? lookup(l) : null; if (r !== null) hit = true; return r === null ? l : r; });
          if (hit) out = lines.join("\n");
        } else { const r = lookup(orig); if (r !== null) out = r; }
      }
      if (out === null) { if (mine) { delete st[a]; el.setAttribute(a, orig); } continue; }
      st[a] = { o: orig, t: out };
      if (v !== out) el.setAttribute(a, out);
    }
  }
  function walk(node) {
    if (!node) return;
    if (node.nodeType === 3) { if (node.parentElement && !skipEl(node.parentElement)) doText(node); return; }
    if (node.nodeType !== 1) return;
    if (!node.closest("[data-no-i18n]")) doAttrs(node);
    if (skipEl(node)) return;
    for (let c = node.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) doText(c);
      else if (c.nodeType === 1) walk(c);
    }
  }
  function applyAll() {
    if (mo) mo.disconnect();
    walk(root);
    if (mo) observe();
    root.removeAttribute("data-i18n-wait");
  }
  function observe() {
    mo.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }
  function startObserver() {
    if (mo) return;
    mo = new MutationObserver((list) => {
      mo.disconnect();
      for (const m of list) {
        if (m.type === "characterData") { if (m.target.parentElement && !skipEl(m.target.parentElement)) doText(m.target); }
        else if (m.type === "attributes") { if (!m.target.closest("[data-no-i18n]")) doAttrs(m.target); }
        else for (const n of m.addedNodes) walk(n);
      }
      observe();
    });
    observe();
  }

  /** Turn a flat {english: translation} file into exact + number-template lookups. */
  function prepare(file) {
    dict = file.s || {};
    tpl = file.t || {};
  }
  async function load(code) {
    if (code === "en") { dict = null; tpl = null; return; }
    const r = await fetch(base + "lang/" + code + ".json", { cache: "no-cache" });
    if (!r.ok) throw new Error("language file " + r.status);
    prepare(await r.json());
  }

  function setDir(code) {
    root.setAttribute("lang", code === "zh-TW" ? "zh-Hant" : code === "zh" ? "zh-Hans" : code);
    root.setAttribute("dir", RTL.has(code) ? "rtl" : "ltr");
  }

  async function set(code, remember) {
    if (!NAMES[code] || (code !== "en" && AVAIL.indexOf(code) < 0)) code = "en";
    try { await load(code); } catch (e) { code = "en"; dict = null; tpl = null; }
    lang = code;
    setDir(code);
    if (remember !== false) store.set(code);
    startObserver();
    applyAll();
    const sel = document.getElementById("lang-pick");
    if (sel && sel.value !== code) sel.value = code;
    document.dispatchEvent(new CustomEvent("i18n-change", { detail: { lang: code } }));
    return code;
  }

  function pick() {
    const want = [];
    try {
      const q = new URLSearchParams(location.search).get("lang");
      if (q) { const c = q.trim(); store.set(c); want.push(c); }
    } catch (e) { /* no query */ }
    const saved = store.get();
    if (saved) want.push(saved);
    if (!want.length) for (const l of (navigator.languages || [navigator.language || "en"])) want.push(l);
    for (const w of want) {
      if (!w) continue;
      if (w === "en" || /^en\b/i.test(w)) return "en";
      const lw = w.toLowerCase();
      if (/^zh-(tw|hk|mo|hant)/.test(lw) && AVAIL.indexOf("zh-TW") >= 0) return "zh-TW";
      if (AVAIL.indexOf(w) >= 0) return w;
      const short = lw.split("-")[0];
      if (short === "nb" || short === "nn") { if (AVAIL.indexOf("no") >= 0) return "no"; }
      if (short === "tl" && AVAIL.indexOf("fil") >= 0) return "fil";
      if (short === "iw" && AVAIL.indexOf("he") >= 0) return "he";
      if (AVAIL.indexOf(short) >= 0) return short;
    }
    return "en";
  }

  function css() {
    const s = document.createElement("style");
    s.textContent = "html[data-i18n-wait] body{visibility:hidden}#lang-pick{font:inherit;font-size:.85rem;max-width:9.5em;padding:5px 6px;border-radius:8px;border:1px solid var(--line,#8886);background:var(--card,var(--bg,transparent));color:inherit;cursor:pointer}#lang-pick option{color:#111;background:#fff}";
    document.head.appendChild(s);
  }
  function mount() {
    if (AVAIL.length < 2 || document.getElementById("lang-pick")) return;
    const sel = document.createElement("select");
    sel.id = "lang-pick"; sel.setAttribute("data-no-i18n", ""); sel.setAttribute("aria-label", "Language"); sel.title = "Language";
    for (const c of ["en"].concat(AVAIL.filter((x) => x !== "en"))) {
      const o = document.createElement("option"); o.value = c; o.textContent = NAMES[c] || c; sel.appendChild(o);
    }
    sel.value = lang;
    sel.addEventListener("change", () => set(sel.value));
    const slot = document.querySelector("[data-lang-slot]") || document.querySelector(".top-right") || document.querySelector("nav.links");
    if (!slot) return;
    const ref = slot.querySelector("#theme, .theme, #quickfind");
    if (ref) slot.insertBefore(sel, ref); else slot.appendChild(sel);
  }

  // Dialogs the page opens with alert(), confirm() and prompt() are translated too.
  for (const f of ["alert", "confirm", "prompt"]) {
    const orig = window[f];
    if (typeof orig === "function") window[f] = function (m, ...rest) { return orig.call(window, t(String(m == null ? "" : m)), ...rest); };
  }

  window.I18N = { t, set, get lang() { return lang; }, available: AVAIL.slice(), names: NAMES, rtl: () => RTL.has(lang) };

  const first = pick();
  if (first !== "en") root.setAttribute("data-i18n-wait", "");
  const boot = () => {
    css(); mount();
    set(first, false).then(() => { const s = document.getElementById("lang-pick"); if (s) s.value = lang; });
    setTimeout(() => root.removeAttribute("data-i18n-wait"), 2500);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
