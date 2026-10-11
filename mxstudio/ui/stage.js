/* The stage: the current template's pages, always visible behind the two floating panels.
   Loaded before app.js; app.js calls window.MXS_STAGE.init(ctx). HTTP only.
   Clicking a page selects it and tells app.js (ctx.onSelect) to open «عدّل» on it. */
"use strict";

window.MXS_STAGE = (function () {
  const S = {
    ar: { name: "الاسم", empty: "لسه مفيش قالب. اطلب واحد من «اطلب» على الجنب، أو من Claude Desktop.", page: "صفحة",
      pages: "صفحات", variants: "نسخ سليمة", approved: "معتمد", draft: "مسودة", version: "نسخة",
      layouts: { classic: "كلاسيك", overlay: "كلام فوق الصورة", storybook: "كتاب حكايات" },
      formats: { portrait: "طولي", landscape_169: "عرضي 16:9" } },
    en: { name: "Name", empty: "No template yet. Ask for one in «Ask» beside the pages, or from Claude Desktop.", page: "Page",
      pages: "pages", variants: "variants OK", approved: "approved", draft: "draft", version: "version",
      layouts: { classic: "classic", overlay: "text over picture", storybook: "storybook" },
      formats: { portrait: "portrait", landscape_169: "landscape 16:9" } },
  };
  const KINDS_AR = { cover: "غلاف", scene: "مشهد", dedication: "إهداء", back: "ظهر", certificate: "شهادة", about_me: "أنا مين",
    qr_back: "QR", coloring: "تلوين", bilingual: "لغتين", class_page: "صفحة الفصل" };

  let ctx = null;
  let data = null;
  let selectedIndex = null;
  let key = "";
  let seq = 0;
  const $ = (id) => document.getElementById(id);
  const s = (k) => (S[ctx.lang()] || S.ar)[k];

  function signature(page) { return JSON.stringify([page.kind, page.text, page.name_style, page.rotate, page.text_box, page.has_art]); }

  function render(previous) {
    const esc = ctx.esc;
    const pagesBox = $("pages"), facts = $("stage-facts"), sheet = $("preview"), select = $("stage-key");
    const title = $("current-title");
    if (!data || !data.story_key) {
      pagesBox.innerHTML = `<div class="mx-empty">${esc(s("empty"))}</div>`;
      facts.textContent = ""; sheet.innerHTML = ""; title.textContent = ""; select.hidden = true;
      return;
    }
    const before = new Map(((previous && previous.story_key === data.story_key) ? previous.pages : []).map((p) => [p.index, signature(p)]));
    const fresh = previous && previous.story_key === data.story_key && previous.version !== data.version;
    const portrait = data.page !== "landscape_169";
    pagesBox.innerHTML = data.pages.map((p) => {
      const kind = ctx.lang() === "ar" ? (KINDS_AR[p.kind] || p.kind) : p.kind;
      const changed = fresh && before.get(p.index) !== signature(p);
      return `<button type="button" class="mx-page${portrait ? " is-portrait" : ""}${p.index === selectedIndex ? " is-on" : ""}${changed ? " is-new" : ""}"
        data-index="${p.index}" aria-pressed="${p.index === selectedIndex}" aria-label="${esc(`${s("page")} ${p.number} · ${kind}`)}">
        <span class="veil"></span><span class="kind">${esc(kind)}</span><span class="text">${esc(p.text).replace(/\{name\}/g, `<span class="tok">${esc(s("name"))}</span>`)}</span><span class="num">${p.number}</span></button>`;
    }).join("");
    pagesBox.querySelectorAll(".mx-page").forEach((card) => { card.onclick = () => select_(Number(card.dataset.index)); });
    const layouts = s("layouts"), formats = s("formats");
    const ok = data.variants ? `${data.variants_ok}/${data.variants} ${s("variants")}${data.variants_ok === data.variants ? " ✓" : ""}` : "";
    facts.textContent = [formats[data.page] || data.page, layouts[data.layout] || data.layout, `${data.pages.length} ${s("pages")}`, ok,
      `${s("version")} ${data.version}`, data.approved ? s("approved") : s("draft")].filter(Boolean).join(" · ");
    facts.classList.toggle("is-ok", Boolean(data.ok));
    title.textContent = data.title || data.story_key;
    const keys = data.keys || [];
    select.hidden = keys.length < 2;
    select.innerHTML = keys.map((k) => `<option value="${esc(k)}"${k === data.story_key ? " selected" : ""}>${esc(k)}</option>`).join("");
    sheet.innerHTML = data.preview_sha
      ? `<a href="/api/blobs/${esc(data.preview_sha)}" target="_blank" rel="noopener"><img src="/api/blobs/${esc(data.preview_sha)}" alt="contact sheet"></a>` : "";
  }

  function select_(index) {
    selectedIndex = index;
    document.querySelectorAll("#pages .mx-page").forEach((card) => {
      const on = Number(card.dataset.index) === index;
      card.classList.toggle("is-on", on);
      card.setAttribute("aria-pressed", String(on));
    });
    if (ctx.onSelect) ctx.onSelect(selected());
  }

  async function refresh() {
    if (!ctx) return;
    const mine = ++seq;
    const previous = data;
    const next = await ctx.api(`/api/studio/current${key ? `?key=${encodeURIComponent(key)}` : ""}`);
    if (mine !== seq) return; // a newer refresh already answered
    if (previous && next.story_key !== previous.story_key) selectedIndex = null;
    if (selectedIndex !== null && !(next.pages || []).some((p) => p.index === selectedIndex)) selectedIndex = null;
    data = next;
    render(previous);
    if (ctx.onChange) ctx.onChange(data);
  }

  function selected() {
    if (!data || selectedIndex === null) return null;
    return (data.pages || []).find((p) => p.index === selectedIndex) || null;
  }

  function init(context) {
    ctx = context;
    $("stage-key").onchange = (event) => { key = event.target.value; selectedIndex = null; refresh(); };
    return refresh();
  }

  return { init, refresh, selected, current: () => data, select: select_, rerender: () => ctx && render(null) };
})();
