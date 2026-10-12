/* "Please wait, this takes time": a calm note with the time so far and an approximate time left, for anything that is not instant.
   - requests that take more than 4 seconds get a banner at the top of the window;
   - background jobs (the progress bar) compute the time left from how far they are;
   - times seen before are remembered in this browser (localStorage, optional) so later estimates get better. */
(() => {
  const F = window.Fathom;
  const SHOW_AFTER = 4000;
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage may be blocked: fine */ } },
  };
  F.fmtLeft = (s) => (s < 10 ? "a few seconds" : s < 45 ? "less than a minute" : s < 90 ? "about a minute" : s < 3600 ? `about ${Math.round(s / 60)} minutes` : `about ${(s / 3600).toFixed(1)} hours`);
  F.remember = (key, seconds) => { const a = store.get("fathom.dur." + key) || []; a.push(Math.round(seconds)); store.set("fathom.dur." + key, a.slice(-7)); };
  F.typical = (key) => { const a = (store.get("fathom.dur." + key) || []).slice().sort((x, y) => x - y); return a.length >= 2 ? a[Math.floor(a.length / 2)] : null; };
  /* the words: elapsed seconds, the typical total (or null), and the fraction done (or null) */
  F.waitText = (elapsed, typical, fraction) => {
    let left = null;
    if (fraction != null && fraction > 0.02 && elapsed > 3) left = elapsed * (1 - fraction) / fraction;
    else if (typical != null) left = typical - elapsed;
    let t = "Please wait, this takes time. ";
    if (left == null) t += `${F.fmtTime(elapsed)} so far; the time left is not known yet.`;
    else if (left < 5 && fraction == null) t += `${F.fmtTime(elapsed)} so far; it is taking a little longer than usual.`;
    else t += `${F.fmtTime(elapsed)} so far, ${F.fmtLeft(Math.max(left, 0))} left.`;
    return t;
  };

  /* ---- the banner ---- */
  const live = new Set();
  let bar = null, timer = null;
  const ensureBar = () => {
    if (bar) return bar;
    bar = document.createElement("div"); bar.className = "waitbar"; bar.setAttribute("role", "status"); bar.setAttribute("aria-live", "polite"); bar.hidden = true;
    bar.innerHTML = '<i class="spin"></i><div><strong></strong><span></span></div>';
    document.body.append(bar); return bar;
  };
  const redraw = () => {
    const shown = [...live].filter((w) => Date.now() - w.t0 >= SHOW_AFTER);
    const b = ensureBar();
    if (!shown.length) { b.hidden = true; return; }
    const w = shown[0], el = (Date.now() - w.t0) / 1000;
    b.querySelector("strong").textContent = w.label + (shown.length > 1 ? `  (+${shown.length - 1} more)` : "");
    b.querySelector("span").textContent = F.waitText(el, w.typical, w.fraction ? w.fraction() : null);
    b.hidden = false;
  };
  F.wait = {
    /* handle = F.wait.start("Converting…", { key: "convert", fraction: () => 0.4 }); handle.end(); */
    start(label, opts = {}) {
      const w = { label, t0: opts.t0 || Date.now(), key: opts.key || null, fraction: opts.fraction || null, typical: opts.key ? F.typical(opts.key) : null };
      live.add(w);
      if (!timer) timer = setInterval(redraw, 500);
      w.end = (ok = true) => {
        if (!live.delete(w)) return;
        if (ok && w.key && Date.now() - w.t0 >= SHOW_AFTER) F.remember(w.key, (Date.now() - w.t0) / 1000);
        if (!live.size) { clearInterval(timer); timer = null; }
        redraw();
      };
      return w;
    },
  };

  /* ---- every slow request ---- */
  const SKIP = /^\/api\/(ops\/|ai\/events|ai\/state|warm|health|ping)/;
  const LABELS = [
    [/\/ai\/transcribe/, "Understanding what you said"], [/\/ai\/speak/, "Making the voice"], [/\/convert/, "Converting"], [/\/search/, "Searching"],
    [/\/repair/, "Repairing"], [/\/ocr|handwriting/, "Reading text from the picture"], [/\/pdf/, "Working on the PDF"], [/\/drives|\/disk/, "Reading the drive"],
    [/\/scan/, "Scanning"], [/\/print/, "Printing"], [/\/torrent/, "Working on the torrent"], [/\/sync/, "Syncing"],
  ];
  const labelFor = (path) => { for (const [re, l] of LABELS) if (re.test(path)) return l; return "Working"; };
  const origApi = F.api;
  F.api = async function api(path, opts) {
    const p = String(path).split("?")[0];
    if (SKIP.test(p)) return origApi(path, opts);
    let w = null;
    const key = (opts && opts.method || "GET") + " " + p, t0 = Date.now();
    const t = setTimeout(() => { w = F.wait.start(labelFor(p) + "…", { key, t0 }); redraw(); }, SHOW_AFTER);
    try { const r = await origApi(path, opts); clearTimeout(t); if (w) w.end(true); return r; }
    catch (e) { clearTimeout(t); if (w) w.end(false); throw e; }
  };
})();
