/* Plain-words help for every option of the Find tool. (Other tools attach their own help as they are built.) */
(() => {
  "use strict";
  const F = window.Fathom, $ = F.$;
  /** tipFor("opt-case", text): the whole row (label) gets the tip, so hovering the words works too. */
  F.tipFor = (id, text) => { const el = typeof id === "string" ? $(id) : id; if (!el) return; F.tip(el.closest("label") || el, text); };
  const T = F.tipFor;
  T("kind-words", "Look for the exact letters, words or numbers you type, in any file.\nUse it for names, invoice numbers, phrases or anything written. Also reads words inside pictures and video frames.");
  T("kind-seen", "Find words you can SEE: signs, screenshots, slides, subtitles, posters, photos of paper.\nIt reads the pictures and the video frames only, so it ignores typed text in documents.");
  T("kind-spoken", "Find words that are SAID in videos and audio recordings, like searching a transcript.\nNeeds the speech engine (installed by Fathom.bat). The first time it may download a speech model.");
  T("kind-objects", "Look for the actual thing, not the word, in pictures, PDF pages and videos.\nTyping 'dog' finds pictures and video moments that show a dog, and ignores the written word 'dog'.");
  T("kind-objpic", "Look for the actual thing in pictures, photos and scanned pages only.\nTyping 'butterfly' finds butterflies, not the word.");
  T("kind-objvid", "Look for the actual thing in videos only.\nEvery match gives you a still and a slow-motion clip of the moment it appears.");
  T("in-documents", "Search documents and text files: PDF, Word, Excel, PowerPoint, code, notes and so on.\nUntick it to skip them.");
  T("in-pictures", "Search pictures, photos, screenshots and scans.\nUntick it to skip them.");
  T("in-videos", "Search videos (what is shown, written or said in them).\nUntick it to skip them.");
  T("in-audio", "Search audio recordings (spoken words).\nUntick it to skip them.");
  T("opt-case", "Decides whether capital letters matter.\nOn: 'Apple' will not match 'apple'.\nOff: 'Apple', 'apple' and 'APPLE' all match.");
  T("opt-word", "Decides if a word can be part of a longer word.\nOn: 'cat' will not match 'category'.\nOff: 'cat' also matches inside longer words.");
  T("opt-regex", "A regular expression is a special pattern for advanced searches, for example 'all words that start with inv followed by numbers'.\nOn: what you type is read as a pattern.\nOff: what you type is searched exactly as written.");
  T("opt-ocr", "OCR means reading the words that are inside pictures, screenshots and scanned pages.\nOn: finds words in pictures too, but searching takes longer.\nOff: only real text is searched. It is faster.");
  T("opt-hand", "Also reads HANDWRITING in pictures, photos of notes and scanned pages, even messy writing, and finds words that were read a letter or two wrong.\nOn: slower. With an AI reader (best for messy writing) each picture is sent to your AI service, which can cost a little and leaves your PC. With the offline reader nothing leaves your PC.\nOff: only printed text is read.\nChoose the reader in Assistant > Settings > Handwriting.");
  T("opt-strict", "How sure Fathom must be before it shows you an object.\nLow: shows more results, but some of them will be wrong.\nHigh: shows only things it is very sure about, but it may miss some.");
  T("opt-thorough", "How carefully each picture is looked at.\nOn: the picture is checked in small pieces, so small things are found. Slower.\nOff: the whole picture is checked once. Faster, but small things can be missed.");
  T("opt-recursive", "Folders can have folders inside them.\nOn: everything inside the folders you added is searched, however deep.\nOff: only the files directly in the folder are searched.");
  T("opt-junk", "Programs leave behind folders full of technical files (like .git or node_modules) that are rarely what you want.\nOn: those folders are skipped, which is faster and cleaner.\nOff: they are searched too.");
  T("opt-cloud", "Some OneDrive files are only stored online until you open them.\nOn: Fathom downloads them to search them. This can use a lot of internet and disk space.\nOff: online-only files are skipped.");
  T("opt-every", "How often Fathom looks at a video.\nLow number (like 0.5): checks very often. Slower, but misses nothing.\nHigh number (like 5): checks rarely. Faster, but quick moments can be missed.");
  T("opt-slow", "How much slower the slow part of the clip plays.\nLow: 1× is normal speed. 2× is a gentle slow-down.\nHigh: 16× is almost frozen, so you can see every detail.");
  T("opt-hold", "How long the picture stays frozen on the full result, so you can get a good look.\n0: never freezes.\nHigh: stays frozen longer, and the clip gets longer by the same amount.");
  T("opt-before", "How much of the video to show before the result appears, so you can see what led up to it.\nLow: starts almost at the result.\nHigh: starts earlier. The clip gets longer.");
  T("opt-after", "How much of the video to keep after the result disappears.\nLow: ends soon after.\nHigh: keeps more. The clip gets longer.");
  T("clipcalc", "This is the length your clip will have, worked out from your choices above. It is a guide, because the real length also depends on how long the result stays on screen.");
  T("opt-changes", "Also marks moments where the picture suddenly changes, like a cut to another scene or a flash.\nOn: those moments are added to the results.\nOff: only your search words or objects are marked.");
  T("opt-listen", "Listens to the sound and finds words that are spoken, like a transcript.\nOn: spoken words are searched too. It needs a speech model and takes longer.\nOff: only what you can see is searched.");
  F.tip($("opt-model"), () => ({ tiny: "Tiny: the fastest and smallest. It makes a few more mistakes.", base: "Base: a good balance of speed and accuracy.", small: "Small: the most accurate, but slower and uses more memory." })[$("opt-model").value]);
  F.tip($("query"), "Type what you want to find, then press Enter. In Words mode it is the letters you type. In Objects mode it is what the thing is called, like 'butterfly' or 'red car'.");
  F.tip($("go"), "Starts the search. While it runs this button turns into Stop.");
  F.tip($("filter"), "Narrows the results already found. Type part of a file name or a word.");
  T("group", "On: results are gathered under the file they came from.\nOff: all results are shown in one list.");
  const modeTips = {
    pause: "The clip plays at normal speed. When the full result is on screen it freezes for the number of seconds you chose, then carries on.",
    result: "The clip plays at normal speed, slows down while the result is on screen, then speeds back up. The freeze time you chose is added at the best moment.",
    all: "Every part of the clip plays in slow motion, from the first second to the last.",
  };
  for (const b of document.querySelectorAll("#clipmode .choice")) F.tip(b, modeTips[b.dataset.v]);
})();
