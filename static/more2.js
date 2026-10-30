/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
/* More tools, part 2. PDF: header and footer, tables to Excel, clean hidden data, bookmarks, page size.
   Pictures: collage, frame, icon maker, see-through colour, animation, slideshow. Video and sound: crop, reverse, cut silence,
   fade, add music, watermark. Tables: tidy a CSV. Each one is a small form built with F.jobTool. */
(() => {
  "use strict";
  const F = window.Fathom; if (!F || !F.jobTool) return;
  const base = F.baseBody;
  const opt = (v, l, tip) => ({ v, l, tip });
  const PAGES = { id: "pages", type: "text", label: "Which pages", value: "", placeholder: "all pages", tip: "Empty = every page. Or type numbers (1,3), ranges (5-8), 'odd', 'even' or 'end'." };
  const ORDER = " The result follows the order of your list on the left (use the little arrows to change it).";

  F.jobTool({ id: "pdfheader", group: "edit", icon: "🔢", label: "Header & footer", blurb: "Add text to the top or bottom of every PDF page: titles, dates, page x of y, or Bates numbers.",
    title: "Header, footer and Bates numbers", sub: "Type text for the left, middle and right of the top and bottom of each page. Use {page}, {pages}, {file} and {date} and Fathom fills them in. A Bates prefix numbers every page (ACME-000001) for legal papers.",
    fields: [
      { id: "hl", type: "text", label: "Top left", value: "{file}", tip: "Shown at the top left of each page." },
      { id: "hc", type: "text", label: "Top middle", value: "", tip: "Shown at the top, in the middle." },
      { id: "hr", type: "text", label: "Top right", value: "{date}", tip: "Shown at the top right." },
      { id: "fl", type: "text", label: "Bottom left", value: "", tip: "Shown at the bottom left." },
      { id: "fc", type: "text", label: "Bottom middle", value: "Page {page} of {pages}", tip: "Shown at the bottom, in the middle." },
      { id: "fr", type: "text", label: "Bottom right", value: "", tip: "Shown at the bottom right." },
      { id: "bates", type: "text", label: "Bates prefix (optional)", value: "", placeholder: "ACME-", tip: "Adds a running number like ACME-000001 at the bottom right (when the bottom right is empty)." },
      { id: "start", type: "text", label: "First number", value: "1", tip: "The Bates number of the first page." },
      { id: "size", type: "text", label: "Text size", value: "10", tip: "In points. 10 is small and tidy." },
      { id: "color", type: "text", label: "Colour", value: "#444444", tip: "A colour name or a code like #444444." },
      PAGES],
    endpoint: "/api/tools/pdfheader", body: (v) => base(v, { options: v }), run: "Add", noun: "PDF" });

  F.jobTool({ id: "pdftables", group: "convert", icon: "📊", label: "PDF tables to Excel", blurb: "Find the tables in a PDF and save them as an Excel file or CSV files.",
    title: "PDF tables to Excel or CSV", sub: "Finds every table with lines or clear columns and saves it. Numbers become real numbers. Scanned pages need Searchable PDF (OCR) first.",
    fields: [{ id: "kind", type: "select", label: "Save as", value: "xlsx", options: [opt("xlsx", "One Excel file (a sheet per table)", "All the tables in one workbook."), opt("csv", "A CSV file per table", "Plain text tables, one file each.")], tip: "How the tables are saved." }, PAGES],
    endpoint: "/api/tools/pdftables", body: (v) => base(v, { options: v }), run: "Find tables", noun: "PDF" });

  F.jobTool({ id: "pdfclean", group: "protect", icon: "🧼", label: "Clean PDF", blurb: "Remove author, hidden scripts and attached files from a PDF before you share it.",
    title: "Clean a PDF before sharing", sub: "Removes the details people forget are inside a PDF: author and title, software, hidden scripts, attached files and old thumbnails. The pages look the same.",
    fields: [{ id: "meta", type: "check", label: "Author, title, dates and software", value: true, tip: "The document details and hidden XML data." },
      { id: "js", type: "check", label: "Scripts (JavaScript)", value: true, tip: "Code that can run when the PDF opens." },
      { id: "files", type: "check", label: "Attached files", value: true, tip: "Files hidden inside the PDF." },
      { id: "comments", type: "check", label: "Comments and notes", value: false, tip: "Deletes all comments, highlights and sticky notes." },
      { id: "links", type: "check", label: "Links", value: false, tip: "Makes web links and page links stop working." }],
    endpoint: "/api/tools/pdfclean", body: (v) => base(v, { options: v }), run: "Clean", noun: "PDF" });

  F.jobTool({ id: "pdfbookmarks", group: "edit", icon: "🔖", label: "Bookmarks", blurb: "Build the clickable outline of a PDF from its headings.",
    title: "Make bookmarks from the headings", sub: "Looks for lines set larger than the body text and builds the bookmark panel from them, so long PDFs can be jumped through. Works best on documents made from Word or a web page.",
    fields: [{ id: "levels", type: "select", label: "Heading levels", value: "3", options: [opt("1", "1 level"), opt("2", "2 levels"), opt("3", "3 levels"), opt("4", "4 levels")], tip: "How many sizes of heading count." },
      { id: "keep", type: "check", label: "Keep the bookmarks it already has", value: false, tip: "Off: the old bookmarks are replaced." }],
    endpoint: "/api/tools/pdfbookmarks", body: (v) => base(v, { options: { levels: +v.levels, keep: v.keep } }), run: "Add bookmarks", noun: "PDF" });

  F.jobTool({ id: "pdfresize", group: "size", icon: "📐", label: "Page size", blurb: "Fit every PDF page onto A4, Letter, A5 and more.",
    title: "Change the page size of a PDF", sub: "Puts each page onto a sheet of the paper you choose, shrunk or grown to fit and centred. Handy before printing. Form fields and notes become plain page content.",
    fields: [{ id: "size", type: "select", label: "Paper", value: "a4", options: [["a3", "A3"], ["a4", "A4"], ["a5", "A5"], ["a6", "A6"], ["letter", "Letter"], ["legal", "Legal"], ["tabloid", "Tabloid"]].map(([v, l]) => opt(v, l)), tip: "The new page size." },
      { id: "orient", type: "select", label: "Turn the sheet", value: "auto", options: [opt("auto", "Like each page (upright or sideways)"), opt("portrait", "Always upright"), opt("landscape", "Always sideways")], tip: "How the sheet is turned." },
      { id: "fill", type: "select", label: "Fit", value: "fit", options: [opt("fit", "Whole page visible", "Nothing is cut off; there may be white bars."), opt("fill", "Fill the sheet", "No bars, but the edges may be cut off.")], tip: "Fit keeps everything." },
      { id: "margin", type: "text", label: "Margin (mm)", value: "0", tip: "White border around the page." }],
    endpoint: "/api/tools/pdfresize", body: (v) => base(v, { options: v }), run: "Change size", noun: "PDF" });

  F.jobTool({ id: "collage", presets: [{ name: "Photo grid 3 wide", values: { layout: "grid", cols: "3", cell: "400", gap: "12", bg: "#ffffff", format: "jpg" } }, { name: "Before and after row", values: { layout: "row", cell: "600", gap: "16", bg: "#ffffff", format: "png" } }, { name: "Tight contact sheet", values: { layout: "grid", cols: "5", cell: "240", gap: "4", bg: "#000000", format: "jpg" } }], group: "edit", icon: "🖼️", label: "Collage", blurb: "Put several pictures into one: a grid, a row or a column.",
    title: "Make a collage", sub: "Joins the pictures in your list into one picture." + ORDER,
    fields: [{ id: "layout", type: "select", label: "Layout", value: "grid", options: [opt("grid", "Grid"), opt("row", "One row"), opt("column", "One column")], tip: "How the pictures are placed." },
      { id: "cols", type: "text", label: "Pictures per row", value: "3", show: (v) => v.layout === "grid", tip: "How many columns the grid has." },
      { id: "cell", type: "text", label: "Size of each picture (pixels)", value: "400", tip: "The width and height of every square in a grid, or the height/width in a row or column." },
      { id: "fit", type: "select", label: "In each square", value: "fill", show: (v) => v.layout === "grid", options: [opt("fill", "Fill it (crop the edges)"), opt("pad", "Show the whole picture (add bars)")], tip: "How a picture that is not square is handled." },
      { id: "gap", type: "text", label: "Space between (pixels)", value: "12", tip: "The gap around and between pictures." },
      { id: "bg", type: "text", label: "Background colour", value: "#ffffff", tip: "A colour name or a code like #ffffff." },
      { id: "format", type: "select", label: "Save as", value: "jpg", options: [opt("jpg", "JPG"), opt("png", "PNG")], tip: "The picture type." }],
    endpoint: "/api/tools/collage", body: (v) => base(v, { options: v }), run: "Make collage", noun: "collage", needsFiles: true });

  F.jobTool({ id: "frame", presets: [{ name: "Polaroid look", values: { border: "40", color: "#ffffff", radius: "2", circle: false, shadow: true, transparent: false } }, { name: "Profile circle", values: { border: "0", radius: "0", circle: true, shadow: false, transparent: true } }, { name: "Rounded with shadow", values: { border: "16", color: "#ffffff", radius: "12", circle: false, shadow: true, transparent: false } }], group: "edit", icon: "🪟", label: "Frame & corners", blurb: "Add a border, round the corners, cut a circle or add a soft shadow.",
    title: "Frame, round corners, shadow", sub: "Makes a picture look finished: a coloured border, rounded corners, a circle (for profile pictures) and a soft shadow. Rounded or shadowed pictures are saved as PNG so the corners can be see-through.",
    fields: [{ id: "border", type: "text", label: "Border (pixels)", value: "24", tip: "0 = no border." },
      { id: "color", type: "text", label: "Border colour", value: "#ffffff", tip: "A colour name or a code like #ffffff." },
      { id: "radius", type: "text", label: "Round the corners (0 to 50 %)", value: "8", tip: "0 = square corners. 50 = as round as possible." },
      { id: "circle", type: "check", label: "Cut a circle", value: false, tip: "Crops the picture into a circle (a profile picture)." },
      { id: "shadow", type: "check", label: "Soft shadow", value: true, tip: "A gentle shadow behind the picture." },
      { id: "transparent", type: "check", label: "See-through background", value: false, tip: "Leaves the space around the picture see-through instead of the border colour." }],
    endpoint: "/api/tools/frame", body: (v) => base(v, { options: v }), run: "Apply", noun: "picture" });

  F.jobTool({ id: "icon", group: "convert", icon: "🎯", label: "Icon maker", blurb: "Turn a logo into a Windows icon (.ico) and the pictures a website needs.",
    title: "Icon and favicon maker", sub: "Makes an .ico with every size Windows uses (16 to 256), and, if you like, the favicon, Apple touch icon and 192 and 512 pixel pictures for a website. A square logo with a see-through background works best.",
    fields: [{ id: "pack", type: "check", label: "Also make the website icon set", value: true, tip: "favicon-32, apple-touch-icon (180), icon-192 and icon-512 as PNG." }],
    endpoint: "/api/tools/icon", body: (v) => base(v, { options: v }), run: "Make icons", noun: "picture" });

  F.jobTool({ id: "transparent", group: "edit", icon: "🫧", label: "Make colour see-through", blurb: "Turn a plain background (white, green, any colour) into see-through.",
    title: "Make a colour see-through", sub: "Removes one colour from a picture, usually a plain background, and saves a PNG. For photos with a busy background use Remove background instead.",
    fields: [{ id: "color", type: "text", label: "Colour to remove", value: "auto", tip: "'auto' takes the colour along the edges of the picture. Or type a colour name or code like #ffffff." },
      { id: "tolerance", type: "text", label: "How close (0 to 100)", value: "12", tip: "Higher removes shades near the colour too. Raise it if a halo is left." },
      { id: "soft", type: "text", label: "Soft edge (0 to 50)", value: "6", tip: "Fades the edge so it does not look cut with scissors." }],
    endpoint: "/api/tools/transparent", body: (v) => base(v, { options: v }), run: "Make see-through", noun: "picture" });

  F.jobTool({ id: "picsgif", group: "convert", icon: "🎬", label: "Pictures to animation", blurb: "Join pictures into an animated GIF or WebP.",
    title: "Pictures to an animated GIF or WebP", sub: "Shows your pictures one after the other in a loop." + ORDER,
    fields: [{ id: "kind", type: "select", label: "Make", value: "gif", options: [opt("gif", "GIF", "Works everywhere."), opt("webp", "WebP", "Smaller and better looking, works in modern apps.")], tip: "The animation type." },
      { id: "ms", type: "text", label: "Time per picture (milliseconds)", value: "500", tip: "1000 = one second." },
      { id: "width", type: "text", label: "Width (pixels)", value: "480", tip: "The height follows." },
      { id: "loop", type: "check", label: "Repeat forever", value: true, tip: "Off: plays once." }],
    endpoint: "/api/tools/picsgif", body: (v) => base(v, { options: v }), run: "Make animation", noun: "animation" });

  F.jobTool({ id: "slideshow", group: "convert", icon: "📽️", label: "Slideshow video", blurb: "Turn pictures (and a song) into a video.",
    title: "Pictures to a slideshow video", sub: "Makes an MP4 where each picture shows for a few seconds, with a fade at the start and end. Add one sound file to the list to use it as the music." + ORDER,
    fields: [{ id: "seconds", type: "text", label: "Seconds per picture", value: "3", tip: "How long each picture stays." },
      { id: "size", type: "select", label: "Shape", value: "1280x720", options: [opt("1280x720", "Wide (1280x720)"), opt("1920x1080", "Wide, HD (1920x1080)"), opt("1080x1920", "Tall, for phones (1080x1920)"), opt("1080x1080", "Square (1080x1080)")], tip: "The picture size of the video." },
      { id: "fade", type: "text", label: "Fade in and out (seconds)", value: "0.5", tip: "0 = no fade." }],
    endpoint: "/api/tools/slideshow", body: (v) => base(v, { options: v }), run: "Make video", noun: "video" });

  F.jobTool({ id: "videocrop", group: "edit", icon: "📱", label: "Crop video", blurb: "Cut a video to a shape: vertical for phones, square, wide.",
    title: "Crop a video to a shape", sub: "Cuts the picture to a new shape: 9:16 for phone stories and shorts, 1:1 for squares, 4:5 for feeds. The sound is kept.",
    fields: [{ id: "ratio", type: "select", label: "Shape", value: "9:16", options: [opt("9:16", "Tall 9:16 (phone, shorts)"), opt("4:5", "Tall 4:5 (feed)"), opt("1:1", "Square 1:1"), opt("4:3", "Classic 4:3"), opt("16:9", "Wide 16:9"), opt("21:9", "Cinema 21:9")], tip: "The new shape." },
      { id: "anchor", type: "select", label: "Keep the part at the", value: "center", options: [opt("center", "Middle"), opt("left", "Left"), opt("right", "Right"), opt("top", "Top"), opt("bottom", "Bottom")], tip: "Which part of the picture is kept." }],
    endpoint: "/api/tools/videocrop", body: (v) => base(v, { options: v }), run: "Crop", noun: "video" });

  F.jobTool({ id: "reverse", group: "edit", icon: "⏪", label: "Reverse", blurb: "Play a video or a sound backwards.",
    title: "Reverse a video or sound", sub: "Plays it from the end to the start. Limited to 3 minutes, because the whole clip is held in memory while it is turned around.",
    fields: [], endpoint: "/api/tools/reverse", body: (v) => base(v, { options: {} }), run: "Reverse", noun: "file" });

  F.jobTool({ id: "silence", group: "edit", icon: "🤫", label: "Cut silence", blurb: "Remove the quiet gaps from a recording or podcast.",
    title: "Cut out the silence", sub: "Shortens recordings by removing long quiet parts, such as pauses in a lecture or a voice memo. A little breathing room is kept so it still sounds natural.",
    fields: [{ id: "db", type: "text", label: "Counts as silence below (dB)", value: "-40", tip: "-40 is quiet. Use -30 for noisy recordings." },
      { id: "gap", type: "text", label: "Only gaps longer than (seconds)", value: "0.6", tip: "Shorter pauses are kept." },
      { id: "keep", type: "text", label: "Leave this much silence (seconds)", value: "0.15", tip: "So words do not run together." }],
    endpoint: "/api/tools/silence", body: (v) => base(v, { options: v }), run: "Cut silence", noun: "recording" });

  F.jobTool({ id: "fade", group: "edit", icon: "🌅", label: "Fade in / out", blurb: "Fade a video or sound in at the start and out at the end.",
    title: "Fade in and out", sub: "Makes the start and end of a video or sound smooth instead of sudden. A video fades from and to black and its sound fades too.",
    fields: [{ id: "fin", type: "text", label: "Fade in (seconds)", value: "1", tip: "0 = no fade in." }, { id: "fout", type: "text", label: "Fade out (seconds)", value: "2", tip: "0 = no fade out." }],
    endpoint: "/api/tools/fade", body: (v) => base(v, { options: v }), run: "Add fades", noun: "file" });

  F.jobTool({ id: "addaudio", group: "edit", icon: "🎵", label: "Add music", blurb: "Put a song under a video, or replace its sound.",
    title: "Add music to a video", sub: "Put one video and one sound file in the list. The song is repeated or cut to fit the video. The picture is not re-encoded, so there is no quality loss.",
    fields: [{ id: "mode", type: "select", label: "Original sound", value: "replace", options: [opt("replace", "Replace it with the music"), opt("mix", "Keep it and play the music underneath")], tip: "What happens to the video's own sound." },
      { id: "volume", type: "text", label: "Music volume (0 to 2)", value: "1", tip: "1 = as it is. 0.3 is quiet background." },
      { id: "orig", type: "text", label: "Original sound volume (0 to 2)", value: "0.4", show: (v) => v.mode === "mix", tip: "How loud the video's own sound stays." }],
    endpoint: "/api/tools/addaudio", body: (v) => base(v, { options: v }), run: "Add music", noun: "video" });

  F.jobTool({ id: "videomark", group: "edit", icon: "💧", label: "Video watermark", blurb: "Put your name or a note in a corner of a video.",
    title: "Text watermark on a video", sub: "Adds readable text (a name, a website, 'draft') on top of the whole video. For pictures and PDFs use Stamp.",
    fields: [{ id: "text", type: "text", label: "Text", value: "", placeholder: "My Channel", tip: "What the watermark says." },
      { id: "pos", type: "select", label: "Where", value: "br", options: [opt("br", "Bottom right"), opt("bl", "Bottom left"), opt("tr", "Top right"), opt("tl", "Top left"), opt("c", "Middle")], tip: "The corner it sits in." },
      { id: "size", type: "text", label: "Size (% of the video height)", value: "5", tip: "5 is small and tidy." },
      { id: "opacity", type: "text", label: "Opacity (0.1 to 1)", value: "0.6", tip: "1 = solid. Lower is more see-through." },
      { id: "color", type: "text", label: "Colour", value: "#ffffff", tip: "A colour name or a code." }],
    endpoint: "/api/tools/videomark", body: (v) => base(v, { options: v }), run: "Add watermark", noun: "video" });

  F.jobTool({ id: "csvclean", group: "tidy", icon: "🧽", label: "Tidy a table", blurb: "Clean a CSV: trim spaces, remove blank and duplicate rows, sort.",
    title: "Tidy a CSV or TSV table", sub: "Trims extra spaces, removes empty rows and duplicate rows and sorts. Works on the text as it is: a new file is made and the original is kept.",
    fields: [{ id: "trim", type: "check", label: "Trim spaces around every cell", value: true, tip: "' Bob ' becomes 'Bob'." },
      { id: "empty", type: "check", label: "Remove empty rows", value: true, tip: "Rows where every cell is blank." },
      { id: "dedupe", type: "check", label: "Remove duplicate rows", value: true, tip: "Keeps the first of each." },
      { id: "key", type: "text", label: "Duplicates are judged by column", value: "", placeholder: "all columns", tip: "A column name or number. Empty = the whole row must match." },
      { id: "sort", type: "text", label: "Sort by column", value: "", placeholder: "don't sort", tip: "A column name or number. Numbers sort as numbers." },
      { id: "desc", type: "check", label: "Biggest first", value: false, show: (v) => !!v.sort, tip: "Sorts from high to low." }],
    endpoint: "/api/tools/csvclean", body: (v) => base(v, { options: v }), run: "Tidy", noun: "table" });

  F.jobTool({ id: "pdfa", group: "protect", icon: "🗄️", label: "PDF/A archive", blurb: "Make a PDF that is built to stay readable for decades: fonts inside, no outside links.",
    title: "Make a PDF/A", sub: "Rebuilds a PDF in the archive standard used by courts, councils and libraries. Needs Ghostscript or LibreOffice on this PC. Look at the result: layout can shift a little.",
    fields: [{ id: "level", type: "select", label: "Version", value: "2", options: [opt("1", "PDF/A-1b", "The oldest and strictest."), opt("2", "PDF/A-2b", "The usual choice."), opt("3", "PDF/A-3b", "Allows attached files.")], tip: "If you are not told which, use PDF/A-2b." }],
    endpoint: "/api/tools/pdfa", body: (v) => base(v, { options: v }), run: "Make PDF/A", noun: "PDF" });

  F.jobTool({ id: "pdfredactcheck", group: "protect", icon: "🕵️", label: "Check redactions", blurb: "Prove that blacked-out words are really gone from a PDF, not just hidden under a box.",
    title: "Check a redaction", sub: "A black box over text often leaves the words underneath, and they can be copied. Type the words that should be gone: Fathom looks in the text, notes, form fields, document details, bookmarks and attachments and writes a PASSED or FAILED report next to the PDF.",
    fields: [{ id: "words", type: "text", label: "Words that must be gone", value: "", placeholder: "e.g. John Smith, 4111 1111, ACME", tip: "Separate several with commas." },
      { id: "hidden", type: "check", label: "Also look for hidden text", value: true, tip: "White text, and text placed outside the page edge." },
      { id: "meta", type: "check", label: "Also look in details, bookmarks and attachments", value: true, tip: "Names often survive in the author field or a bookmark." },
      { id: "password", type: "text", label: "Password (if the PDF has one)", value: "", tip: "Leave empty if it opens without one." }],
    endpoint: "/api/tools/pdfredactcheck", body: (v) => base(v, { options: v }), run: "Check", noun: "PDF" });

  F.jobTool({ id: "passport", group: "edit", icon: "🪪", label: "Passport photo", blurb: "Crop a portrait to a passport or ID size, centred on the face, and lay out a print sheet.",
    title: "Passport and ID photos", sub: "Finds the face and crops to the exact size, with the head the right size in the frame. Optionally makes a sheet to print at any photo shop. Always check your country's rules: background colour and expression matter.",
    presets: [{ name: "Europe / UK / Pakistan 35x45", values: { size: "eu", sheet: "4x6" } }, { name: "USA / India 2x2 inch", values: { size: "us", sheet: "4x6" } }, { name: "Visa photo, white background", values: { size: "us", bg: "#ffffff", sheet: "single" } }],
    fields: [{ id: "size", type: "select", label: "Size", value: "eu", options: [opt("eu", "35 x 45 mm (Europe, Schengen)"), opt("uk", "35 x 45 mm (UK)"), opt("pk", "35 x 45 mm (Pakistan)"), opt("au", "35 x 45 mm (Australia)"), opt("jp", "35 x 45 mm (Japan)"), opt("us", "2 x 2 inch, 51 mm (USA)"), opt("in", "51 x 51 mm (India)"), opt("cn", "33 x 48 mm (China)"), opt("ca", "50 x 70 mm (Canada)"), opt("id", "25 x 35 mm (small ID)"), opt("custom", "Another size…")], tip: "The finished photo size." },
      { id: "w", type: "text", label: "Width (mm)", value: "35", show: (v) => v.size === "custom" }, { id: "h", type: "text", label: "Height (mm)", value: "45", show: (v) => v.size === "custom" },
      { id: "head", type: "text", label: "Head size (% of the photo height)", value: "72", tip: "Most countries want about 70 to 80." },
      { id: "bg", type: "text", label: "Fill colour where the photo runs out", value: "#ffffff", tip: "Used only if the crop goes past the edge of your picture." },
      { id: "dpi", type: "text", label: "Detail (dpi)", value: "300", tip: "300 suits photo shops." },
      { id: "sheet", type: "select", label: "Print sheet", value: "single", options: [opt("single", "Just the one photo"), opt("4x6", "4 x 6 inch sheet with copies"), opt("5x3.5", "5 x 3.5 inch sheet"), opt("a4", "A4 sheet with copies")], tip: "Fills the sheet with copies, ready to print." }],
    endpoint: "/api/tools/passport", body: (v) => base(v, { options: v }), run: "Make photos", noun: "photo" });

  F.jobTool({ id: "fitsize", group: "size", icon: "📏", label: "Fit under a size", blurb: "Shrink a video or song to fit a limit, like WhatsApp, Discord, Telegram or an email.",
    title: "Fit under a size limit", sub: "Tell Fathom the biggest size allowed and it picks the quality, picture size and sound to land just under it. Your original is not changed.",
    presets: [{ name: "WhatsApp (16 MB)", values: { mb: "16" } }, { name: "Discord free (10 MB)", values: { mb: "10" } }, { name: "Discord Nitro Basic (50 MB)", values: { mb: "50" } }, { name: "Email (20 MB)", values: { mb: "20" } }, { name: "Telegram (50 MB)", values: { mb: "50" } }],
    fields: [{ id: "mb", type: "text", label: "Biggest size (MB)", value: "16", tip: "The file will be at or below this." }],
    endpoint: "/api/tools/fitsize", body: (v) => base(v, { options: v }), run: "Shrink", noun: "file" });
})();
