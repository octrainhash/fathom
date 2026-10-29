/* Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE). */
(() => {
  "use strict";
  const F = window.Fathom, $ = F.$, h = F.h;
  F.addGroup("home", "Home"); F.addGroup("ai", "Assistant"); F.addGroup("search", "Search"); F.addGroup("convert", "Convert"); F.addGroup("size", "Size"); F.addGroup("edit", "Edit");
  F.addGroup("protect", "Protect"); F.addGroup("tidy", "Tidy"); F.addGroup("lab", "Lab"); F.addGroup("sync", "Sync"); F.addGroup("torrent", "Torrent"); F.addGroup("drives", "Drives"); F.addGroup("toolbox", "Toolbox"); F.addGroup("mine", "My tools");
  // the most-wanted editing tools come first in the Edit group
  { const first = ["editor", "replace", "stamp", "sign"].map((id) => F.tools.find((t) => t.id === id)).filter(Boolean); const at = F.tools.findIndex((t) => t.id === "merge"); if (first.length && at >= 0) { F.tools = F.tools.filter((t) => !first.includes(t)); F.tools.splice(F.tools.findIndex((t) => t.id === "merge"), 0, ...first); } }
  F.buildNav();
  const want = F.load("tool", "find");
  F.show(F.tools.some((t) => t.id === want) ? want : "find");
  F.engineRefresh && F.engineRefresh();
  F.refreshUndo && F.refreshUndo();
  (F.onBoot || []).forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });

  // drag and drop of files/folders adds them to the shared list
  let depth = 0;
  const drop = $("drop");
  // The overlay is only for files dragged in from outside; dragging a picture or text inside Fathom never shows it, and it always clears itself.
  const hasFiles = (e) => { const t = e.dataTransfer && e.dataTransfer.types; return !!t && [...t].includes("Files"); };
  let hideT = 0;
  const hideDrop = () => { depth = 0; drop.hidden = true; clearTimeout(hideT); };
  const keepDrop = () => { clearTimeout(hideT); hideT = setTimeout(hideDrop, 1500); };     // dragover fires constantly while a drag is really over the window
  window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; drop.hidden = false; keepDrop(); });
  window.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; if (--depth <= 0 || e.relatedTarget === null) hideDrop(); });
  window.addEventListener("dragover", (e) => { e.preventDefault(); if (hasFiles(e)) { drop.hidden = false; keepDrop(); } });
  window.addEventListener("dragend", hideDrop, true);
  window.addEventListener("drop", hideDrop, true);
  window.addEventListener("pointerdown", () => { if (!drop.hidden) hideDrop(); }, true);
  window.addEventListener("keydown", () => { if (!drop.hidden) hideDrop(); }, true);
  window.addEventListener("blur", hideDrop);
  window.addEventListener("drop", (e) => { e.preventDefault(); hideDrop(); const files = [...(e.dataTransfer?.files || [])]; const paths = files.map((f) => f.path).filter(Boolean); if (paths.length) F.addPaths(paths); else if (files.length) { F.toast("Sending " + files.length + " file" + (files.length === 1 ? "" : "s") + " to Fathom…"); F.uploadFiles(files).then((p) => F.addPaths(p)).catch((x) => F.toast(x.message)); } });

  // outside the app window (plain browser) there is a Quit button
  setTimeout(async () => { try { await F.ready; } catch { /* ok */ } if (!window.pywebview && $("quit") && !(F.info && F.info.serve)) { $("quit").hidden = false; $("quit").onclick = async () => { try { await F.api("/api/quit", { method: "POST" }); } catch { /* closing */ } document.body.innerHTML = "<p style='padding:40px;font:16px sans-serif'>Fathom has stopped. You can close this tab.</p>"; }; } }, 1500);
})();
