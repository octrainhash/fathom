/* Assistant voice and screen: talk to it in any language, hear it answer, and let it watch your screen. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, ai = F.ai;
  if (!ai) return;
  const post = (p, b) => F.api(p, { method: "POST", body: b || {} });
  const LANGS = [["auto", "Any language"], ["en-US", "English"], ["ur-PK", "اردو Urdu"], ["hi-IN", "हिन्दी Hindi"], ["ar-SA", "العربية Arabic"], ["bn-BD", "বাংলা Bengali"], ["pa-IN", "ਪੰਜਾਬੀ Punjabi"], ["fa-IR", "فارسی Persian"], ["tr-TR", "Türkçe"], ["es-ES", "Español"], ["fr-FR", "Français"], ["de-DE", "Deutsch"], ["it-IT", "Italiano"], ["pt-BR", "Português"], ["nl-NL", "Nederlands"], ["sv-SE", "Svenska"], ["pl-PL", "Polski"], ["ru-RU", "Русский"], ["uk-UA", "Українська"], ["el-GR", "Ελληνικά"], ["he-IL", "עברית"], ["zh-CN", "中文 (普通话)"], ["zh-TW", "中文 (繁體)"], ["ja-JP", "日本語"], ["ko-KR", "한국어"], ["th-TH", "ไทย"], ["vi-VN", "Tiếng Việt"], ["id-ID", "Indonesia"], ["ms-MY", "Melayu"], ["fil-PH", "Filipino"], ["ta-IN", "தமிழ்"], ["te-IN", "తెలుగు"], ["mr-IN", "मराठी"], ["gu-IN", "ગુજરાતી"], ["kn-IN", "ಕನ್ನಡ"], ["ml-IN", "മലയാളം"], ["ne-NP", "नेपाली"], ["si-LK", "සිංහල"], ["sw-KE", "Kiswahili"], ["am-ET", "አማርኛ"], ["cs-CZ", "Čeština"], ["ro-RO", "Română"], ["hu-HU", "Magyar"], ["fi-FI", "Suomi"], ["da-DK", "Dansk"], ["nb-NO", "Norsk"]];
  const ARABIC_SCRIPT = new Set(["ar", "ur", "fa", "ps", "sd", "ug"]);
  const SCRIPTS = [[/[؀-ۿݐ-ݿ]/, "arabic"], [/[ऀ-ॿ]/, "hi"], [/[ঀ-৿]/, "bn"], [/[਀-੿]/, "pa"], [/[઀-૿]/, "gu"], [/[஀-௿]/, "ta"], [/[ఀ-౿]/, "te"], [/[ಀ-೿]/, "kn"], [/[ഀ-ൿ]/, "ml"], [/[඀-෿]/, "si"], [/[฀-๿]/, "th"], [/[぀-ヿ]/, "ja"], [/[가-힯]/, "ko"], [/[一-鿿]/, "zh"], [/[Ѐ-ӿ]/, "ru"], [/[Ͱ-Ͽ]/, "el"], [/[֐-׿]/, "he"], [/[ሀ-፿]/, "am"]];
  const V = { listening: false, speak: F.load("ai.speak", true), hands: false, lang: F.load("ai.lang", "auto"), spoken: "", buf: "", watch: false, uis: [], timer: 0, stopRec: null };

  const P = Object.assign({ mic: "", voice: "", rate: 1, engine: "auto" }, F.load("ai.voice", {}));
  const savePrefs = () => F.save("ai.voice", P);
  const detect = (text) => {
    for (const [rx, code] of SCRIPTS) if (rx.test(text)) return code === "arabic" ? (ARABIC_SCRIPT.has(V.spoken) ? V.spoken : (V.lang !== "auto" && ARABIC_SCRIPT.has(V.lang.split("-")[0]) ? V.lang.split("-")[0] : "ar")) : code;
    const l = (V.spoken || (V.lang !== "auto" ? V.lang : navigator.language || "en")).split("-")[0];
    return SCRIPTS.some(([, c]) => c === l) || ARABIC_SCRIPT.has(l) ? "en" : l;   // Latin text, but the user spoke a non-Latin language: the reply is most likely English
  };
  const plain = (t) => t.replace(/```[\s\S]*?```/g, " (code left out) ").replace(/`([^`]*)`/g, "$1").replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/https?:\/\/\S+/g, " link ").replace(/^[#>\-*\s|]+/gm, "").replace(/[*_~|#]+/g, "").replace(/\s+/g, " ").trim();
  const voices = () => new Promise((res) => { const v = speechSynthesis.getVoices(); if (v.length) return res(v); const t = setTimeout(() => res(speechSynthesis.getVoices()), 1200); speechSynthesis.onvoiceschanged = () => { clearTimeout(t); res(speechSynthesis.getVoices()); }; });
  let warned = false, speakToken = 0, curAudio = null; const warnedLang = {};
  const sentences = (clean) => {
    const parts = clean.match(/[^.!?。！？؟।\n]+[.!?。！？؟।]*/g) || [clean];
    const chunks = []; let cur = "";
    for (const p of parts) { if ((cur + p).length > 170 && cur) { chunks.push(cur); cur = p; } else cur += (cur ? " " : "") + p; }
    if (cur) chunks.push(cur);
    return chunks;
  };
  async function speak(text, forceServer) {
    const clean = plain(text); if (!clean) return afterSpeech();
    stopSpeaking(true);                                   // silence anything still being read (this also moves the counter on)
    const token = ++speakToken, lang = detect(clean), chunks = sentences(clean);
    setStatus("speaking");
    let voice = null, noVoice = "";
    // on Windows the computer's own voice (made by Fathom's engine and played as sound) is the most dependable; the window's built-in reader is the fallback
    if (!forceServer && P.engine === "auto" && /Windows/i.test(navigator.userAgent)) {
      try { await serverSpeak(chunks, lang, token); if (token === speakToken) afterSpeech(token); return; }
      catch (e) { if (token !== speakToken) return; if (/NOVOICE/.test(e.message || "")) noVoice = lang; /* fall through to the window's own reader */ }
    }
    if ("speechSynthesis" in window && !forceServer && P.engine !== "server") {
      const vs = await voices();
      voice = (P.voice && vs.find((v) => v.name === P.voice && v.lang.toLowerCase().startsWith(lang.toLowerCase()))) || null;
      if (!voice) { const match = vs.filter((v) => v.lang.toLowerCase().replace("_", "-").startsWith(lang.toLowerCase())); voice = match.find((v) => /natural|online/i.test(v.name)) || match[0] || null; }
      if (!voice && P.voice && lang === (vs.find((v) => v.name === P.voice) || { lang: "" }).lang.split("-")[0]) voice = vs.find((v) => v.name === P.voice);
    }
    if (token !== speakToken) return;
    if (voice) { if (await browserSpeak(chunks, voice, token)) return afterSpeech(token); if (token !== speakToken) return; }
    // the browser has no voice for this language (or did not start): use the computer's own voice / the voice service
    try { if (noVoice) throw new Error("NOVOICE:" + noVoice); await serverSpeak(chunks, lang, token); }
    catch (e) {
      if (token === speakToken) {
        setStatus("");
        const m = /NOVOICE:(\w+)/.exec(e.message || "");
        if (m) { if (!warnedLang[m[1]]) { warnedLang[m[1]] = 1; let n = m[1]; try { n = new Intl.DisplayNames(["en"], { type: "language" }).of(m[1]) || n; } catch { /* ok */ } F.toast(`This PC has no ${n} voice yet, so the answer is not read aloud. Add one: Windows Settings > Time & language > Language & region > ${n} > Language options > install "Text-to-speech" (and "Speech"), then restart Fathom.`, 14000); } }
        else if (!warned) { warned = true; F.toast("Could not speak the answer: " + e.message); }
      }
      return;
    }
    afterSpeech(token);
  }
  function browserSpeak(chunks, voice, token) {
    return new Promise((resolve) => {
      let started = false, finished = false;
      const t0 = Date.now(), chars = chunks.reduce((n, c) => n + c.length, 0);
      const fail = () => { if (!finished) { finished = true; try { speechSynthesis.cancel(); } catch { /* ok */ } resolve(false); } };
      const watchdog = setTimeout(() => { if (!started) fail(); }, 3000);
      // some PCs "finish" at once without a sound: reading N characters aloud cannot take less than about 20 ms each
      const tooFast = () => (Date.now() - t0) < Math.min(2500, chars * 20);
      speechSynthesis.cancel();
      chunks.forEach((c, i) => {
        const u = new SpeechSynthesisUtterance(c); u.lang = voice.lang; u.voice = voice; u.rate = P.rate || 1;
        u.onstart = () => { started = true; clearTimeout(watchdog); };
        u.onerror = (e) => { if (e.error === "canceled" || e.error === "interrupted") { if (!finished) { finished = true; resolve(true); } } else fail(); };
        if (i === chunks.length - 1) u.onend = () => { if (finished) return; if (tooFast() && token === speakToken) return fail(); finished = true; clearTimeout(watchdog); resolve(true); };
        speechSynthesis.speak(u);
      });
    });
  }
  async function serverSpeak(chunks, lang, token) {
    // first choice: this PC's engine plays the voice on the speakers itself (the window's own sound can be silent on some PCs)
    let local = null;
    try {
      let next = post("/api/ai/speak_prepare", { text: chunks[0], lang, voice: "" });
      for (let i = 0; i < chunks.length; i++) {
        const r = await next; if (token !== speakToken) return;
        if (!r.local) { local = false; break; }
        local = true;
        if (i + 1 < chunks.length) next = post("/api/ai/speak_prepare", { text: chunks[i + 1], lang, voice: "" });
        const played = await post("/api/ai/speak_play", { id: r.id });
        if (token !== speakToken) return;
        if (!played.played) { local = false; break; }
      }
      if (local) return;
    } catch (e) { if (local) throw e; local = false; }
    // otherwise: the window plays the sound file
    const fetchOne = (c) => post("/api/ai/speak", { text: c, lang, voice: "" });
    let next = fetchOne(chunks[0]);
    for (let i = 0; i < chunks.length; i++) {
      const r = await next; if (token !== speakToken) return;
      if (i + 1 < chunks.length) next = fetchOne(chunks[i + 1]);
      await new Promise((resolve, reject) => {
        const a = new Audio(r.data); curAudio = a; a.playbackRate = P.rate || 1;
        a.onended = () => resolve(); a.onerror = () => reject(new Error("the sound could not be played"));
        a.play().catch((e) => reject(new Error(e.name === "NotAllowedError" ? "the window blocked sound until you click something in it" : e.message)));
      });
      if (token !== speakToken) return;
    }
  }
  const stopSpeaking = (keepStatus) => { speakToken++; post("/api/ai/speak_stop").catch(() => {}); try { speechSynthesis.cancel(); } catch { /* ok */ } if (curAudio) { try { curAudio.pause(); } catch { /* ok */ } curAudio = null; } if (!keepStatus && V.status === "speaking") setStatus(""); };
  function afterSpeech(token) { if (token !== undefined && token !== speakToken) return; setStatus(""); if (V.hands && !V.listening && !ai.isRunning()) setTimeout(() => { if (V.hands && !V.listening) listen(); }, 500); }

  // ---------------------------------------------------------------- listening
  async function listen() {
    if (V.listening) { V.stopRec && V.stopRec(); return; }
    if (V.status === "speaking") { stopSpeaking(); return; }
    if (ai.isRunning()) return F.toast("The assistant is still working. Wait for it, or press Stop.");
    let info = {}; try { info = await F.api("/api/ai/voice"); } catch { /* ok */ }
    if (info.whisper || info.openai) { try { return await record(); } catch (e) { if (e.message !== "no-engine") return F.toast(e.name === "NotAllowedError" ? "Fathom needs permission to use the microphone. Allow it in the window, or in Windows Settings > Privacy > Microphone." : e.message); } }
    return browserListen();
  }
  async function openMic(deviceId) {
    const id = deviceId === undefined ? P.mic : deviceId, base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
    if (id) { try { return await navigator.mediaDevices.getUserMedia({ audio: { ...base, deviceId: { exact: id } } }); } catch (e) { if (e.name !== "OverconstrainedError" && e.name !== "NotFoundError") throw e; F.toast("The microphone you picked is not connected; using the default one."); } }
    return navigator.mediaDevices.getUserMedia({ audio: base });
  }
  async function record() {
    const stream = await openMic();
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : {}), chunks = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    const ctx = new (window.AudioContext || window.webkitAudioContext)(), src = ctx.createMediaStreamSource(stream), an = ctx.createAnalyser(); an.fftSize = 1024; src.connect(an);
    const buf = new Float32Array(an.fftSize); let floor = 0.008, spoke = false, last = 0, t0 = performance.now(), done = false, calib = 0;
    const finish = () => { if (done) return; done = true; clearInterval(iv); try { rec.stop(); } catch { /* ok */ } };
    const iv = setInterval(() => {
      an.getFloatTimeDomainData(buf); let sum = 0; for (const x of buf) sum += x * x; const rms = Math.sqrt(sum / buf.length), now = performance.now();
      if (now - t0 < 500) { floor = Math.max(floor, Math.min(rms, 0.03)); calib++; return; }
      const thr = Math.max(0.018, floor * 2.6);
      if (rms > thr) { spoke = true; last = now; }
      if ((spoke && now - last > 1600) || (!spoke && now - t0 > 9000) || now - t0 > 90000) finish();
    }, 80);
    V.listening = true; V.stopRec = finish; setStatus("listening");
    const stopped = new Promise((res) => { rec.onstop = res; }); rec.start(250);
    await stopped;
    clearInterval(iv); stream.getTracks().forEach((t) => t.stop()); try { ctx.close(); } catch { /* ok */ }
    V.listening = false; V.stopRec = null;
    if (!spoke) { setStatus(""); if (!V.hands) F.toast("I did not hear anything."); return; }
    setStatus("thinking");
    const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
    const data = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(blob); });
    const slowHint = setTimeout(() => { if (V.status === "thinking") F.toast("Still working on it. The first time, Fathom downloads its speech model (about 500 MB, once). Later it takes a second or two."); }, 10000);
    try {
      const r = await post("/api/ai/transcribe", { data, lang: V.lang === "auto" ? "" : V.lang });
      clearTimeout(slowHint);
      if (r.language) V.spoken = r.language;
      if (!r.text) { setStatus(""); return F.toast("I could not make out any words. Try again a little closer to the microphone."); }
      setStatus(""); ai.submit(r.text, { voice: true, lang: r.language || V.lang });
    } catch (e) { clearTimeout(slowHint); setStatus(""); if (e.message === "no-engine") throw e; F.toast(e.message); }
  }
  function browserListen() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return F.toast("Voice typing needs a speech engine. Run Fathom.bat repair once (it installs the offline speech engine, which understands about 99 languages), or save an OpenAI key in Assistant settings.");
    const r = new SR(); r.lang = V.lang === "auto" ? (navigator.language || "en-US") : V.lang; r.interimResults = true; r.continuous = false;
    let finalText = "";
    r.onresult = (e) => { let t = ""; for (const x of e.results) t += x[0].transcript; if (e.results[e.results.length - 1].isFinal) finalText = t; for (const ui of V.uis) ui.chat.ta.value = t; };
    r.onerror = (e) => { V.listening = false; setStatus(""); F.toast(e.error === "not-allowed" ? "Fathom needs permission to use the microphone." : e.error === "no-speech" ? "I did not hear anything." : "Voice typing stopped: " + e.error); };
    r.onend = () => { V.listening = false; V.stopRec = null; setStatus(""); if (finalText.trim()) { for (const ui of V.uis) ui.chat.ta.value = ""; V.spoken = r.lang.split("-")[0]; ai.submit(finalText.trim(), { voice: true, lang: r.lang }); } };
    V.listening = true; V.stopRec = () => r.stop(); setStatus("listening"); r.start();
  }

  // ---------------------------------------------------------------- watching the screen
  async function setWatch(on) {
    try {
      const s = await post("/api/ai/screen", { on });
      if (on && !s.available) { F.toast(s.why || "The screen cannot be captured here."); on = false; await post("/api/ai/screen", { on: false }); }
    } catch (e) { F.toast(e.message); on = false; }
    V.watch = on; clearInterval(V.timer);
    if (on) { frame(); V.timer = setInterval(frame, 2500); }
    redraw();
  }
  async function frame() {
    if (!V.watch || document.hidden) return;
    try { const r = await post("/api/ai/screen/frame"); for (const ui of V.uis) { ui.thumb.src = r.data; ui.thumb.hidden = false; } } catch (e) { V.watch = false; clearInterval(V.timer); redraw(); F.toast(e.message); }
  }

  // ---------------------------------------------------------------- the buttons
  function setStatus(s) { V.status = s; redraw(); }
  function redraw() {
    const lab = { listening: "Listening… speak now (click to stop)", thinking: "Understanding what you said…", speaking: "Speaking… (click to silence)" }[V.status] || "";
    for (const ui of V.uis) {
      ui.mic.classList.toggle("rec", V.status === "listening"); ui.mic.textContent = V.status === "listening" ? "⏹ Stop listening" : "🎤 Talk";
      ui.state.textContent = lab; ui.state.hidden = !lab;
      ui.watch.classList.toggle("on", V.watch); ui.watch.textContent = V.watch ? "👁 Watching your screen" : "👁 Watch my screen";
      ui.thumb.hidden = !V.watch; if (!V.watch) ui.thumb.removeAttribute("src");
      ui.say.classList.toggle("on", V.speak); ui.hands.classList.toggle("on", V.hands);
    }
  }
  ai.decorators.push((chat) => {
    const mic = h("button", { class: "btn small vbtn", onclick: () => listen() }, "🎤 Talk");
    F.tip(mic, "Press and speak. Fathom writes what you said in the chat, the assistant answers, and reads the answer aloud. Works in almost every language. Stops by itself when you pause.");
    const watch = h("button", { class: "btn small vbtn", onclick: () => setWatch(!V.watch) }, "👁 Watch my screen");
    F.tip(watch, "Lets the assistant SEE your screen while you use the app, so it can tell what you are doing, what is on screen and what to click. Off until you press it; nothing is saved. Press again to stop.");
    const say = h("button", { class: "btn small vbtn", onclick: () => { V.speak = !V.speak; F.save("ai.speak", V.speak); if (!V.speak) stopSpeaking(); redraw(); } }, "🔊 Read answers aloud");
    F.tip(say, "On: the assistant speaks its answers (in the language it answers in) as well as writing them. Off: text only.");
    const hands = h("button", { class: "btn small vbtn", onclick: () => { V.hands = !V.hands; if (V.hands) { V.speak = true; F.save("ai.speak", true); if (!V.listening && !ai.isRunning()) listen(); } else if (V.listening) V.stopRec && V.stopRec(); redraw(); } }, "🗣 Hands-free");
    F.tip(hands, "A back-and-forth conversation: after the assistant finishes speaking, it listens to you again by itself. Press again to end.");
    const lang = h("select", { class: "vlang", onchange: () => { V.lang = lang.value; F.save("ai.lang", V.lang); } }, ...LANGS.map(([v, t]) => h("option", { value: v, text: t })));
    lang.value = V.lang;
    F.tip(lang, "The language you speak. \"Any language\" lets Fathom work it out by itself (needs the offline speech engine or an OpenAI key); pick one if it keeps guessing wrong. The assistant always answers in the language you use.");
    const state = h("span", { class: "vstate", hidden: true }), thumb = h("img", { class: "vthumb", hidden: true, alt: "What the assistant sees of your screen" });
    F.tip(thumb, "This is what the assistant sees of your screen right now.");
    chat.voiceRow.append(mic, say, hands, watch, lang, state, thumb);
    V.uis.push({ chat, mic, watch, say, hands, state, thumb }); redraw();
  });
  // speak each finished answer
  ai.listeners.push((ev, replay) => {
    if (replay) return;
    if (ev.type === "user") { V.buf = ""; }
    else if (ev.type === "text") V.buf += ev.delta;
    else if (ev.type === "done") { const t = V.buf; V.buf = ""; if (V.speak && t.trim()) speak(t); else afterSpeech(); }
  });
  ai.beforeStop = stopSpeaking;
  F.onBoot = F.onBoot || [];
  F.onBoot.push(async () => { try { const s = await post("/api/ai/screen"); if (s.on) { V.watch = true; V.timer = setInterval(frame, 2500); redraw(); } } catch { /* ok */ } });

  // ---------------------------------------------------------------- settings: microphone and voice
  async function micList() {
    try { const t = await navigator.mediaDevices.getUserMedia({ audio: true }); t.getTracks().forEach((x) => x.stop()); } catch { /* labels stay hidden */ }
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === "audioinput" && d.deviceId !== "communications");
  }
  async function meter(bar, msg, secs) {
    let stream; try { stream = await openMic(); } catch (e) { msg.textContent = e.name === "NotAllowedError" ? "Fathom is not allowed to use the microphone. Allow it in Windows Settings > Privacy > Microphone." : "Could not open the microphone: " + e.message; return; }
    const ctx = new (window.AudioContext || window.webkitAudioContext)(), an = ctx.createAnalyser(); an.fftSize = 1024; ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize); let peak = 0; const t0 = performance.now(); msg.textContent = "Say something…";
    await new Promise((res) => { const iv = setInterval(() => { an.getFloatTimeDomainData(buf); let sum = 0; for (const x of buf) sum += x * x; const rms = Math.sqrt(sum / buf.length); peak = Math.max(peak, rms); bar.style.width = Math.min(100, Math.round(rms * 600)) + "%"; if (performance.now() - t0 > secs * 1000) { clearInterval(iv); res(); } }, 60); });
    stream.getTracks().forEach((t) => t.stop()); try { ctx.close(); } catch { /* ok */ } bar.style.width = "0";
    msg.textContent = peak > 0.02 ? "✔ The microphone works: I could hear you." : "I heard almost nothing. Pick another microphone, speak closer, or raise its volume in Windows Settings > System > Sound > Input.";
  }
  (ai.settingsCards = ai.settingsCards || []).push(() => {
    const sel = h("select", {}); const hint = h("p", { class: "hint" }), bar = h("div", { class: "vmeter-bar" }), meterBox = h("div", { class: "vmeter" }, bar);
    const fill = async () => {
      let list = []; try { list = await micList(); } catch { /* ok */ }
      sel.replaceChildren(h("option", { value: "", text: "Default microphone (what Windows uses)" }), ...list.map((d, i) => h("option", { value: d.deviceId, text: d.label || "Microphone " + (i + 1) })));
      sel.value = list.some((d) => d.deviceId === P.mic) ? P.mic : ""; if (P.mic && sel.value !== P.mic) { P.mic = ""; savePrefs(); }
      hint.textContent = list.length ? `${list.length} microphone${list.length === 1 ? "" : "s"} found.` : "No microphone found. Plug one in, then press Refresh.";
    };
    sel.onchange = () => { P.mic = sel.value; savePrefs(); F.toast("Microphone saved"); };
    F.tip(sel, "Which microphone Fathom listens to when you press Talk. \"Default\" follows Windows' own choice.");
    const refresh = h("button", { class: "btn small", onclick: fill }, "Refresh"); F.tip(refresh, "Look for microphones again (after plugging one in).");
    const msg = h("p", { class: "hint" });
    const test = h("button", { class: "btn small", onclick: async () => { test.disabled = true; await meter(bar, msg, 5); test.disabled = false; } }, "Test microphone"); F.tip(test, "Shows a live level bar for 5 seconds while you speak, so you can see this microphone works.");
    const vsel = h("select", {}); const vfill = async () => {
      const vs = "speechSynthesis" in window ? await voices() : [];
      vsel.replaceChildren(h("option", { value: "", text: "Automatic (best voice for the language of the answer)" }), ...vs.map((v) => h("option", { value: v.name, text: `${v.name} (${v.lang})` })));
      vsel.value = vs.some((v) => v.name === P.voice) ? P.voice : "";
    };
    vsel.onchange = () => { P.voice = vsel.value; savePrefs(); }; F.tip(vsel, "The voice that reads answers aloud. Automatic picks a natural voice that matches the language of the answer. Add more languages in Windows Settings > Time & language > Speech.");
    const rate = h("input", { type: "range", min: "0.6", max: "1.6", step: "0.1", value: String(P.rate) }), rateLab = h("span", { text: P.rate + "×" });
    rate.oninput = () => { P.rate = +rate.value; rateLab.textContent = P.rate + "×"; savePrefs(); }; F.tip(rate, "How fast the voice speaks. 1× is normal.");
    const eng = h("select", {}, h("option", { value: "auto", text: "Automatic: the window's voices, then the computer's own voice" }), h("option", { value: "server", text: "Always use the computer's own voice (or my voice service)" })); eng.value = P.engine;
    eng.onchange = () => { P.engine = eng.value; savePrefs(); }; F.tip(eng, "If you hear nothing in Automatic, choose the second option. It uses Windows' built-in voices (or the OpenAI voice if you set one above).");
    const sample = h("input", { type: "text", value: "Hello! This is how I will read my answers to you.", style: "flex:1;min-width:200px" }); F.tip(sample, "Type a sentence in any language to hear it.");
    const say = h("button", { class: "btn small", onclick: () => speak(sample.value) }, "▶ Test voice"); F.tip(say, "Reads the sentence aloud with the settings above.");
    const sayPC = h("button", { class: "btn small", onclick: () => { F.toast("Reading aloud on this PC's speakers… If you hear nothing, right-click the speaker icon by the clock, open the Volume mixer, and check the level of Python."); speak(sample.value, true); } }, "▶ Test the computer's voice"); F.tip(sayPC, "Reads it with Windows' own voice, to check sound works even when the window's voices do not.");
    fill(); vfill();
    return h("div", { class: "card-box" }, h("h3", { text: "Microphone and voice" }), h("p", { class: "hint", text: "These are saved on this computer. Talk, hands-free mode and spoken answers use them." }),
      h("div", { class: "row", style: "gap:8px;align-items:center;flex-wrap:wrap" }, h("label", {}, "Microphone ", sel), refresh, test), meterBox, hint, msg,
      h("div", { class: "row", style: "gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px" }, h("label", {}, "Voice ", vsel), h("label", {}, "Speed ", rate, rateLab), h("label", {}, "Engine ", eng)),
      h("div", { class: "row", style: "gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px" }, sample, say, sayPC));
  });
  F.voice = { listen, speak, setWatch, prefs: P };
})();
