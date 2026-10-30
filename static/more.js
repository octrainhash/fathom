/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* More tools: crop PDF pages, flatten a PDF, PDF to Markdown, make a PDF fillable, hide faces, meme maker,
   video to GIF, change speed, even out loudness, remove sound. Each one is a small form built with F.jobTool. */
(() => {
  "use strict";
  const F = window.Fathom; if (!F || !F.jobTool) return;
  const base = F.baseBody;
  const opt = (v, l, tip) => ({ v, l, tip });

  F.jobTool({ id: "pdfcrop", presets: [{ name: "Trim white margins", values: { mode: "auto", pad: "5", same: true } }, { name: "Tight crop, per page", values: { mode: "auto", pad: "2", same: false } }, { name: "Cut 1 cm off every side", values: { mode: "margins", unit: "cm", top: "1", bottom: "1", left: "1", right: "1" } }], group: "edit", icon: "✂️", label: "Crop PDF", blurb: "Cut the margins off PDF pages: by amounts you type, or let Fathom trim the white space by itself.",
    title: "Crop PDF pages", sub: "Cut a border off every page, or only the pages you choose. Or let Fathom find the printed area on each page and trim the empty white margin around it. The cut-off part is hidden, not erased.",
    fields: [
      { id: "mode", type: "select", label: "How", value: "auto", options: [opt("auto", "Trim the white margins by itself", "Finds where the writing and pictures are and cuts the empty border."), opt("margins", "Cut a set amount off each side", "You say how much to remove from the top, bottom, left and right.")], tip: "Choose how the crop is worked out." },
      { id: "pad", type: "text", label: "Keep a border of (mm)", value: "5", show: (v) => v.mode === "auto", tip: "A little white space left around the content so nothing touches the edge." },
      { id: "same", type: "check", label: "Same size on every page", value: true, show: (v) => v.mode === "auto", tip: "Uses one common window, so the pages do not jump in size when you flip through them." },
      { id: "unit", type: "select", label: "Unit", value: "mm", show: (v) => v.mode === "margins", options: [opt("mm", "Millimetres"), opt("cm", "Centimetres"), opt("in", "Inches"), opt("pt", "Points")], tip: "The unit for the four numbers." },
      { id: "top", type: "text", label: "Top", value: "0", show: (v) => v.mode === "margins", tip: "How much to cut off the top." },
      { id: "bottom", type: "text", label: "Bottom", value: "0", show: (v) => v.mode === "margins", tip: "How much to cut off the bottom." },
      { id: "left", type: "text", label: "Left", value: "0", show: (v) => v.mode === "margins", tip: "How much to cut off the left side." },
      { id: "right", type: "text", label: "Right", value: "0", show: (v) => v.mode === "margins", tip: "How much to cut off the right side." },
      { id: "pages", type: "text", label: "Which pages", value: "", placeholder: "all pages", tip: "Empty = every page. Or type numbers (1,3), ranges (5-8), 'odd', 'even' or 'end'." }],
    endpoint: "/api/tools/pdfcrop", body: (v) => base(v, { options: v }), run: "Crop", noun: "PDF" });

  F.jobTool({ id: "pdfflatten", group: "protect", icon: "🧱", label: "Flatten PDF", blurb: "Bake form fields and notes into the page so they cannot be changed any more.",
    title: "Flatten a PDF", sub: "Turns filled-in form fields, comments and stamps into plain page content. The result looks the same but nobody can edit or remove them. Good for sending a finished form.",
    fields: [{ id: "what", type: "select", label: "Flatten", value: "all", options: [opt("all", "Form fields and notes", "Both."), opt("forms", "Form fields only", "Keeps comments and highlights editable."), opt("notes", "Notes only", "Keeps form fields fillable.")], tip: "Choose what becomes part of the page." }],
    endpoint: "/api/tools/pdfflatten", body: (v) => base(v, { options: v }), run: "Flatten", noun: "PDF" });

  F.jobTool({ id: "pdfmarkdown", group: "convert", icon: "📝", label: "PDF to Markdown", blurb: "Turn a PDF into a clean Markdown file: headings, lists, tables and links kept.",
    title: "PDF to Markdown", sub: "Reads the text of a PDF and writes a Markdown (.md) file: headings from the font sizes, lists, bold and italic, links and tables. Page headers and footers that repeat are left out. For a scan, make a Searchable PDF first.",
    fields: [{ id: "tables", type: "check", label: "Turn tables into Markdown tables", value: true, tip: "Off: table text comes out as plain lines." },
      { id: "pages", type: "text", label: "Which pages", value: "", placeholder: "all pages", tip: "Empty = every page. Or type numbers (1,3), ranges (5-8), 'odd', 'even' or 'end'." }],
    endpoint: "/api/tools/pdfmarkdown", body: (v) => base(v, { options: v }), run: "Convert", noun: "PDF" });

  F.jobTool({ id: "pdffillable", group: "edit", icon: "📋", label: "Make fillable", blurb: "Find blank lines, empty boxes and check squares in a PDF and turn them into fields you can type in.",
    title: "Make a PDF fillable", sub: "Fathom looks for lines like ________, empty boxes and ☐ check squares and puts a real form field on each one. Then the PDF can be filled in any PDF reader, or with Fill a PDF form. Check the result: only things that look like blanks are found.",
    fields: [{ id: "checks", type: "check", label: "Check squares (☐ and [ ])", value: true, tip: "Adds a tick box on each one." },
      { id: "boxes", type: "check", label: "Empty rectangles", value: true, tip: "Adds a text field in each empty box, like the boxes of a printed form." }],
    endpoint: "/api/tools/pdffillable", body: (v) => base(v, { options: v }), run: "Make fillable", noun: "PDF" });

  F.jobTool({ id: "blurfaces", group: "protect", icon: "🫥", label: "Hide faces", blurb: "Find the faces in pictures and blur, pixelate or black them out. Runs on this PC.",
    title: "Hide faces in pictures", sub: "Finds faces with Fathom's own face finder and covers them: handy before sharing a photo of other people. Nothing is uploaded. Always look at the result: faces seen from the side, very small faces or faces turned away can be missed.",
    fields: [{ id: "style", type: "choice", label: "Cover with", value: "blur", options: [opt("blur", "Blur", "Soft blur, still looks natural."), opt("pixel", "Pixels", "Big square pixels."), opt("black", "Black", "A solid black shape. The strongest.")], tip: "How the faces are hidden. Black cannot be undone." },
      { id: "strength", type: "text", label: "Strength (1 to 10)", value: "6", show: (v) => v.style !== "black", tip: "Higher hides more." },
      { id: "grow", type: "text", label: "Extra around the face (0 to 1)", value: "0.25", tip: "0.25 covers a quarter more around each face, so hair and chin are hidden too." }],
    endpoint: "/api/tools/blurfaces", body: (v) => base(v, { options: v }), run: "Hide faces", noun: "picture" });

  F.jobTool({ id: "meme", group: "edit", icon: "😂", label: "Meme maker", blurb: "Put bold top and bottom text on a picture, like a meme.",
    title: "Meme maker", sub: "Adds white text with a black outline at the top and bottom of a picture. Works on one or many pictures at once. The original is not changed.",
    fields: [{ id: "top", type: "text", label: "Top text", value: "", placeholder: "when it works first time", tip: "Shown in capitals at the top." },
      { id: "bottom", type: "text", label: "Bottom text", value: "", placeholder: "and you do not know why", tip: "Shown in capitals at the bottom." },
      { id: "size", type: "text", label: "Text size (% of the picture height)", value: "10", tip: "4 is small, 20 is huge. Long text is made smaller automatically." }],
    endpoint: "/api/tools/meme", body: (v) => base(v, { options: v }), run: "Make memes", noun: "picture" });

  F.jobTool({ id: "gif", presets: [{ name: "Chat sticker (small)", values: { length: "4", fps: "10", width: "320", loop: true } }, { name: "Smooth and sharp", values: { length: "6", fps: "15", width: "640", loop: true } }, { name: "Tiny file", values: { length: "3", fps: "8", width: "240", loop: true } }], group: "convert", icon: "🎞️", label: "Video to GIF", blurb: "Turn a piece of a video into a small animated GIF.",
    title: "Video to GIF", sub: "Makes an animated GIF from a video: choose where it starts, how long it is and how big. Good colours: it works out the best palette for each clip.",
    fields: [{ id: "start", type: "text", label: "Start at (seconds)", value: "0", tip: "Where in the video the GIF begins." },
      { id: "length", type: "text", label: "Length (seconds)", value: "6", tip: "How long the GIF runs. Up to 120. Long GIFs are big." },
      { id: "fps", type: "text", label: "Pictures per second", value: "12", tip: "10 to 15 looks smooth enough. Fewer makes a smaller file." },
      { id: "width", type: "text", label: "Width (pixels)", value: "480", tip: "The height follows. 480 is good for chats, 320 for a small file." },
      { id: "loop", type: "check", label: "Repeat forever", value: true, tip: "Off: plays once." }],
    endpoint: "/api/tools/gif", body: (v) => base(v, { options: v }), run: "Make GIF", noun: "video" });

  F.jobTool({ id: "speed", presets: [{ name: "Slow motion (half)", values: { factor: "0.5", pitch: true } }, { name: "Watch faster (1.5x)", values: { factor: "1.5", pitch: true } }, { name: "Double speed", values: { factor: "2", pitch: true } }, { name: "Time-lapse (4x)", values: { factor: "4", pitch: false } }], group: "edit", icon: "⏩", label: "Change speed", blurb: "Make a video or song faster or slower, keeping the voice natural.",
    title: "Change speed", sub: "Plays a video or sound faster or slower. For speech, keeping the pitch means voices do not turn squeaky or deep.",
    fields: [{ id: "factor", type: "select", label: "Speed", value: "2", options: ["0.25", "0.5", "0.75", "1.25", "1.5", "2", "3", "4"].map((x) => opt(x, x + "x", x < 1 ? "Slow motion." : "Faster.")), tip: "1x is normal. 2x takes half as long." },
      { id: "pitch", type: "check", label: "Keep the voice pitch", value: true, tip: "Off: the pitch rises and falls with the speed, like a record." }],
    endpoint: "/api/tools/speed", body: (v) => base(v, { options: { factor: +v.factor, pitch: v.pitch } }), run: "Change speed", noun: "file" });

  F.jobTool({ id: "loudness", presets: [{ name: "Music streaming", values: { target: "-14" } }, { name: "Podcast / speech", values: { target: "-16" } }], group: "edit", icon: "🔊", label: "Even out volume", blurb: "Make quiet recordings louder and loud ones softer, to one steady level.",
    title: "Even out the volume", sub: "Brings the sound of a video or song to the same loudness that streaming sites use, without spoiling it. Good for lectures, phone recordings and mixed playlists.",
    fields: [{ id: "target", type: "select", label: "Target", value: "-16", options: [opt("-14", "Loud (-14)", "Like music streaming."), opt("-16", "Normal (-16)", "Good for speech and video."), opt("-23", "Quiet (-23)", "Broadcast standard.")], tip: "How loud the result should be." }],
    endpoint: "/api/tools/loudness", body: (v) => base(v, { options: { target: +v.target } }), run: "Even out", noun: "file" });

  F.jobTool({ id: "mute", group: "edit", icon: "🔇", label: "Remove sound", blurb: "Take the sound off a video without re-encoding it.",
    title: "Remove the sound from a video", sub: "Makes a copy of the video with no audio. The picture is copied as it is, so it is instant and loses no quality.",
    fields: [],
    endpoint: "/api/tools/mute", body: (v) => base(v, { options: {} }), run: "Remove sound", noun: "video" });
})();
