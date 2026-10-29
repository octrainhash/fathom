/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* Toolbox: quick text and data helpers, barcode maker, PDF watermark remover, searchable PDF, background remover, subtitle fixer and burner,
   Workflows (save a chain of steps) and Watch folders (run them on every new file). Everything runs on this computer. */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;
  const post = (p, b) => api(p, { method: "POST", body: b });
  const reg = (t, build) => F.addTool({ ...t, el: F.makeView(t.id), build: (sec) => { const v = F.standardView(t.id, { files: !!t.files, output: !!t.output, hint: t.hint }); sec.replaceWith(v.sec); F.tools.find((x) => x.id === t.id).el = v.sec; v.sec.classList.add("on"); build(v.main, v); } });
  const opt = (v, l, tip, s) => ({ v, l, tip, s });
  const sel = (id, label, options, value, tip, extra = {}) => ({ id, type: "select", label, options, value, tip, ...extra });
  const chk = (id, label, value, tip, extra = {}) => ({ id, type: "check", label, value, tip, ...extra });
  const num = (id, label, value, tip, extra = {}) => ({ id, type: "number", label, value, tip, ...extra });
  const when = (id, ...vals) => (v) => vals.includes(v[id]);

  // ====================================================================== quick helpers (no file needed)
  function quickTool(cfg) {
    reg({ id: cfg.id, group: "toolbox", icon: cfg.icon, label: cfg.label, blurb: cfg.blurb, files: false, output: false }, (main) => {
      main.append(F.titleBlock(cfg.title || cfg.label, cfg.sub));
      const input = h("textarea", { rows: cfg.rows || 8, placeholder: cfg.placeholder || "Type or paste here…", spellcheck: "false", style: "width:100%;font-family:ui-monospace,Consolas,monospace" });
      F.tip(input, cfg.inputTip || "What you type here is only used on this computer.");
      const specs = cfg.fields || [];
      let timer = 0, form;
      const out = h("textarea", { rows: cfg.outRows || 8, readonly: "readonly", style: "width:100%;font-family:ui-monospace,Consolas,monospace" });
      const note = h("p", { class: "hint" }); const table = h("table", { class: "info-table", style: "margin-top:8px" });
      const img = h("div");
      const run = async () => {
        const v = form ? form.values() : {};
        const o = cfg.options ? cfg.options(v) : v;
        if (cfg.needsText !== false && !input.value.trim() && !cfg.generator) { out.value = ""; table.replaceChildren(); note.textContent = ""; return; }
        try {
          const r = await post("/api/toolbox/quick", { kind: cfg.tool, text: input.value, options: o });
          out.value = r.result || ""; note.textContent = r.note || ""; note.style.color = r.ok === false ? "var(--bad, #c0392b)" : "";
          table.replaceChildren(...(r.info || []).map((row) => h("tr", {}, h("th", { text: String(row[0]), style: "text-align:left;padding:2px 14px 2px 0;font-weight:600" }), h("td", { text: String(row[1]), style: "word-break:break-all" }))));
          cfg.after && cfg.after(r, img);
        } catch (e) { out.value = ""; note.textContent = e.message; table.replaceChildren(); }
      };
      const soon = () => { clearTimeout(timer); timer = setTimeout(run, 250); };
      form = F.form(specs, soon);
      if (cfg.presets) main.append(h("div", { class: "row", style: "gap:6px;flex-wrap:wrap;margin-bottom:8px" }, h("span", { class: "hint", text: "Quick settings:" }), ...cfg.presets.map((p) => h("button", { class: "btn small", tip: p.tip, onclick: () => { for (const [k, v] of Object.entries(p.set)) form.set(k, v); run(); } }, p.l))));
      const showInput = cfg.needsText !== false || (cfg.generator && cfg.nameInput);
      if (showInput) main.append(h("div", { class: "card-box" }, h("div", { class: "lab", text: cfg.inputLabel || "Your text" }), input));
      const go = h("button", { class: "primary", tip: "Do it now." }, cfg.run || (cfg.generator ? "Make more" : "Go"));
      const cp = h("button", { class: "btn", tip: "Copy the result to the clipboard.", onclick: () => F.copy(out.value) }, "Copy result");
      const use = h("button", { class: "btn", tip: "Move the result up into the box above, to work on it some more.", onclick: () => { input.value = out.value; run(); } }, "Use as input");
      main.append(h("div", { class: "row", style: "margin:10px 0;gap:8px" }, go, cp, ...(showInput ? [use] : [])), h("div", { class: "card-box" }, h("div", { class: "lab", text: "Result" }), out, note, table, img));
      if (specs.length) main.append(h("h3", { text: "Options", style: "margin:14px 0 6px" }), h("div", { class: "card-box" }, form.el));
      input.addEventListener("input", soon); go.onclick = run;
      if (cfg.generator) setTimeout(run, 100);
    });
  }
  const CHARSETS = [opt("utf-8", "UTF-8 (normal)"), opt("utf-16", "UTF-16"), opt("latin-1", "Latin-1 (Western Europe)"), opt("cp1252", "Windows-1252"), opt("ascii", "ASCII")];

  quickTool({ id: "jsontool", tool: "json", icon: "🧾", label: "JSON", blurb: "Tidy, check, shrink or sort JSON, with the exact line and column of any mistake.",
    sub: "Paste JSON to make it neat, check that it is valid, squeeze it into one line, or sort the keys. If something is wrong Fathom shows exactly where. Nothing leaves this computer.", placeholder: '{"name": "Fathom", "tools": [1, 2, 3]}', rows: 10, outRows: 12,
    fields: [sel("mode", "What to do", [opt("pretty", "Make it neat", "Adds line breaks and indentation so it is easy to read."), opt("minify", "Squeeze it small", "Removes every space and line break."), opt("validate", "Only check it", "Tells you whether it is valid, and shows a summary.")], "pretty", "The main job."),
      sel("indent", "Indentation", [opt("2", "2 spaces"), opt("4", "4 spaces"), opt("tab", "Tabs"), opt("1", "1 space"), opt("8", "8 spaces")], "2", "How far each level moves in.", { show: when("mode", "pretty") }),
      chk("sort", "Sort the keys A to Z", false, "Puts every object's keys in alphabetical order, at every level."), chk("lenient", "Forgive small mistakes", false, "Accepts // comments, /* comments */, trailing commas and 'single quotes'."),
      chk("ascii", "Write non-English letters as \\u codes", false, "Makes the result plain ASCII.")] });

  quickTool({ id: "encode", tool: "base64", icon: "🔤", label: "Base64", blurb: "Turn text into Base64 and back, in standard or web-safe form.",
    sub: "Base64 turns any text into safe letters and digits, and back. Paste a data: address or a long wrapped block and Fathom copes.",
    fields: [sel("mode", "Direction", [opt("encode", "Text → Base64"), opt("decode", "Base64 → text")], "encode", "Which way to convert."), sel("charset", "Text character set", CHARSETS, "utf-8", "How letters are stored as bytes. UTF-8 is right for almost everything."),
      chk("urlsafe", "Web-safe form (- and _ instead of + and /)", false, "Used in web addresses and tokens.", { show: when("mode", "encode") }), chk("nopad", "Leave off the = padding", false, "Some systems want it removed.", { show: when("mode", "encode") }),
      num("wrap", "Break lines every … characters (0 = never)", 0, "76 is common for emails.", { min: 0, max: 200, show: when("mode", "encode") })] });

  quickTool({ id: "urltool", tool: "url", icon: "🔗", label: "Web address", blurb: "Encode, decode or take apart a web address and its parameters.",
    sub: "Make text safe to put in a web address, undo it, or split a full address into its host, path and every parameter.", placeholder: "https://example.com/search?q=hello world&page=2",
    fields: [sel("mode", "What to do", [opt("encode", "Encode"), opt("decode", "Decode"), opt("parse", "Take it apart")], "encode", "Pick a job."), sel("scope", "Encode", [opt("component", "Everything (for one value)", "Also escapes / ? & = :"), opt("full", "A whole address (keep / ? & =)", "Leaves the address's own symbols alone."), opt("form", "Form style (spaces become +)")], "component", "How much to escape.", { show: when("mode", "encode") }),
      chk("plus", "Read + as a space", true, "Used in web forms.", { show: when("mode", "decode") })] });

  quickTool({ id: "genid", tool: "uuid", icon: "🆔", label: "Unique IDs", blurb: "Make UUIDs: random, time-ordered, or from a name, as many as you like.", generator: true, nameInput: true, needsText: false, rows: 3,
    sub: "Make unique identifiers. Version 4 is random, 7 sorts by time (good for databases), 1 uses the clock, 3 and 5 always give the same ID for the same name.",
    fields: [sel("version", "Kind", [opt("4", "Version 4 – random"), opt("7", "Version 7 – time-ordered"), opt("1", "Version 1 – clock based"), opt("5", "Version 5 – from a name (SHA-1)"), opt("3", "Version 3 – from a name (MD5)"), opt("nil", "Nil – all zeros")], "4", "Which kind of ID."),
      num("count", "How many", 5, "Up to 1000.", { min: 1, max: 1000, show: (v) => !["3", "5", "nil"].includes(v.version) }), text("name", "The name", "", "Used for version 3 and 5. You can also type it in the box above.", (v) => ["3", "5"].includes(v.version)),
      sel("ns", "Name group", [opt("dns", "Domain name"), opt("url", "Web address"), opt("oid", "OID"), opt("x500", "X.500")], "dns", "The group the name belongs to.", { show: (v) => ["3", "5"].includes(v.version) }),
      chk("upper", "CAPITAL letters", false, "Upper case hex digits."), chk("nohyphen", "No hyphens", false, "32 characters in a row."), chk("braces", "Wrap in { }", false, "Windows registry style.")] });
  function text(id, label, value, tip, show) { return { id, type: "text", label, value, tip, show }; }

  quickTool({ id: "passgen", tool: "password", icon: "🔑", label: "Passwords", blurb: "Make strong passwords, passphrases or PINs with a strength meter. Made here, never sent anywhere.", generator: true, needsText: false, rows: 2,
    sub: "Passwords are made with your computer's secure random generator and are never sent anywhere. Pick random characters, a passphrase of words, or a PIN.",
    presets: [{ l: "Strong (20)", set: { mode: "chars", length: 20, lower: true, upper: true, digits: true, symbols: true } }, { l: "Easy to type", set: { mode: "words", words: 4, sep: "-" } }, { l: "Wi-Fi style (16, no symbols)", set: { mode: "chars", length: 16, symbols: false, noambig: true } }, { l: "PIN (6)", set: { mode: "pin", length: 6 } }, { l: "Maximum (64)", set: { mode: "chars", length: 64, symbols: true } }],
    fields: [sel("mode", "Kind", [opt("chars", "Random characters"), opt("words", "Passphrase of words"), opt("pin", "PIN (digits)")], "chars", "What sort of password."),
      num("length", "Length", 20, "How many characters.", { min: 3, max: 256, show: (v) => v.mode !== "words" }), num("words", "Number of words", 5, "More words = stronger.", { min: 2, max: 20, show: when("mode", "words") }),
      text("sep", "Between words", "-", "A dash, space, dot…", when("mode", "words")), chk("capital", "Capitalise each word", false, "", { show: when("mode", "words") }), chk("digit", "Add a number at the end", false, "", { show: when("mode", "words") }),
      chk("lower", "a-z", true, "Small letters.", { show: when("mode", "chars") }), chk("upper", "A-Z", true, "Capital letters.", { show: when("mode", "chars") }), chk("digits", "0-9", true, "Digits.", { show: when("mode", "chars") }), chk("symbols", "Symbols", true, "! @ # $ …", { show: when("mode", "chars") }),
      text("custom", "Extra characters to allow", "", "Anything else you want in the mix.", when("mode", "chars")), chk("noambig", "Skip look-alikes (O 0 l 1 I)", false, "Easier to read aloud or copy by hand.", { show: when("mode", "chars") }),
      chk("each", "Use every kind at least once", true, "Guarantees one of each ticked kind.", { show: when("mode", "chars") }), num("count", "How many to make", 5, "", { min: 1, max: 200 })] });

  quickTool({ id: "whentool", tool: "time", icon: "🕒", label: "Dates & times", blurb: "Epoch timestamps to dates and back, time zones, week numbers, and adding or subtracting time.", rows: 2, placeholder: "now   or   1793222873   or   2026-10-29 14:30",
    sub: "Type a date, a time, an epoch number (seconds, milliseconds or more) or the word now. See it in many forms and in any time zone, and move it forward or back.",
    fields: [text("tz_in", "Your date is in time zone", "UTC", "For dates without a zone. Examples: UTC, Asia/Karachi, America/New_York, Europe/London.", () => true), text("zones", "Show also in (comma separated)", "UTC,local,Asia/Karachi,America/New_York,Europe/London,Asia/Tokyo", "Time zone names.", () => true),
      num("add", "Move it by", 0, "Use a negative number to go back.", { min: -1000000000, max: 1000000000 }), sel("unit", "Unit", ["seconds", "minutes", "hours", "days", "weeks"].map((x) => opt(x, x)), "days", "")] });

  quickTool({ id: "hashtext", tool: "hash", icon: "#️⃣", label: "Hash & HMAC", blurb: "Hash text with MD5, SHA-1, SHA-2, SHA-3 or BLAKE2, or sign it with a secret key (HMAC).",
    sub: "Get the checksum of any text with many algorithms at once, or add a secret key to make an HMAC. Paste a known value in 'Expected' to see whether it matches.",
    fields: [{ id: "algos", type: "multi", label: "Algorithms", value: ["md5", "sha1", "sha256", "sha512"], options: ["md5", "sha1", "sha224", "sha256", "sha384", "sha512", "sha3_224", "sha3_256", "sha3_384", "sha3_512", "blake2b", "blake2s"].map((a) => opt(a, a.toUpperCase().replace("_", "-"))), tip: "Tick as many as you like." },
      { id: "key", type: "password", label: "Secret key (leave empty for a plain hash)", value: "", tip: "With a key the result is an HMAC." }, sel("form", "Show as", [opt("hex", "Lowercase hex"), opt("upper", "Uppercase hex"), opt("base64", "Base64")], "hex", ""),
      sel("charset", "Text character set", CHARSETS, "utf-8", "How the text becomes bytes."), text("expect", "Expected value (to compare)", "", "Paste a value you were given to check it matches.", () => true)] });

  quickTool({ id: "mdtool", tool: "markdown", icon: "📝", label: "Markdown → web page", blurb: "Turn Markdown into clean HTML: headings, tables, task lists, code blocks, contents list, or a whole page.", rows: 12, outRows: 12,
    sub: "Write Markdown on top and get HTML below. Supports headings, bold, italics, links, pictures, lists, task lists, tables, quotes and code blocks.", placeholder: "# Title\n\nSome **bold** text and a [link](https://example.com).\n\n- item one\n- [x] done",
    fields: [chk("page", "Make a complete web page", false, "Adds the html, head and a little tidy style."), text("title", "Page title", "Document", "", (v) => v.page), chk("toc", "Add a contents list", false, "Links to every heading."), chk("raw", "Keep HTML written in the text", false, "Off = any < is shown as text (safer).")] });

  quickTool({ id: "readtool", tool: "readability", icon: "📖", label: "Reading level", blurb: "How easy your writing is to read: grade level, reading time, long sentences, most-used words.", rows: 10, run: "Check",
    sub: "Paste your writing to see Flesch, Flesch-Kincaid, Gunning Fog, SMOG, Coleman-Liau and ARI scores, reading and speaking time, and the words you use most.", fields: [] });

  quickTool({ id: "texttool", tool: "text", icon: "🧹", label: "Text tools", blurb: "Change case, sort and clean lines, remove duplicates, find and replace (with patterns), count, extract emails or links.", rows: 10, outRows: 10,
    sub: "A bench of small text jobs. Pick one, and the result appears below as you type.",
    fields: [sel("op", "What to do", [opt("case", "Change case"), opt("sort", "Sort lines"), opt("dedupe", "Remove duplicate lines"), opt("clean", "Clean up spaces and quotes"), opt("replace", "Find and replace"), opt("extract", "Pull out emails, links, numbers…"), opt("number", "Number the lines"), opt("reverse", "Reverse"), opt("slug", "Make web-friendly names"), opt("count", "Count words and letters")], "case", "Pick a job."),
      sel("case", "Make it", [opt("upper", "UPPER CASE"), opt("lower", "lower case"), opt("title", "Title Case"), opt("sentence", "Sentence case"), opt("swap", "sWAP cASE"), opt("camel", "camelCase"), opt("pascal", "PascalCase"), opt("snake", "snake_case"), opt("kebab", "kebab-case"), opt("constant", "CONSTANT_CASE"), opt("dot", "dot.case")], "upper", "", { show: when("op", "case") }),
      chk("reverse", "Backwards (Z to A)", false, "", { show: when("op", "sort") }), chk("numeric", "By the number in each line", false, "", { show: when("op", "sort") }), chk("unique", "Also drop repeats", false, "", { show: (v) => v.op === "sort" || v.op === "extract" }), chk("ignorecase", "Ignore capitals", true, "", { show: (v) => v.op === "sort" || v.op === "dedupe" }),
      chk("trim", "Ignore spaces at the ends", true, "", { show: when("op", "dedupe", "clean") }), chk("spaces", "Squeeze repeated spaces", true, "", { show: when("op", "clean") }), chk("blank", "Squeeze repeated blank lines", true, "", { show: when("op", "clean") }),
      chk("quotes", "Straighten curly quotes and dashes", false, "", { show: when("op", "clean") }), chk("nonascii", "Remove accents and symbols", false, "", { show: when("op", "clean") }), chk("tabs", "Tabs to 4 spaces", false, "", { show: when("op", "clean") }),
      text("find", "Find", "", "", when("op", "replace")), text("repl", "Replace with", "", "", when("op", "replace")), chk("regex", "Find is a pattern (regular expression)", false, "", { show: when("op", "replace") }), chk("case", "Match capitals exactly", false, "", { show: when("op", "replace") }),
      sel("kind", "Pull out", [opt("email", "Email addresses"), opt("url", "Web links"), opt("number", "Numbers"), opt("hashtag", "#hashtags"), opt("ip", "IP addresses"), opt("date", "Dates")], "email", "", { show: when("op", "extract") }),
      num("start", "Start at", 1, "", { show: when("op", "number") }), text("sep", "After the number", ". ", "", when("op", "number")), sel("rmode", "Reverse", [opt("lines", "The order of lines"), opt("chars", "The letters in each line"), opt("words", "The words in each line")], "lines", "", { show: when("op", "reverse") })] });

  quickTool({ id: "numtool", tool: "base", icon: "🔢", label: "Number bases", blurb: "Decimal, hexadecimal, binary and octal at a glance, with the bytes and the matching character.", rows: 2, placeholder: "255   or   0xFF   or   0b1010",
    sub: "Type a number and see it in every base.", fields: [sel("from", "The number is", [opt("auto", "Detect (0x, 0b, 0o prefixes)"), opt("dec", "Decimal"), opt("hex", "Hexadecimal"), opt("bin", "Binary"), opt("oct", "Octal")], "auto", "")] });

  quickTool({ id: "colortool", tool: "color", icon: "🎨", label: "Colour converter", blurb: "Hex, RGB, HSL, HSV and CMYK together, with contrast checks for readable text.", rows: 2, placeholder: "#1b3a8c   or   rgb(27, 58, 140)   or   hsl(220, 68%, 32%)",
    sub: "Type a colour in any form and get all of them, plus how well black or white text reads on it.", fields: [], after: (r, img) => { img.replaceChildren(h("div", { style: `height:46px;border-radius:8px;margin-top:10px;border:1px solid #8884;background:${r.result}` })); } });

  quickTool({ id: "lorem", tool: "lorem", icon: "📄", label: "Placeholder text", blurb: "Lorem ipsum filler as words, sentences or paragraphs, optionally as HTML.", generator: true, needsText: false, rows: 2, outRows: 12,
    sub: "Dummy text for layouts and mock-ups. A seed gives the same text every time.", fields: [sel("unit", "Make", [opt("paragraphs", "Paragraphs"), opt("sentences", "Sentences"), opt("words", "Words")], "paragraphs", ""), num("count", "How many", 3, "", { min: 1, max: 200 }),
      chk("start", 'Begin with "Lorem ipsum"', true, ""), chk("html", "Wrap paragraphs in <p>", false, "", { show: when("unit", "paragraphs") }), text("seed", "Seed (optional)", "", "Same seed, same text.", () => true)] });

  // ====================================================================== file tools
  const field = (fn) => fn;
  const BARCODE_KINDS = [opt("code128", "Code 128", "Any text. The best all-round choice."), opt("code39", "Code 39", "Capitals, digits and - . $ / + %"), opt("ean13", "EAN-13", "Shop products. 12 digits (the 13th is added)."), opt("ean8", "EAN-8", "Small products. 7 digits."), opt("upca", "UPC-A", "US products. 11 digits."), opt("itf", "Interleaved 2 of 5", "Digits for cartons.")];
  const barcodeLook = () => [num("scale", "Bar thickness", 3, "Pixels per thinnest bar.", { min: 1, max: 20 }), num("height", "Height", 90, "Pixels.", { min: 20, max: 600 }), num("quiet", "Blank space at the sides", 10, "In thin-bar widths. Scanners need at least 10.", { min: 0, max: 40 }),
    { id: "fg", type: "color", label: "Bar colour", value: "#000000", tip: "Keep it dark for scanners." }, { id: "bg", type: "color", label: "Background", value: "#ffffff", tip: "Keep it light for scanners." }, chk("label", "Print the number under the bars", true, ""), num("fontsize", "Number size", 14, "", { min: 8, max: 60, show: (v) => v.label }),
    { id: "formats", type: "multi", label: "Save as", value: ["png", "svg"], options: [opt("png", "PNG picture"), opt("svg", "SVG (sharp at any size)"), opt("jpg", "JPEG picture"), opt("pdf", "PDF")], tip: "Pick one or more." }];
  F.addTool({ id: "barcode", group: "toolbox", icon: "▮▯", label: "Barcode maker", blurb: "Make Code 128, Code 39, EAN-13, EAN-8, UPC-A or ITF barcodes, one per line, as PNG, SVG, JPEG or PDF.", el: F.makeView("barcode"),
    build: (sec) => {
      const view = F.standardView("barcode", { output: true, files: false }); sec.replaceWith(view.sec); F.tools.find((x) => x.id === "barcode").el = view.sec; view.sec.classList.add("on");
      const main = view.main; main.append(F.titleBlock("Barcode maker", "Type one value per line to make one barcode for each. The check digit is added for you on shop barcodes. Every barcode type here was tested with an independent scanner program."));
      const txt = h("textarea", { rows: 5, placeholder: "FATHOM-0001\nFATHOM-0002", style: "width:100%;font-family:ui-monospace,Consolas,monospace" }); const form = F.form([sel("kind", "Type", BARCODE_KINDS, "code128", "Which barcode system."), ...barcodeLook()], () => preview());
      const prev = h("div", { style: "margin-top:10px;overflow:auto" }); const msg = h("p", { class: "hint" }); let t = 0;
      const preview = () => { clearTimeout(t); t = setTimeout(async () => { const v = form.values(); if (!txt.value.trim()) { prev.replaceChildren(); msg.textContent = ""; return; } try { const r = await post("/api/toolbox/barcode/preview", { kind: v.kind, text: txt.value, options: v }); prev.replaceChildren(h("img", { src: r.image, style: "max-width:100%;background:#fff;border:1px solid #8884;border-radius:6px" })); msg.textContent = r.shown && r.shown !== txt.value.split("\n")[0].trim() ? "Printed as: " + r.shown : ""; } catch (e) { prev.replaceChildren(); msg.textContent = e.message; } }, 250); };
      txt.addEventListener("input", preview);
      main.append(h("div", { class: "card-box" }, h("div", { class: "lab", text: "Values (one per line)" }), txt, msg, prev), h("div", { class: "card-box" }, form.el));
      const go = h("button", { class: "primary", tip: "Saves every barcode to the folder chosen under Where results go." }, "Save barcodes"); const host = h("div"); const panel = new F.JobPanel(host, { noun: "barcode", onDone: () => { go.disabled = false; } });
      main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
      go.onclick = async () => { const v = form.values(); try { go.disabled = true; const out = F.outputBody(); const r = await post("/api/toolbox/barcode", { kind: v.kind, text: txt.value, options: v, output: out.mode === "beside" ? { mode: "folder", dir: "" } : out }); panel.start(r.job); } catch (e) { go.disabled = false; F.toast(e.message); } };
    } });

  const WM = () => [sel("mode", "How to find the watermark", [opt("auto", "Find it for me", "Looks for text and pictures that repeat on most pages, plus stamps and watermark layers."), opt("words", "By its words", "You type the watermark's words."), opt("annots", "Stamps and layers only", "Removes stamp/watermark notes and hidden watermark layers."), opt("images", "Repeated pictures", "Removes pictures that appear on most pages (logos, faint images).")], "auto", "Pick the method that matches your PDF."),
    { id: "words", type: "textarea", label: "Watermark words (one per line)", value: "", rows: 3, tip: "Every place these words appear is removed.", show: when("mode", "words") }, num("share", "Counts as a watermark if it is on at least … % of pages", 60, "Lower finds more, but may remove real repeated text such as headers.", { min: 20, max: 100, show: when("mode", "auto", "images") }),
    chk("annots", "Remove stamps and watermark notes", true, "", { show: when("mode", "auto", "annots", "words") }), chk("freetext", "Also remove text-box notes", false, "", { show: when("mode", "auto", "annots", "words") }), chk("layers", "Hide watermark layers", true, "", { show: when("mode", "auto", "annots", "words") }), chk("images", "Also remove repeated pictures", true, "", { show: when("mode", "auto") })];
  F.jobTool({ id: "watermark", group: "edit", icon: "💧", label: "Remove watermark", blurb: "Take a text or picture watermark out of PDFs: found automatically, by its words, or as stamps and layers.",
    title: "Remove a PDF watermark", sub: "Works on PDFs that have a real watermark (text, a stamp, a layer or a repeated picture). A watermark that is baked into a scanned page cannot be separated from it. Your original is kept.", fields: WM(),
    endpoint: "/api/toolbox/watermark", body: (v) => F.baseBody(v, { options: v }), run: "Remove watermark", noun: "PDF", runTip: "Saves a new PDF and leaves the original alone." });

  const OCRF = () => [sel("dpi", "Reading quality", [opt("150", "Fast (150)"), opt("200", "Normal (200)"), opt("300", "Careful (300)"), opt("400", "Very careful (400)")], "200", "Higher reads small print better but is slower."),
    chk("skip", "Leave pages that already have text alone", true, "Only blank-of-text (scanned) pages are read."), sel("keep", "Page picture", [opt("image", "Use the scan picture", "Exactly what you scanned, plus hidden text."), opt("original", "Keep the original page", "Keeps vector pages exactly as they were.")], "image", ""), sel("quality", "Picture size", [opt("high", "Keep full quality"), opt("small", "Smaller file")], "high", "", { show: when("keep", "image") }), chk("title", "Fill in the title if missing", true, "")];
  F.jobTool({ id: "ocrpdf", group: "convert", icon: "🔍", label: "Searchable PDF", blurb: "Turn scanned PDFs into PDFs you can search and copy text from, keeping the pages looking the same.",
    title: "Make scanned PDFs searchable", sub: "Fathom reads the words on each scanned page and hides them behind it, so you can search, select and copy text while the page still looks exactly like the scan.", fields: OCRF(),
    endpoint: "/api/toolbox/ocrpdf", body: (v) => F.baseBody(v, { options: v }), run: "Make searchable", noun: "PDF" });

  const BG = () => [sel("method", "How", [opt("grabcut", "Find the main subject", "Works on most photos with a clear subject near the middle."), opt("color", "Remove one colour", "Best for plain backgrounds such as white or green screens.")], "grabcut", ""),
    num("margin", "Space around the subject (%)", 6, "The subject should sit inside the box that is left after trimming this much from each edge.", { min: 1, max: 40, show: when("method", "grabcut") }), num("passes", "Effort", 5, "More passes = more careful, slower.", { min: 1, max: 12, show: when("method", "grabcut") }), chk("largest", "Keep only the biggest piece", true, "Drops specks.", { show: when("method", "grabcut") }),
    { id: "color", type: "color", label: "Background colour (empty = detect from the edges)", value: "", tip: "Leave empty to use the colour found around the picture's edge.", show: when("method", "color") }, num("tolerance", "How different counts as 'not background'", 30, "Higher removes more shades near the background colour.", { min: 1, max: 120, show: when("method", "color") }), chk("connected", "Only remove background touching the edges", true, "Keeps same-coloured parts inside the subject.", { show: when("method", "color") }),
    num("grow", "Grow (+) or shrink (−) the cut-out by", 0, "Pixels.", { min: -20, max: 20 }), num("feather", "Soften the edge", 1.5, "Pixels of blur on the edge.", { min: 0, max: 10, step: 0.5 }), chk("crop", "Trim empty space around the subject", false, ""), num("pad", "Leave this much around it", 10, "Pixels.", { min: 0, max: 200, show: (v) => v.crop }),
    sel("fill", "Behind the subject", [opt("none", "Transparent"), opt("color", "A solid colour")], "none", ""), { id: "fillcolor", type: "color", label: "Colour", value: "#ffffff", tip: "", show: when("fill", "color") }, sel("format", "Save as", [opt("png", "PNG"), opt("webp", "WebP (smaller)"), opt("jpg", "JPEG (needs a solid colour)")], "png", "")];
  F.jobTool({ id: "nobg", group: "edit", icon: "✂", label: "Remove background", blurb: "Cut the background out of pictures: find the subject or remove one colour. Transparent PNG or any colour behind.",
    title: "Remove picture backgrounds", sub: "Works fully offline with no downloads. Use 'Find the main subject' for photos and 'Remove one colour' for logos, products on white, and green screens.", fields: BG(),
    endpoint: "/api/toolbox/nobg", body: (v) => F.baseBody(v, { options: v }), run: "Remove background", noun: "picture" });

  const SUB = () => [num("shift", "Move all subtitles later (+) or earlier (−) by", 0, "Seconds. For example 2.5 or −1.", { step: 0.1 }), text("sync1", "…or stretch: first line should appear at (seconds)", "", "Use with the box below to fix subtitles that drift.", () => true), text("sync2", "…and the last line should appear at (seconds)", "", "", () => true),
    text("fps_from", "Frame rate it was made for", "", "For example 23.976. Leave empty if not needed.", () => true), text("fps_to", "Frame rate of your video", "", "For example 25.", () => true),
    chk("html", "Remove formatting tags (<i>, <b>, <font>)", true, ""), chk("sdh", "Remove hearing-impaired notes [door slams] and speaker names", false, ""), chk("ads", "Remove adverts and credits", true, "Lines mentioning download sites."), chk("dedupe", "Merge repeated lines", true, ""), chk("overlap", "Fix overlapping times", true, ""),
    num("mindur", "Shortest time on screen (seconds, 0 = leave)", 0, "", { step: 0.1 }), num("maxdur", "Longest time on screen (seconds, 0 = leave)", 0, "", { step: 0.5 }), num("wrap", "Wrap lines at … characters (0 = leave)", 0, "42 is the usual choice.", { min: 0, max: 100 }),
    sel("format", "Save as", [opt("srt", "SRT"), opt("vtt", "WebVTT"), opt("txt", "Plain text")], "srt", ""), sel("charset", "The file is written in", [opt("auto", "Detect automatically"), opt("utf-8", "UTF-8"), opt("cp1252", "Western Windows"), opt("cp1250", "Central European"), opt("cp1251", "Cyrillic"), opt("cp1253", "Greek"), opt("cp1254", "Turkish"), opt("cp1256", "Arabic"), opt("cp1255", "Hebrew"), opt("gbk", "Chinese (GBK)"), opt("big5", "Chinese (Big5)"), opt("shift_jis", "Japanese"), opt("euc-kr", "Korean")], "auto", "Fixes garbled letters."),
    sel("encoding", "Save the result as", [opt("utf8", "UTF-8 (best)"), opt("bom", "UTF-8 with marker (older TVs)"), opt("latin1", "Western Windows")], "utf8", "")];
  F.jobTool({ id: "subs", group: "edit", icon: "💬", label: "Fix subtitles", blurb: "Shift or stretch timing, fix garbled letters, clean tags and notes, convert between SRT, VTT and text.",
    title: "Fix subtitle files", sub: "Choose .srt, .vtt, .ass or .ssa files. Fathom reads the letters correctly, tidies them, and saves a fixed copy.", fields: SUB(),
    endpoint: "/api/toolbox/subs", body: (v) => F.baseBody(v, { options: v }), run: "Fix subtitles", noun: "subtitle file" });

  F.jobTool({ id: "burn", group: "edit", icon: "🎞", label: "Burn in subtitles", blurb: "Draw subtitles onto a video so they show everywhere. Choose size, colour, outline and position.",
    title: "Burn subtitles into a video", sub: "Add the videos on the left. Fathom uses a subtitle file with the same name beside each video, or the one you pick below.", fields: [text("subs", "Subtitle file (empty = same name as the video)", "", "Full path of an .srt, .vtt or .ass file.", () => true),
      num("size", "Text size", 22, "", { min: 8, max: 80 }), { id: "color", type: "color", label: "Text colour", value: "#ffffff", tip: "" }, { id: "outline", type: "color", label: "Outline colour", value: "#000000", tip: "" }, num("border", "Outline thickness", 2, "", { min: 0, max: 8 }),
      sel("pos", "Position", [opt("bottom", "Bottom"), opt("middle", "Middle"), opt("top", "Top")], "bottom", ""), num("margin", "Distance from the edge", 20, "", { min: 0, max: 200 }), num("crf", "Quality (lower = better, bigger)", 20, "14 to 32.", { min: 14, max: 32 })],
    endpoint: "/api/toolbox/burn", body: (v) => F.baseBody(v, { options: v }), run: "Burn in", noun: "video" });

  // ====================================================================== workflows and watch folders
  const TO = ["pdf", "docx", "xlsx", "pptx", "txt", "md", "html", "csv", "json", "png", "jpg", "webp", "avif", "gif", "bmp", "tiff", "svg", "ico", "mp4", "webm", "mkv", "mov", "gif", "mp3", "wav", "flac", "m4a", "ogg", "opus", "epub", "zip"];
  const STEP_FIELDS = { convert: () => [sel("to", "Convert to", [...new Set(TO)].map((x) => opt(x, x.toUpperCase())), "pdf", "The type each file becomes.")], ocrpdf: OCRF, watermark: WM, nobg: BG, subs: SUB };
  const LABELS = { convert: "Convert to another type", ocrpdf: "Make PDF searchable (OCR)", watermark: "Remove PDF watermark", nobg: "Remove picture background", subs: "Fix subtitles" };
  /** an editable list of steps: [{action, options}] */
  function stepEditor(initial = []) {
    const root = h("div"); const steps = []; 
    const add = (action = "convert", options = {}) => {
      const holder = h("div", { class: "card-box", style: "margin-bottom:8px" }); const n = steps.length + 1;
      const pick = h("select", {}, Object.entries(LABELS).map(([k, l]) => h("option", { value: k, text: l }))); pick.value = action;
      const body = h("div"); const rec = { pick, form: null, holder };
      const draw = () => { const specs = STEP_FIELDS[pick.value]().map((s) => (options[s.id] !== undefined && pick.value === action ? { ...s, value: options[s.id] } : s)); rec.form = F.form(specs); body.replaceChildren(rec.form.el); };
      pick.addEventListener("change", draw); draw();
      const del = h("button", { class: "btn small", tip: "Remove this step.", onclick: () => { steps.splice(steps.indexOf(rec), 1); holder.remove(); renum(); } }, "Remove");
      const title = h("b", { text: "" }); rec.title = title;
      holder.append(h("div", { class: "row", style: "gap:10px;align-items:center;margin-bottom:6px" }, title, pick, del), body); steps.push(rec); root.append(holder); renum();
    };
    const renum = () => steps.forEach((s, i) => (s.title.textContent = `Step ${i + 1}`));
    initial.forEach((s) => add(s.action, s.options || {}));
    const addBtn = h("button", { class: "btn", tip: "Add another step after the last one." }, "+ Add a step"); addBtn.onclick = () => add();
    return { el: h("div", {}, root, addBtn), get: () => steps.map((s) => ({ action: s.pick.value, options: s.form.values() })), set: (list) => { steps.length = 0; root.replaceChildren(); list.forEach((s) => add(s.action, s.options || {})); }, count: () => steps.length };
  }

  reg({ id: "workflow", group: "toolbox", icon: "⛓", label: "Workflows", blurb: "Chain steps (for example remove watermark → make searchable → convert) and run them on any files. Save your chains to reuse.", files: true, output: true }, (main) => {
    main.append(F.titleBlock("Workflows", "Build a chain of steps. Each step works on what the step before it made. Add your files on the left, press Run, and only the final results are kept. Save a chain to use it again."));
    const ed = stepEditor([{ action: "convert", options: {} }]); const nameBox = h("input", { type: "text", placeholder: "Name for this workflow", style: "min-width:220px" });
    const saved = h("select", {}); const refreshSaved = () => { const all = F.load("flows", {}); saved.replaceChildren(h("option", { value: "", text: "Saved workflows…" }), ...Object.keys(all).map((k) => h("option", { value: k, text: k }))); };
    saved.onchange = () => { const all = F.load("flows", {}); if (all[saved.value]) { nameBox.value = saved.value; ed.set(all[saved.value]); } };
    const save = h("button", { class: "btn", tip: "Remember this chain under the name on the left." }, "Save"); save.onclick = () => { const n = nameBox.value.trim(); if (!n) return F.toast("Give it a name first."); const all = F.load("flows", {}); all[n] = ed.get(); F.save("flows", all); refreshSaved(); saved.value = n; F.toast("Saved"); };
    const del = h("button", { class: "btn", tip: "Forget the chosen saved workflow." }, "Delete"); del.onclick = () => { const all = F.load("flows", {}); delete all[saved.value]; F.save("flows", all); refreshSaved(); };
    refreshSaved();
    main.append(h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-bottom:10px" }, saved, nameBox, save, del), ed.el);
    const go = h("button", { class: "primary", tip: "Runs the steps on the files in your list." }, "Run workflow"); const stop = h("button", { class: "btn", hidden: true }, "Stop"); const status = h("p", { class: "hint" }); const results = h("div");
    main.append(h("div", { class: "row", style: "margin-top:14px;gap:8px" }, go, stop), status, results);
    let fid = "", poll = 0;
    stop.onclick = () => post("/api/flow/cancel", { id: fid });
    go.onclick = async () => {
      if (!F.needFiles()) return; if (!ed.count()) return F.toast("Add a step first.");
      try { go.disabled = true; stop.hidden = false; results.replaceChildren(); const r = await post("/api/flow/run", { steps: ed.get(), paths: F.state.sources, output: F.outputBody() }); fid = r.flow;
        clearInterval(poll); poll = setInterval(async () => { try { const s = await api("/api/flow/" + fid); status.textContent = s.status === "running" ? `Working on step ${s.step} of ${s.of}…` : ""; if (s.status !== "running") { clearInterval(poll); go.disabled = false; stop.hidden = true;
          if (s.status === "done") { status.textContent = "Done. " + s.notes.join("  "); results.replaceChildren(h("ul", {}, ...s.outputs.slice(0, 50).map((p) => h("li", {}, h("a", { href: "#", text: F.baseName(p), tip: "Show in folder", onclick: (e) => { e.preventDefault(); post("/api/reveal", { path: p }); } }))))); } else status.textContent = s.error || "It did not finish."; } } catch (e) { clearInterval(poll); go.disabled = false; stop.hidden = true; status.textContent = e.message; } }, 900);
      } catch (e) { go.disabled = false; stop.hidden = true; F.toast(e.message); } };
  });

  reg({ id: "watch", group: "toolbox", icon: "👁", label: "Watch folders", blurb: "Pick a folder and Fathom does a job on every new file that lands in it: convert, make searchable, clean subtitles, and more.", files: false, output: false }, (main) => {
    main.append(F.titleBlock("Watch folders", "Fathom keeps an eye on a folder while it is open. When a new file appears (and has finished downloading or saving), the steps you set run on it and the results go to the output folder. Files already there are left alone unless you tick the box. Fathom has to be running for this to work."));
    const list = h("div"); const logBox = h("div", { class: "card-box" }); let rules = [];
    const draw = () => {
      list.replaceChildren(...rules.map((r, i) => h("div", { class: "card-box", style: "margin-bottom:8px" },
        h("div", { class: "row", style: "gap:10px;align-items:center;flex-wrap:wrap" },
          h("b", { text: r.name }), h("span", { class: "hint", text: r.folder }),
          h("span", { class: "hint", text: (r.exts ? r.exts + " files · " : "all files · ") + r.steps.map((s) => LABELS[s.action]).join(" → ") }),
          h("button", { class: "btn small", tip: r.enabled ? "Pause this watcher." : "Turn it back on.", onclick: async () => { r.enabled = !r.enabled; await saveAll(); } }, r.enabled ? "Pause" : "Resume"),
          h("button", { class: "btn small", onclick: async () => { rules.splice(i, 1); await saveAll(); } }, "Remove")))));
      if (!rules.length) list.append(h("p", { class: "hint", text: "No watched folders yet. Add one below." }));
    };
    const saveAll = async () => { try { rules = (await post("/api/watch", { rules })).rules; draw(); } catch (e) { F.toast(e.message); } };
    const load = async () => { try { const r = await api("/api/watch"); rules = r.rules; draw(); logBox.replaceChildren(h("h3", { text: "Recent activity" }), ...(r.log.length ? r.log.slice(0, 15).map((l) => h("div", { class: "hint", text: `${new Date(l.time * 1000).toLocaleTimeString()}  ${l.rule}: ${F.baseName(l.file)} – ${l.status}${l.note ? " (" + l.note + ")" : ""}` })) : [h("p", { class: "hint", text: "Nothing yet." })])); } catch { /* ignore */ } };
    const folder = h("input", { type: "text", placeholder: "Folder to watch", style: "flex:1;min-width:240px" }); const out = h("input", { type: "text", placeholder: "Results go to (empty = a 'Fathom output' folder inside it)", style: "flex:1;min-width:240px" });
    const pk = (box) => async () => { const p = await F.pickOne("folder"); if (p) box.value = p; };
    const form = F.form([text("name", "Name", "", "Just a label.", () => true), text("exts", "Only these file types (empty = all)", "", "For example: pdf, png, jpg", () => true), chk("subfolders", "Also watch folders inside it", false, ""), chk("existing", "Also process the files already there", false, "Normally only new files are processed.")]);
    const ed = stepEditor([{ action: "convert", options: {} }]);
    const addBtn = h("button", { class: "primary", tip: "Start watching." }, "Start watching this folder");
    addBtn.onclick = async () => { const v = form.values(); if (!folder.value.trim()) return F.toast("Choose a folder first."); if (!ed.count()) return F.toast("Add a step."); rules.push({ ...v, name: v.name || folder.value.split(/[\\/]/).filter(Boolean).pop(), folder: folder.value.trim(), outdir: out.value.trim(), steps: ed.get(), enabled: true }); folder.value = ""; await saveAll(); F.toast("Watching"); };
    main.append(h("h3", { text: "Watching now" }), list, logBox, h("h3", { text: "Add a watched folder", style: "margin-top:18px" }), h("div", { class: "card-box" },
      h("div", { class: "row", style: "gap:8px;flex-wrap:wrap" }, folder, h("button", { class: "btn small", onclick: pk(folder) }, "Choose…")), h("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:8px" }, out, h("button", { class: "btn small", onclick: pk(out) }, "Choose…")), form.el), h("h3", { text: "What to do with each new file" }), ed.el, h("div", { class: "row", style: "margin-top:12px" }, addBtn));
    load(); setInterval(() => { if (F.currentTool && F.currentTool.id === "watch") load(); }, 5000);
  });
})();
