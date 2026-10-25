/* Convert (any file to any other supported type) and Resize (make files smaller or bigger). */
(() => {
  "use strict";
  const F = window.Fathom, h = F.h, api = F.api;

  // =========================================================== CONVERT
  const opt = {};   // option form values
  let plan = null, mapping = {}, groupCombos = [], allTypes = null, planSeq = 0, running = false;

  function optionForms() {
    const T = (a, b) => `${a}\n${b}`;
    const pic = F.form([
      { id: "image_quality", type: "range", label: "Picture quality", min: 1, max: 100, value: 90, fmt: (v) => v + "%", tip: "How much detail is kept when saving JPEG, WebP, AVIF and similar pictures.\nLow: small file, but blurry or blocky.\nHigh: sharp picture, bigger file." },
      { id: "resize", type: "select", label: "Change the picture size", value: "none", options: [
        { v: "none", l: "Keep the size", tip: "The picture keeps its width and height." },
        { v: "percent", l: "Shrink or grow by a percentage", tip: "Make the picture a percentage of its size, like 50% for half." },
        { v: "fit", l: "Fit inside a width and height", tip: "Make the picture fit inside a box you choose. It never gets stretched." }], tip: "Decides if the picture's width and height are changed while converting." },
      { id: "resize_percent", type: "number", label: "Percent", min: 1, max: 1000, value: 50, unit: "%", tip: "100 keeps the size. 50 makes it half as wide and half as tall. 200 makes it twice as big.", show: (v) => v.resize === "percent" },
      { id: "max_width", type: "number", label: "Biggest width", min: 0, value: 1920, unit: "pixels", tip: "The picture will not be wider than this. 0 means no limit.", show: (v) => v.resize === "fit" },
      { id: "max_height", type: "number", label: "Biggest height", min: 0, value: 1080, unit: "pixels", tip: "The picture will not be taller than this. 0 means no limit.", show: (v) => v.resize === "fit" },
      { id: "strip_metadata", type: "check", label: "Remove hidden details", small: "(location, camera, dates)", value: false, tip: "Photos can carry hidden details such as where and when they were taken.\nOn: those details are removed from the new picture, which is better for privacy.\nOff: the details are kept." },
      { id: "background", type: "text", label: "Background colour for see-through areas", value: "#ffffff", tip: "Some formats (like JPEG) cannot be see-through. Any see-through area is filled with this colour. White is #ffffff, black is #000000." },
      { id: "all_frames", type: "check", label: "Save every frame as its own picture", small: "(animations, multi-page TIFF)", value: false, tip: "On: an animated picture or a multi-page file becomes one picture per frame or page.\nOff: only the first frame is used (or the animation is kept if the new type supports it)." },
      { id: "ico_sizes", type: "text", label: "Icon sizes", value: "16,24,32,48,64,128,256", tip: "When making an icon file (.ico or .icns), these are the sizes packed inside it. Windows picks the one that fits." },
    ], null, { compact: true });
    const vid = F.form([
      { id: "video_quality", type: "select", label: "Video quality", value: "balanced", options: [
        { v: "high", l: "High", tip: "Looks almost the same as the original. The file is big." },
        { v: "balanced", l: "Balanced", tip: "A good mix of looks and size. Best for most videos." },
        { v: "small", l: "Small file", tip: "The smallest file. You may see blocks in fast scenes." }], tip: "How good the video looks compared to how big the file is." },
      { id: "video_crf", type: "number", label: "Quality number (advanced)", min: 0, max: 40, value: 0, tip: "A number you choose yourself instead of the quality choice above. Lower looks better and makes a bigger file: 16 is excellent, 23 is normal, 30 is small. 0 means use the quality choice." },
      { id: "video_copy", type: "check", label: "Only copy (no re-encode)", value: true, tip: "On: when you only change the file type (for example MP4 to MKV), the video and sound are moved into the new file as they are. Very fast and the same quality.\nIt is skipped automatically when you pick settings that change the picture (quality, size, frame rate, speed, turn, colours...). If copying fails, Fathom converts normally.\nOff: the video is always re-encoded, which takes much longer." },
      { id: "video_preset", type: "select", label: "Encoding speed", value: "medium", options: [
        { v: "ultrafast", l: "Fastest", tip: "Finishes soonest. The file is noticeably bigger for the same looks." },
        { v: "fast", l: "Fast", tip: "Quicker than normal. A somewhat bigger file." },
        { v: "medium", l: "Normal", tip: "The usual balance of speed and file size." },
        { v: "slow", l: "Slow, smaller file", tip: "Takes longer but gives a smaller file for the same looks." }], tip: "Only used when the video is re-encoded. Faster means a bigger file; slower means a smaller file." },
      { id: "video_gpu", type: "check", label: "Use the graphics card (NVIDIA)", value: false, tip: "On: the NVIDIA graphics card encodes the video, which is usually several times faster than the processor. Used for MP4, MKV, MOV and similar types. Fathom's built-in FFmpeg cannot do this: run Get-FFmpeg-GPU.bat once to install a full FFmpeg. If no card or no full FFmpeg is found, Fathom quietly uses the processor.\nOff: the processor does the work." },
      { id: "video_height", type: "select", label: "Video height", value: "0", options: [{ v: "0", l: "Keep the original" }, { v: "2160", l: "4K (2160)" }, { v: "1440", l: "1440" }, { v: "1080", l: "Full HD (1080)" }, { v: "720", l: "HD (720)" }, { v: "480", l: "480" }, { v: "360", l: "360" }, { v: "240", l: "240" }], tip: "Makes the video smaller in pixels, which makes the file much smaller. It is never made bigger than the original." },
      { id: "fps", type: "number", label: "Frames per second", min: 0, max: 240, value: 0, tip: "How many pictures per second the video shows.\n0: keep the original.\nLow (like 15): choppy but small.\nHigh (like 60): very smooth but bigger." },
      { id: "keep_audio", type: "check", label: "Keep the sound", value: true, tip: "On: the video keeps its sound.\nOff: the new video is silent, and smaller." },
      { id: "gif_fps", type: "number", label: "GIF speed", min: 1, max: 50, value: 12, unit: "frames/second", tip: "When making a GIF. Low: small file, jerky. High: smooth, big file." },
      { id: "gif_width", type: "number", label: "GIF width", min: 16, max: 4000, value: 480, unit: "pixels", tip: "When making a GIF. Low: small file. High: big, sharp file. GIFs get huge quickly." },
      { id: "frame_time", type: "number", label: "Take the picture at", min: 0, value: 0, unit: "seconds", tip: "When turning a video into a picture: which second of the video to take the picture from. 0 is the very start." },
      { id: "still_seconds", type: "number", label: "Make the video this long", min: 0.5, value: 5, unit: "seconds", tip: "When turning a picture into a video: how long the video lasts." },
    ], null, { compact: true });
    const padj = F.form([
      { id: "img_brightness", type: "range", label: "Brightness", min: 0, max: 200, value: 100, fmt: (v) => v + "%", tip: "100% leaves the light as it is.\nBelow 100%: darker.\nAbove 100%: brighter." },
      { id: "img_contrast", type: "range", label: "Contrast", min: 0, max: 200, value: 100, fmt: (v) => v + "%", tip: "How different the light and dark parts are.\n100%: unchanged. Lower: flat and grey. Higher: stronger and punchier." },
      { id: "img_saturation", type: "range", label: "Colour strength", min: 0, max: 300, value: 100, fmt: (v) => v + "%", tip: "100%: unchanged.\n0%: black and white.\nHigher: more vivid colours." },
      { id: "img_sharpness", type: "range", label: "Sharpness", min: 0, max: 300, value: 100, fmt: (v) => v + "%", tip: "100%: unchanged.\nBelow 100%: softer.\nAbove 100%: crisper edges (too much looks harsh)." },
      { id: "img_blur", type: "number", label: "Blur", min: 0, max: 50, value: 0, unit: "pixels", tip: "Softens the whole picture. 0 means no blur. A small number such as 2 is gentle; 20 is very blurry." },
      { id: "img_auto_levels", type: "check", label: "Fix the lighting automatically", value: false, tip: "Stretches the lightest and darkest parts to the full range. Helps grey, washed-out photos." },
      { id: "img_grayscale", type: "check", label: "Black and white", value: false, tip: "Removes all colour from the picture." },
      { id: "img_invert", type: "check", label: "Invert the colours", value: false, tip: "Swaps light and dark and every colour for its opposite, like a photo negative." },
      { id: "img_rotate", type: "select", label: "Turn the picture", value: "none", options: [{ v: "none", l: "Do not turn" }, { v: "90", l: "A quarter turn right (90°)" }, { v: "180", l: "Upside down (180°)" }, { v: "270", l: "A quarter turn left (270°)" }], tip: "Turns the picture while converting. Photos that are already rotated by the camera are straightened first." },
      { id: "img_flip", type: "select", label: "Mirror the picture", value: "none", options: [{ v: "none", l: "Do not mirror" }, { v: "h", l: "Left to right" }, { v: "v", l: "Top to bottom" }, { v: "both", l: "Both ways" }], tip: "Mirrors the picture. Left to right is like looking at it in a mirror." },
      { id: "img_aspect", type: "select", label: "Crop to a shape", value: "keep", options: [{ v: "keep", l: "Keep the shape" }, { v: "1:1", l: "Square (1:1)" }, { v: "4:3", l: "4:3" }, { v: "3:2", l: "3:2" }, { v: "16:9", l: "Wide (16:9)" }, { v: "9:16", l: "Tall phone (9:16)" }, { v: "2:3", l: "Portrait (2:3)" }], tip: "Cuts the picture evenly from the sides or the top and bottom to fit this shape. The middle is kept." },
      { id: "img_autotrim", type: "check", label: "Cut off empty edges", value: false, tip: "Removes margins that are all one colour (or fully see-through) around the picture, for example white space around a scan or a logo." },
      { id: "img_border", type: "number", label: "Add a border", min: 0, max: 2000, value: 0, unit: "pixels", tip: "Adds a frame of this width around the picture. 0 means none." },
      { id: "img_border_color", type: "color", label: "Border colour", value: "#ffffff", show: (v) => Number(v.img_border) > 0, tip: "The colour of the border." },
      { id: "img_palette", type: "select", label: "Number of colours", value: "0", options: [{ v: "0", l: "All colours" }, { v: "256", l: "256 colours" }, { v: "64", l: "64 colours" }, { v: "16", l: "16 colours" }, { v: "8", l: "8 colours" }, { v: "2", l: "2 colours (black and white dots)" }], tip: "Reduces the colours. In PNG and GIF files this makes a much smaller file; in other types it gives a poster-like look." },
      { id: "img_resample", type: "select", label: "How a resized picture is calculated", value: "lanczos", options: [{ v: "lanczos", l: "Sharp and smooth (best for photos)" }, { v: "bicubic", l: "Smooth" }, { v: "bilinear", l: "Soft" }, { v: "nearest", l: "Blocky (best for pixel art)" }], tip: "Used when the picture size is changed. Pixel art stays crisp with the blocky choice." },
      { id: "img_dpi", type: "select", label: "Print sharpness (DPI)", value: "0", options: [{ v: "0", l: "Leave as it is" }, { v: "72", l: "72 (screen)" }, { v: "150", l: "150" }, { v: "300", l: "300 (print)" }, { v: "600", l: "600" }], tip: "The print size note saved inside JPEG, PNG, TIFF and BMP files. It does not change the number of pixels." },
    ], null, { compact: true });
    const vlook = F.form([
      { id: "video_rotate", type: "select", label: "Turn the video", value: "none", options: [{ v: "none", l: "Do not turn" }, { v: "90", l: "A quarter turn right (90°)" }, { v: "180", l: "Upside down (180°)" }, { v: "270", l: "A quarter turn left (270°)" }], tip: "Turns the picture of the video, for example a phone video that was filmed sideways." },
      { id: "video_flip", type: "select", label: "Mirror the video", value: "none", options: [{ v: "none", l: "Do not mirror" }, { v: "h", l: "Left to right" }, { v: "v", l: "Top to bottom" }, { v: "both", l: "Both ways" }], tip: "Mirrors the video." },
      { id: "video_aspect", type: "select", label: "Change the shape", value: "keep", options: [{ v: "keep", l: "Keep the shape" }, { v: "16:9", l: "Wide (16:9)" }, { v: "4:3", l: "Old TV (4:3)" }, { v: "3:2", l: "3:2" }, { v: "1:1", l: "Square (1:1)" }, { v: "9:16", l: "Tall phone (9:16)" }, { v: "21:9", l: "Cinema (21:9)" }], tip: "Makes the video fit another screen shape." },
      { id: "video_aspect_mode", type: "select", label: "How to fit the new shape", value: "pad", show: (v) => v.video_aspect !== "keep", options: [{ v: "pad", l: "Add black bars (keeps everything)" }, { v: "crop", l: "Fill the screen (cuts the edges)" }], tip: "Black bars keep the whole picture. Fill the screen cuts the sides or the top and bottom." },
      { id: "video_deinterlace", type: "check", label: "Fix comb lines (old TV recordings)", value: false, tip: "Old TV and camcorder recordings can show fine horizontal lines on moving things. This cleans them up." },
      { id: "video_brightness", type: "range", label: "Brightness", min: -100, max: 100, value: 0, fmt: (v) => (v > 0 ? "+" : "") + v, tip: "0 leaves the light as it is. Negative: darker. Positive: brighter." },
      { id: "video_contrast", type: "range", label: "Contrast", min: 0, max: 200, value: 100, fmt: (v) => v + "%", tip: "100%: unchanged. Lower: flat. Higher: punchier." },
      { id: "video_saturation", type: "range", label: "Colour strength", min: 0, max: 200, value: 100, fmt: (v) => v + "%", tip: "100%: unchanged. 0%: black and white. Higher: more vivid." },
      { id: "video_grayscale", type: "check", label: "Black and white", value: false, tip: "Removes all colour from the video." },
      { id: "video_denoise", type: "check", label: "Reduce grain and noise", value: false, tip: "Smooths the speckles of a dark or old video. It makes the picture a little softer." },
      { id: "video_sharpen", type: "check", label: "Sharpen", value: false, tip: "Makes edges crisper. Too much can look harsh." },
    ], null, { compact: true });
    const cut = F.form([
      { id: "trim_start", type: "number", label: "Start at", min: 0, value: 0, unit: "seconds", step: "any", tip: "Keep the video or sound from this second on. 0 is the very start." },
      { id: "trim_end", type: "number", label: "Stop at", min: 0, value: 0, unit: "seconds", step: "any", tip: "Keep it up to this second. 0 means to the very end. Cutting a copied (not re-encoded) video starts at the nearest earlier key picture, so it can begin a moment early." },
      { id: "speed", type: "number", label: "Speed", min: 0.25, max: 4, value: 1, unit: "times", step: "any", tip: "1 is normal speed.\n2 is twice as fast, 0.5 is half speed. The sound speeds up or slows down with the picture, keeping its pitch.\nBetween 0.25 and 4." },
    ], null, { compact: true });
    const aud = F.form([
      { id: "audio_kbps", type: "select", label: "Sound quality", value: "192", options: [{ v: "64", l: "64 kbps (voice)", tip: "Small file. Fine for speech, poor for music." }, { v: "128", l: "128 kbps", tip: "Okay for casual listening." }, { v: "192", l: "192 kbps (good)", tip: "Good for most music." }, { v: "256", l: "256 kbps", tip: "Very good." }, { v: "320", l: "320 kbps (best)", tip: "The best for MP3 and similar. Big file." }], tip: "How much detail the sound keeps. Low numbers make smaller files that sound worse. High numbers sound better but are bigger. It does not apply to lossless types like FLAC or WAV." },
      { id: "audio_volume", type: "range", label: "Volume", min: 0, max: 500, value: 100, fmt: (v) => v + "%", tip: "100% leaves the loudness as it is.\n50% is quieter, 200% is twice as loud, 0% is silent. Loud settings are kept from crackling by a limiter. Works on sound files and on the sound of a video." },
      { id: "audio_normalize", type: "check", label: "Even out the loudness", value: false, tip: "Makes the sound a comfortable, steady loudness (the same level TV and streaming use). Good for videos with quiet speech and loud music." },
      { id: "audio_bass", type: "range", label: "Bass", min: -15, max: 15, value: 0, fmt: (v) => (v > 0 ? "+" : "") + v + " dB", tip: "Deep sounds. 0 leaves them. Positive: more boom. Negative: less." },
      { id: "audio_treble", type: "range", label: "Treble", min: -15, max: 15, value: 0, fmt: (v) => (v > 0 ? "+" : "") + v + " dB", tip: "High sounds. 0 leaves them. Positive: brighter. Negative: duller." },
      { id: "audio_denoise", type: "check", label: "Reduce background hiss", value: false, tip: "Lowers steady noise such as a fan or tape hiss. Strong settings can make voices sound a little thin." },
      { id: "audio_fade_in", type: "number", label: "Fade in", min: 0, value: 0, unit: "seconds", step: "any", tip: "The sound starts quiet and rises over this many seconds. 0 means no fade." },
      { id: "audio_fade_out", type: "number", label: "Fade out", min: 0, value: 0, unit: "seconds", step: "any", tip: "The sound fades to silence over the last seconds. 0 means no fade." },
      { id: "audio_track", type: "number", label: "Sound track to keep", min: 1, max: 20, value: 1, tip: "Some movies have several sound tracks (languages, commentary). 1 is the first. Fathom says if the file has fewer." },
      { id: "audio_silence", type: "check", label: "Cut long silences", value: false, tip: "Removes silent gaps longer than a second. Only used when the result is a sound file (not for videos, which would drift out of step)." },
      { id: "audio_channels", type: "select", label: "Channels", value: "keep", options: [{ v: "keep", l: "Keep as they are" }, { v: "mono", l: "Mono (one channel)" }, { v: "stereo", l: "Stereo (two channels)" }], tip: "Mono makes a smaller file and is fine for speech. Stereo keeps left and right." },
      { id: "audio_rate", type: "select", label: "Sample rate", value: "0", options: [{ v: "0", l: "Keep as it is" }, { v: "8000", l: "8000 Hz (phone)" }, { v: "22050", l: "22050 Hz" }, { v: "44100", l: "44100 Hz (CD)" }, { v: "48000", l: "48000 Hz (video)" }], tip: "How finely the sound is measured. Lower is smaller and duller. Keep it unless you need a specific rate." },
      { id: "whisper_model", type: "select", label: "Speech-to-text model", value: "base", options: [{ v: "tiny", l: "Tiny", tip: "Fastest. More mistakes." }, { v: "base", l: "Base", tip: "Balanced." }, { v: "small", l: "Small", tip: "Most accurate. Slower." }], tip: "Used when turning speech into text. A bigger model understands speech better but takes longer." },
    ], null, { compact: true });
    const doc = F.form([
      { id: "pdf_dpi", type: "select", label: "Page sharpness", value: "150", options: [{ v: "72", l: "72 (screen, small)", tip: "Small pictures. Text looks soft." }, { v: "150", l: "150 (normal)", tip: "Good for reading on screen." }, { v: "200", l: "200", tip: "Sharp." }, { v: "300", l: "300 (print)", tip: "Sharp enough to print. Large files." }, { v: "600", l: "600 (very sharp)", tip: "Huge files." }], tip: "When a page is turned into a picture. Low: small, soft pictures. High: big, sharp pictures." },
      { id: "pages", type: "pages", label: "Only these pages", value: "", tip: "Leave empty for every page. Type pages like 1-3,7, 'odd', 'last', 'every 2', or click the pages." },
      { id: "password", type: "password", label: "Password (if the file has one)", value: "", tip: "If the file is locked with a password (a protected PDF or ZIP), type it here so Fathom can open it. It is only used for this and is never saved." },
    ], null, { compact: true });
    return { pic, padj, vid, vlook, cut, aud, doc };
  }


  // ---- one-click presets (and ones you save yourself, kept in this browser)
  const PRESETS = [
    ["Older TV: 720p, plays almost anywhere", { video_height: "720", audio_channels: "stereo" }, "Pick MKV or MP4 as the type. Try a short clip on the TV first."],
    ["Phone or tablet: 1080p", { video_height: "1080" }, "Pick MP4 as the type."],
    ["Small file for WhatsApp or e-mail (480p)", { video_height: "480", video_quality: "small", video_preset: "fast", audio_kbps: "96" }, "Pick MP4 as the type."],
    ["Fix a sideways phone video", { video_rotate: "90" }, "Use 270 instead if it turns the wrong way."],
    ["Make it louder", { audio_volume: 200 }, "For sound files you can pick the same type (MP3 to MP3)."],
    ["Even loudness (TV, podcasts)", { audio_normalize: true }, "Quiet speech and loud music end up at a similar level."],
    ["Voice recording: small, clear, mono", { audio_channels: "mono", audio_kbps: "64", audio_normalize: true, audio_denoise: true }, "Pick MP3 or M4A as the type."],
    ["Music: best quality", { audio_kbps: "320" }, "Pick MP3 as the type."],
    ["GIF from a video", { gif_fps: 12, gif_width: 480 }, "Pick GIF as the type. Use 'Cut a part' to choose which seconds."],
    ["Photo for the web", { resize: "fit", max_width: 1920, max_height: 1080, image_quality: 82, strip_metadata: true }, "Pick JPG or WebP as the type."],
    ["Print-ready photo (300 DPI)", { image_quality: 95, img_dpi: "300" }, "Pick JPG, PNG or TIFF as the type."],
    ["Square picture for social media", { img_aspect: "1:1", resize: "fit", max_width: 1080, max_height: 1080 }, "Pick JPG or PNG as the type."],
    ["Smaller PNG: fewer colours", { img_palette: "64" }, "Pick PNG as the type. Good for logos and drawings, not photos."],
    ["Black and white", { img_grayscale: true, video_grayscale: true }, "Works on pictures and videos."],
  ];
  const PRESET_KEY = "fathom.convert.presets";
  const loadMine = () => { try { return JSON.parse(localStorage.getItem(PRESET_KEY) || "{}") || {}; } catch (e) { return {}; } };
  const saveMine = (m) => { try { localStorage.setItem(PRESET_KEY, JSON.stringify(m)); return true; } catch (e) { return false; } };

  function convertOptions() {
    const o = {};
    for (const f of Object.values(opt)) Object.assign(o, f.values());
    for (const k of ["video_height", "audio_kbps", "pdf_dpi", "audio_rate", "img_dpi"]) o[k] = parseInt(o[k] || 0, 10);
    o.pages = (o.pages || "").trim();
    return o;
  }

  function buildConvert(sec) {
    const view = F.standardView("convert", {
      sideExtra: (() => {
        const f = optionForms(); Object.assign(opt, f);
        const mk = (title, form, openIt) => { const d = h("details", { class: "block" }, h("summary", {}, h("h2", { text: title })), form.el); if (openIt) d.open = true; return d; };
        const defaults = {}; for (const form of Object.values(f)) Object.assign(defaults, form.values());
        const setAll = (vals) => { for (const form of Object.values(f)) for (const [k, v] of Object.entries(vals)) form.set(k, v); };
        const pickBox = (() => {
          const sel = h("select", { "aria-label": "Quick presets" });
          const hint = h("p", { class: "hint" });
          const fill = (keep) => {
            const mine = loadMine();
            sel.replaceChildren(h("option", { value: "", text: "Choose a preset…" }),
              h("optgroup", { label: "Ready-made" }, PRESETS.map((p, i) => h("option", { value: "b" + i, text: p[0] }))),
              Object.keys(mine).length ? h("optgroup", { label: "Yours" }, Object.keys(mine).map((n) => h("option", { value: "m" + n, text: n }))) : null,
              h("option", { value: "reset", text: "Reset every option" }));
            sel.value = keep || "";
          };
          fill();
          F.tip(sel, "Fills in the options below for a common job. It starts from the default options, then applies the preset. You can change anything afterwards.");
          sel.addEventListener("change", () => {
            const v = sel.value; if (!v) return;
            if (v === "reset") { setAll(defaults); hint.textContent = "All options are back to normal."; return; }
            const preset = v[0] === "b" ? PRESETS[+v.slice(1)] : [v.slice(1), loadMine()[v.slice(1)], "Your saved preset."];
            if (!preset || !preset[1]) return;
            setAll(defaults); setAll(preset[1]); hint.textContent = `${preset[0]}: applied. ${preset[2] || ""}`;
          });
          const name = h("input", { type: "text", placeholder: "Name for your own preset", "aria-label": "Preset name", maxlength: 40, style: "width:100%" });
          F.tip(name, "Type a name, then press Save to keep the options as they are now. They are stored in this browser and appear under 'Yours'.");
          const save = h("button", { class: "btn", type: "button", tip: "Saves the options you have set now under that name." }, "Save these options");
          save.onclick = () => {
            const n = name.value.trim(); if (!n) { F.toast("Type a name first."); return; }
            const now = {}; for (const form of Object.values(f)) Object.assign(now, form.values());
            const diff = Object.fromEntries(Object.entries(now).filter(([k, v]) => v !== "" && String(v) !== String(defaults[k])));
            const mine = loadMine(); mine[n] = diff;
            if (!saveMine(mine)) { F.toast("This browser would not keep it (private window?)."); return; }
            fill("m" + n); name.value = ""; hint.textContent = `Saved "${n}".`;
          };
          const del = h("button", { class: "btn", type: "button", tip: "Deletes the preset of yours that is chosen in the list." }, "Delete");
          del.onclick = () => {
            const v = sel.value; if (!v || v[0] !== "m") { F.toast("Choose one of your own presets first."); return; }
            const mine = loadMine(); delete mine[v.slice(1)]; saveMine(mine); fill(); hint.textContent = "Deleted.";
          };
          return h("div", { class: "block" }, h("h2", { text: "Quick presets" }), sel, h("div", { class: "row", style: "margin-top:8px" }, name, save, del), hint);
        })();
        return [pickBox, mk("Picture options", f.pic), mk("Picture adjustments (light, colour, turn)", f.padj), mk("Video and GIF options", f.vid), mk("Video look (turn, colour, clean-up)", f.vlook), mk("Cut a part and change speed", f.cut), mk("Sound options and adjustments", f.aud), mk("Pages and passwords", f.doc)];
      })(),
    });
    sec.replaceWith(view.sec); const main = view.main; F.tools.find((t) => t.id === "convert").el = view.sec;
    main.append(F.titleBlock("Convert", "Turn any file into any other type that makes sense. Add your files, then pick what each kind should become. Types that cannot work (like a video into a spreadsheet) are never offered."));

    // search bar + category drop-down: find a file type fast
    const catSel = h("select", { "aria-label": "Kind of file" }, h("option", { value: "", text: "All kinds" }), ...Object.entries(F.CAT_LABEL).map(([k, v]) => h("option", { value: k, text: v })));
    F.tip(catSel, "Narrows the list of file types to one kind, like Pictures or Audio. 'All kinds' shows every type.");
    const globalCombo = F.combo({ placeholder: "Search a file type, like png, pdf, mp3 or 'spreadsheet'…", tipText: "Type part of a file type's name (for example 'png', 'word' or 'audio') and pick it from the list. Choosing a type here sets it for every group of files below that can become it.", onPick: (o) => o && applyAll(o.id) });
    catSel.addEventListener("change", () => globalCombo.setCategory(catSel.value));
    const bar = h("div", { class: "card-box" },
      h("h3", { text: "Convert everything to…" }),
      h("p", { class: "hint", text: "Search for a file type, or pick a kind from the drop-down. It is applied to every group below that can become it. You can also choose per group." }),
      h("div", { class: "row", style: "margin-top:12px" }, globalCombo.el, catSel));
    const groupsBox = h("div", { id: "cv-groups" });
    const msg = h("p", { class: "hint", id: "cv-msg" });
    const go = h("button", { class: "primary", disabled: true, tip: "Starts converting. Your original files are never changed or deleted; the new files are saved with the same name and the new ending." }, "Convert");
    const runRow = h("div", { class: "row", style: "margin-top:16px" }, go, h("span", { class: "hint", id: "cv-count" }));
    const resultsHost = h("div");
    const panel = new F.JobPanel(resultsHost, { noun: "file" });
    main.append(bar, groupsBox, msg, runRow, resultsHost);

    const explorer = buildExplorer(); main.append(explorer);

    function applyAll(id) {
      if (!plan) { F.toast("Add some files first, then pick a type."); return; }
      let n = 0;
      for (const [i, g] of plan.groups.entries()) { if (g.fmt !== id && g.targets.some((t) => t.id === id)) { mapping[g.fmt] = id; groupCombos[i].set(id); n++; } }
      if (!n) F.toast("None of your files can become that type. See the list below for what they can become.");
      refreshGo();
    }
    function refreshGo() {
      const chosen = plan ? plan.groups.filter((g) => mapping[g.fmt]) : [];
      const files = chosen.reduce((s, g) => s + g.count, 0);
      go.disabled = !files || running; F.$("cv-count") && (F.$("cv-count").textContent = files ? `${files} file${files === 1 ? "" : "s"} will be converted` : "");
      go.textContent = files ? `Convert ${files} file${files === 1 ? "" : "s"}` : "Convert";
    }
    async function analyse() {
      const seq = ++planSeq;
      groupsBox.replaceChildren(); groupCombos = []; mapping = {}; plan = null; refreshGo();
      if (!F.state.sources.length) { msg.textContent = "Add files or folders on the left to begin."; return; }
      msg.textContent = "Looking at your files…";
      try {
        const p = await api("/api/convert/plan", { method: "POST", body: { paths: F.state.sources, recursive: true } });
        if (seq !== planSeq) return;
        plan = p; msg.textContent = `${p.files.toLocaleString()} file${p.files === 1 ? "" : "s"} (${F.fmtBytes(p.bytes)}) in ${p.groups.length} kind${p.groups.length === 1 ? "" : "s"}. Fathom checks what is inside each file, not just its ending.`;
        const union = new Map();
        for (const g of p.groups) for (const t of g.targets) if (!union.has(t.id)) union.set(t.id, t);
        globalCombo.setOptions([...union.values()].map((t) => ({ id: t.id, label: t.label, category: t.category, note: "." + t.id })));
        p.groups.forEach((g) => groupsBox.append(groupRow(g)));
        refreshGo();
      } catch (e) { msg.textContent = e.message; }
    }
    function groupRow(g) {
      const combo = F.combo({ placeholder: g.targets.length ? "Convert to… (search)" : "Cannot be converted", tipText: `Pick what ${g.label} files become. Only types that really work are listed. A note like 'via PDF' means it goes through an in-between type to get there.`,
        options: g.targets.map((t) => ({ id: t.id, label: t.label, category: t.category, note: t.via ? "via " + t.via : (t.notes[0] || "." + t.id), keywords: (t.notes || []).join(" ") })),
        onPick: (o) => { mapping[g.fmt] = o ? o.id : ""; refreshGo(); } });
      groupCombos.push(combo);
      const names = g.names.join(", ") + (g.count > g.names.length ? `, … (${g.count} files)` : "");
      return h("div", { class: "group-row" },
        h("div", { class: "what" }, h("b", {}, (F.CATEGORY_EMOJI[g.category] || "📄") + " " + g.label, h("span", { class: "pill", text: `${g.count} file${g.count === 1 ? "" : "s"} · ${F.fmtBytes(g.bytes)}` })), h("small", { text: names })),
        g.targets.length ? combo.el : h("span", { class: "hint", text: "Fathom has no way to convert this kind of file yet." }));
    }
    go.onclick = async () => {
      const chosen = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v));
      try {
        running = true; refreshGo();
        const r = await api("/api/convert/run", { method: "POST", body: { paths: F.state.sources, recursive: true, mapping: chosen, options: convertOptions(), output: F.outputBody() } });
        panel.onDone = () => { running = false; refreshGo(); };
        panel.start(r.job);
      } catch (e) { running = false; refreshGo(); F.toast(e.message); }
    };
    let t = null; F.onSourcesChanged = ((prev) => () => { prev && prev(); if (F.currentTool && F.currentTool.id === "convert") { clearTimeout(t); t = setTimeout(analyse, 250); } })(F.onSourcesChanged);
    F.tools.find((x) => x.id === "convert").refresh = analyse;
    analyse();
  }

  // every file type Fathom knows, with what each can become
  function buildExplorer() {
    const box = h("details", { class: "card-box" });
    box.append(h("summary", {}, h("b", { text: "Browse every file type Fathom can convert" })));
    const search = h("input", { type: "search", placeholder: "Search types…" }); F.tip(search, "Type part of a name or ending, like 'raw', 'word' or 'mp4', to find a type.");
    const cats = h("div", { class: "catbar" }); const grid = h("div", { class: "typegrid" }); const detail = h("div", { class: "hint", style: "margin-top:12px" });
    let cat = "", data = null;
    const draw = () => {
      cats.replaceChildren(...[["", "All"], ...Object.entries(F.CAT_LABEL)].map(([k, v]) => h("button", { "aria-pressed": cat === k, tip: k ? `Show only ${v.toLowerCase()} types.` : "Show every type.", onclick: () => { cat = k; draw(); } }, v)));
      const q = search.value.trim().toLowerCase();
      grid.replaceChildren(...data.readable.filter((t) => (!cat || t.category === cat) && (!q || `${t.id} ${t.label}`.toLowerCase().includes(q))).map((t) =>
        h("div", { class: "t", tip: "Click to see what this type can be converted into.", onclick: () => show(t) }, h("b", { text: t.label }), h("span", { text: "." + t.id }))));
    };
    async function show(t) {
      detail.textContent = "…";
      try {
        const r = await api("/api/formats/" + encodeURIComponent(t.id));
        detail.replaceChildren(h("b", { text: `${t.label} can become ${r.targets.length} types: ` }), r.targets.map((x) => x.label).join(", ") || "nothing yet. If this is a Word, Excel, PowerPoint, e-book or RAR type, it needs LibreOffice, Calibre or 7-Zip, which the Lite edition leaves out: run Fathom.bat full to add them.");
      } catch (e) { detail.textContent = e.message; }
    }
    box.addEventListener("toggle", async () => {
      if (!box.open || data) return;
      try { data = await api("/api/formats"); data = data.matrix; box.querySelector("summary b").textContent = `Browse all ${data.readable.length} file types Fathom can read (${data.writable.length} it can create)`; draw(); } catch (e) { detail.textContent = e.message; }
    });
    search.addEventListener("input", () => data && draw());
    box.append(h("div", { class: "row", style: "margin-top:12px" }, search), cats, grid, detail);
    return box;
  }

  F.addTool({ id: "convert", group: "convert", icon: "🔄", label: "Convert", blurb: "Turn any file into any other type that makes sense: pictures, video, audio, documents, spreadsheets, e-books, data, archives and more.", el: F.makeView("convert"), build: buildConvert, onShow: (t) => t.refresh && t.refresh() });

  // =========================================================== RESIZE
  function buildResize(sec) {
    const form = F.form([
      { id: "mode", type: "choice", label: "What do you want?", value: "smaller", options: [
        { v: "smaller", l: "Make smaller", s: "Save space or fit an email limit", tip: "Shrinks the files while keeping them usable: pictures are compressed, videos and sound get lighter, PDFs and documents lose weight." },
        { v: "bigger", l: "Make bigger", s: "Reach an exact size or enlarge", tip: "Makes files bigger: pictures and videos are enlarged, or filler data is added so a file reaches exactly the size you want (useful for tests)." }] },
      { id: "level", type: "choice", label: "How much?", value: "medium", show: (v) => v.mode === "smaller", options: [
        { v: "light", l: "Light", s: "Looks the same", tip: "A small saving. Quality stays as close to the original as possible." },
        { v: "medium", l: "Medium", s: "Best for most", tip: "A good saving. Quality stays good enough for screens and sharing." },
        { v: "strong", l: "Strong", s: "As small as it gets", tip: "The biggest saving. You may notice lower quality, especially in photos and video." }] },
      { id: "use_target", type: "check", label: "Aim for a specific size", value: false, tip: "On: Fathom tries to make each file exactly (or as close as possible to) the size you type.\nOff: it uses the 'How much?' level, or the enlarge factor." },
      { id: "target_value", type: "number", label: "Size", value: 5, min: 0, step: "any", show: (v) => v.use_target, tip: "For 'smaller' this is the biggest size each file may be. For 'bigger' it is the size each file should reach." },
      { id: "target_unit", type: "select", label: "Unit", value: "MB", show: (v) => v.use_target, options: [{ v: "KB", l: "KB (kilobytes)" }, { v: "MB", l: "MB (megabytes)" }, { v: "GB", l: "GB (gigabytes)" }], tip: "1 MB is about 1,000 KB. 1 GB is about 1,000 MB." },
      { id: "factor", type: "range", label: "Enlarge pictures and video by", min: 1.1, max: 16, step: 0.1, value: 2, fmt: (v) => v.toFixed(1) + "×", show: (v) => v.mode === "bigger" && !v.use_target, tip: "How many times bigger pictures and video are made (width and height).\nLow: slightly larger.\nHigh: much larger; the file grows very quickly." },
      { id: "zip_fallback", type: "check", label: "Zip files that cannot shrink on their own", value: true, show: (v) => v.mode === "smaller", tip: "Some files (like already-compressed formats) cannot be made smaller directly.\nOn: they are put inside a ZIP file, which may still save space.\nOff: those files are skipped." },
      { id: "exact", type: "check", label: "Add filler to hit the exact size", value: true, show: (v) => v.mode === "bigger" && v.use_target, tip: "On: after enlarging, filler bytes are added at the end so the file is exactly the size you typed. Most programs ignore the filler.\nOff: the file only gets as close as the enlarging allows." },
      { id: "fill", type: "select", label: "Kind of filler", value: "zero", show: (v) => v.mode === "bigger" && v.use_target, options: [
        { v: "zero", l: "Empty (fast)", tip: "Blank bytes. Very quick, and the filler shrinks to nothing if the file is zipped." },
        { v: "random", l: "Random data (looks real)", tip: "Random bytes that look like real data. Slower, and zipping the file will not make the filler disappear." }], tip: "What the extra bytes are made of when a file is padded up to an exact size." },
      { id: "replace", type: "check", label: "Replace the original files", value: false, show: () => F.state.output.mode === "beside", tip: "On: the new smaller or bigger file takes the original's place, and the original goes to the Recycle Bin so you can still get it back.\nOff: the original stays and the new file gets a name like 'photo (smaller).jpg'." },
    ], () => {});
    const view = F.standardView("resize", { sideExtra: [] });
    sec.replaceWith(view.sec); F.tools.find((t) => t.id === "resize").el = view.sec;
    const main = view.main;
    main.append(F.titleBlock("Resize files", "Make files smaller to save room or fit a limit, or bigger to reach an exact size. Works on pictures, video, audio, PDFs, documents, archives and more."));
    const presets = h("div", { class: "catbar" }, ["Email · 10 MB|10|MB", "WhatsApp · 16 MB|16|MB", "Web photo · 1 MB|1|MB", "Thumbnail · 200 KB|200|KB", "Upload form · 2 MB|2|MB"].map((s) => { const [l, v, u] = s.split("|"); return h("button", { tip: `Sets the size to ${v} ${u} each. Handy when a website or app says 'files must be under ${v} ${u}'.`, onclick: () => { form.set("mode", "smaller"); form.set("use_target", true); form.set("target_value", +v); form.set("target_unit", u); } }, l); }));
    main.append(h("div", { class: "card-box" }, h("h3", { text: "Choose how" }), form.el, h("div", { class: "field" }, h("div", { class: "lab", text: "Quick sizes" }), presets)));
    const go = h("button", { class: "primary", tip: "Starts resizing. By default your originals stay as they are and the new files get '(smaller)' or '(bigger)' in the name." }, "Resize");
    const host = h("div"); const panel = new F.JobPanel(host, { noun: "file" });
    main.append(h("div", { class: "row", style: "margin-top:16px" }, go), host);
    go.onclick = async () => {
      if (!F.needFiles()) return;
      const v = form.values();
      const spec = { mode: v.mode, level: v.level, factor: v.factor, zip_fallback: v.zip_fallback, exact: v.exact, fill: v.fill };
      if (v.use_target) { spec.target_value = v.target_value; spec.target_unit = v.target_unit; }
      if (v.replace && !confirm("Replace the original files? Each original goes to the Recycle Bin, so you can still restore it.")) return;
      try {
        go.disabled = true;
        const r = await api("/api/size/run", { method: "POST", body: { paths: F.state.sources, recursive: true, spec, output: F.outputBody(), replace: !!v.replace && F.state.output.mode === "beside" } });
        panel.onDone = () => { go.disabled = false; };
        panel.start(r.job);
      } catch (e) { go.disabled = false; F.toast(e.message); }
    };
    F.onSourcesChanged = ((prev) => () => { prev && prev(); form.refresh(); })(F.onSourcesChanged);
  }
  F.addTool({ id: "resize", group: "size", icon: "📏", label: "Smaller / bigger", blurb: "Make files smaller or bigger: by how much, or to an exact size like 'under 10 MB'.", el: F.makeView("resize"), build: buildResize });
})();
