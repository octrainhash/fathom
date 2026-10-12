/* Proof pictures: BEFORE and AFTER pictures with the changed thing highlighted (yellow) and circled (red). */
(() => {
  const F = window.Fathom, h = F.h;

  function lightbox(items, start) {
    let i = start, side = "after", zoom = 1;
    const img = h("img", { alt: "", draggable: "false" });
    const title = h("div", { class: "lb-title" });
    const stage = h("div", { class: "lb-stage" }, img);
    const bBefore = h("button", { tip: "Shows the picture before the change." }, "Before");
    const bAfter = h("button", { tip: "Shows the picture after the change." }, "After");
    const seg = h("div", { class: "seg small" }, bBefore, bAfter);
    const close = () => { document.removeEventListener("keydown", key); box.remove(); };
    const draw = () => {
      const it = items[i];
      if (side === "before" && !it.before) side = "after";
      if (side === "after" && !it.after) side = "before";
      img.src = it[side]; img.style.width = zoom === 1 ? "" : zoom * 100 + "%"; img.style.maxWidth = zoom === 1 ? "" : "none"; img.style.maxHeight = zoom === 1 ? "" : "none";
      bBefore.setAttribute("aria-pressed", side === "before"); bAfter.setAttribute("aria-pressed", side === "after");
      bBefore.disabled = !it.before; bAfter.disabled = !it.after;
      title.textContent = `${it.title}${it.where ? "  ·  " + it.where : ""}   (${i + 1} of ${items.length})`;
    };
    const go = (d) => { i = (i + d + items.length) % items.length; zoom = 1; draw(); };
    const key = (e) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === " " || e.key === "b") { e.preventDefault(); side = side === "after" ? "before" : "after"; draw(); }
      else if (e.key === "+" || e.key === "=") { zoom = Math.min(6, zoom + 0.5); draw(); }
      else if (e.key === "-") { zoom = Math.max(1, zoom - 0.5); draw(); }
    };
    bBefore.onclick = () => { side = "before"; draw(); }; bAfter.onclick = () => { side = "after"; draw(); };
    img.onclick = () => { zoom = zoom === 1 ? 2 : 1; draw(); };
    const box = h("div", { class: "lightbox", role: "dialog", "aria-label": "Proof picture" },
      h("div", { class: "lb-bar" }, title, seg,
        h("button", { class: "btn small", tip: "Shows the previous change.", onclick: () => go(-1) }, "◀"),
        h("button", { class: "btn small", tip: "Shows the next change.", onclick: () => go(1) }, "▶"),
        h("button", { class: "btn small", tip: "Makes the picture bigger. Clicking the picture does the same.", onclick: () => { zoom = Math.min(6, zoom + 0.5); draw(); } }, "＋"),
        h("button", { class: "btn small", tip: "Makes the picture smaller.", onclick: () => { zoom = Math.max(1, zoom - 0.5); draw(); } }, "－"),
        h("button", { class: "btn small", tip: "Closes the big picture (Esc).", onclick: close }, "✕")),
      stage);
    document.body.append(box); document.addEventListener("keydown", key); draw();
  }

  /* items: [{title, where, note, before, after}] -> an element (or null when there is nothing to show) */
  F.proofGallery = (items, opts = {}) => {
    items = (items || []).filter(Boolean);
    if (!items.length) return null;
    const pics = items.filter((x) => x.before || x.after);
    const notes = items.filter((x) => !x.before && !x.after);
    const first = opts.first || 3;
    const wrap = h("div", { class: "proof" });
    const head = h("div", { class: "proof-head" }, h("b", { text: "Proof of what changed" }), h("small", { text: "Yellow = the changed part, red circle = where to look. Click a picture to enlarge it." }));
    const grid = h("div", { class: "proof-grid" });
    const card = (it) => {
      const pane = (label, url) => url
        ? h("figure", { class: "pp" }, h("img", { src: url, alt: label + " picture", loading: "lazy", tip: "Click to enlarge. " + label + " the change.", onclick: () => lightbox(pics, pics.indexOf(it)) }), h("figcaption", { text: label }))
        : h("figure", { class: "pp empty" }, h("div", { class: "none", text: label === "Before" ? "(nothing here before)" : "(removed)" }), h("figcaption", { text: label }));
      return h("div", { class: "pcard" }, h("div", { class: "pt" }, h("b", { text: it.title }), it.note ? h("small", { text: it.note }) : null), h("div", { class: "pair2" }, pane("Before", it.before), pane("After", it.after)));
    };
    pics.slice(0, first).forEach((it) => grid.append(card(it)));
    const rest = pics.slice(first);
    let more = null;
    if (rest.length) {
      more = h("button", { class: "btn small", tip: "Shows the other proof pictures.", onclick: () => { rest.forEach((it) => grid.append(card(it))); more.remove(); } }, `Show ${rest.length} more picture${rest.length === 1 ? "" : "s"}`);
    }
    wrap.append(head, grid); if (more) wrap.append(more);
    for (const n of notes) wrap.append(h("small", { class: "proof-more", text: n.title }));
    return wrap;
  };

  /* a collapsible proof button for a job row */
  F.proofToggle = (items) => {
    const g = F.proofGallery(items);
    if (!g) return null;
    const wrap = h("div", { class: "proof-wrap" });
    let open = false;
    const btn = h("button", { class: "btn small", tip: "Shows pictures of what changed: before and after, with the change highlighted and circled." }, `Show proof (${(items || []).filter((x) => x.before || x.after).length})`);
    btn.onclick = () => { open = !open; g.hidden = !open; btn.textContent = open ? "Hide proof" : `Show proof (${items.filter((x) => x.before || x.after).length})`; };
    g.hidden = true; wrap.append(g);
    return { btn, wrap };
  };
})();
