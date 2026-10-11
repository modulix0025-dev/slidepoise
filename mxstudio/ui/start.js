/* «التنفيذ والتعديل» — the floating work panel: اطلب (ask), عدّل (edit the selected page), وافق (approve).
   Loaded before app.js; app.js calls window.MXS_START(ctx) once and ctx.refresh*() when things change.
   HTTP only (no pywebview js_api). Without a model in the Studio, «اطلب» prepares requests for Claude Desktop. */
"use strict";

window.MXS_START = (function () {
  const S = {
    ar: {
      lead: "اكتب اللي عايزه أو اسحب صورة التصميم، وبعدين قول التعديلات بالكلام.",
      placeholder: "مثال: قصة 8 صفحات بالعرض بالشكل storybook من آخر صورة، والاسم كبير على الغلاف",
      attach: "صور", send: "ابعت", working: "المساعد شغّال… (البناء بياخد دقيقة أو اتنين)",
      newChat: "محادثة جديدة", noPreview: "لسه مفيش معاينة — أول ما يتبني قالب هيظهر هنا.",
      noPending: "مفيش طلبات مستنية موافقتك.", approve: "موافق، نفّذ", reject: "رفض",
      suggest: "المساعد في وضع «اقتراح بس»: هيقترح ومش هينفّذ لحد ما الموديل يعدّي اختبار الأمان.",
      qualify: "اختبر الموديل", qualifying: "بيختبر… (بيكلّم الموديل كام مرة)",
      you: "انت", agent: "المساعد", plan: "الخطة", failed: "حصلت مشكلة",
      prepTitle: "وضع «تحضير طلب لـClaude Desktop»", prepLead: "مفيش موديل متظبط في الاستوديو، وده عادي: اكتب طلبك هنا واسحب الصور، والطلب هيتحفظ. بعدين افتح Claude Desktop واكتب: «نفّذ طلبات الاستوديو». (الاستوديو مايقدرش يشغّل Claude Desktop لوحده.)",
      saveReq: "احفظ الطلب لـClaude Desktop", saved: "اتحفظ ✓", requests: "طلبات Claude Desktop", noRequests: "مفيش طلبات لسه.",
      st_new: "مستني Claude Desktop", st_claimed: "Claude Desktop شغّال عليه", st_done: "خلص", st_failed: "فشل",
      inbox: "الوارد", inboxLead: "اسحب الصور هنا (أو في اختصار «الوارد» على سطح المكتب). في Claude Desktop قول: «استخدم آخر صورة».", inboxEmpty: "لسه مفيش صور.",
      editPick: "اختار صفحة من الصفحات علشان تعدّلها.", editPage: "الصفحة", kind: "النوع", place: "مكان النص", tilt: "الميل",
      nameStyle: "شكل الاسم", art: "صورة المشهد", yes: "موجودة", no: "مش موجودة", auto: "تلقائي",
      editAsk: "اكتب التعديل على الصفحة دي", editSend: "ابعت التعديل",
      editNote: "التعديل بيتبعت كطلب، وبيتبني نسخة جديدة؛ النسخ القديمة بتفضل محفوظة.",
      quick: ["كبّر الاسم", "خلّي الاسم ثلجي", "حرّك الكلام لفوق", "قلّل ميل الكلام", "خلّي الكلام غامق"],
      kinds: { cover: "غلاف", scene: "مشهد", dedication: "إهداء", back: "ظهر", certificate: "شهادة", about_me: "أنا مين", qr_back: "QR", coloring: "تلوين", bilingual: "لغتين", class_page: "صفحة الفصل" },
    },
    en: {
      lead: "Write what you want or drop a design picture, then ask for changes in plain words.",
      placeholder: "Example: an 8-page landscape storybook from the last picture, big name on the cover",
      attach: "Pictures", send: "Send", working: "The assistant is working… (a build takes a minute or two)",
      newChat: "New conversation", noPreview: "No preview yet — it appears here after the first build.",
      noPending: "Nothing is waiting for your approval.", approve: "Approve and run", reject: "Reject",
      suggest: "The assistant is in suggestion-only mode until the model passes the safety check.",
      qualify: "Check the model", qualifying: "Checking… (calls the model a few times)",
      you: "You", agent: "Assistant", plan: "Plan", failed: "Something went wrong",
      prepTitle: "“Prepare a request for Claude Desktop” mode", prepLead: "No model is configured in the Studio, and that is fine: write the request here and drop pictures; it is saved. Then in Claude Desktop write: “run the Studio requests”. (The Studio cannot start Claude Desktop by itself.)",
      saveReq: "Save the request for Claude Desktop", saved: "Saved ✓", requests: "Claude Desktop requests", noRequests: "No requests yet.",
      st_new: "waiting for Claude Desktop", st_claimed: "Claude Desktop is on it", st_done: "done", st_failed: "failed",
      inbox: "Inbox", inboxLead: "Drop pictures here (or into the «Inbox» desktop shortcut). In Claude Desktop say: “use the last picture”.", inboxEmpty: "No pictures yet.",
      editPick: "Pick a page to edit it.", editPage: "Page", kind: "Kind", place: "Text box", tilt: "Tilt",
      nameStyle: "Name style", art: "Scene art", yes: "present", no: "none", auto: "automatic",
      editAsk: "Describe the change for this page", editSend: "Send the change",
      editNote: "The change goes out as a request and builds a new version; old versions are kept.",
      quick: ["Bigger name", "Icy name", "Move the text up", "Less tilt", "Dark text"],
      kinds: { cover: "cover", scene: "scene", dedication: "dedication", back: "back", certificate: "certificate", about_me: "about me", qr_back: "QR", coloring: "colouring", bilingual: "bilingual", class_page: "class page" },
    },
  };

  const state = { conversation: null, attached: [] };
  let ctx = null;
  const s = (key) => (S[ctx.lang] || S.ar)[key];
  const $ = (id) => document.getElementById(id);

  async function modelState() {
    const [settings, check] = await Promise.all([ctx.api("/api/settings"), ctx.api("/api/agent/model-check")]);
    const tv = (settings.providers || {}).text_vision || {};
    return { prepare: !tv.enabled, mode: (settings.agent || {}).mode || "suggest_only", check };
  }

  /* one way to send words: a chat turn when the Studio has a model, else a request for Claude Desktop */
  async function submit(text, shas, statusId) {
    const status = (msg) => { const el = $(statusId); if (el) el.textContent = msg || ""; };
    const { prepare } = await modelState();
    if (prepare) {
      const saved = await ctx.api("/api/requests", { method: "POST", body: { text, image_shas: shas } });
      if (!saved.ok) { status(`${s("failed")}: ${JSON.stringify(saved.detail || saved).slice(0, 300)}`); return false; }
      status(`${s("saved")} — ${ctx.lang === "ar" ? saved.ar : saved.en}`);
      renderRequests();
      return true;
    }
    if (!state.conversation) state.conversation = (await ctx.api("/api/agent/conversations", { method: "POST", body: { title: text.slice(0, 60) } })).id;
    status(s("working"));
    const result = await ctx.api(`/api/agent/conversations/${encodeURIComponent(state.conversation)}/messages`, { method: "POST", body: { text, references: shas } });
    if (result.status === undefined) { status(`${s("failed")}: ${JSON.stringify(result.detail || result).slice(0, 300)}`); return false; }
    status("");
    await renderMessages();
    if (result.preview_sha) ctx.stage.refresh();
    renderPending();
    return true;
  }

  function showPreview(sha) {
    const box = $("preview");
    if (!box || !sha) return;
    box.innerHTML = `<a href="/api/blobs/${ctx.esc(sha)}" target="_blank" rel="noopener"><img src="/api/blobs/${ctx.esc(sha)}" alt=""></a>`;
  }

  async function renderMessages() {
    const box = $("messages");
    if (!box) return;
    if (!state.conversation) { box.innerHTML = ""; return; }
    const { esc } = ctx;
    const data = await ctx.api(`/api/agent/conversations/${encodeURIComponent(state.conversation)}`);
    box.innerHTML = (data.messages || []).map((m) => m.who === "operator"
      ? `<div class="bubble me"><div class="who">${esc(s("you"))}</div>${esc(m.text)}${(m.image_shas || []).map((sha) => `<img class="inline-img" src="/api/blobs/${esc(sha)}" alt="">`).join("")}</div>`
      : m.plan ? `<div class="bubble bot"><div class="who">${esc(s("plan"))}</div><ol>${m.plan.map((step) => `<li>${esc(step)}</li>`).join("")}</ol></div>`
        : `<div class="bubble bot ${m.status === "needs_confirmation" ? "waiting" : ""}"><div class="who">${esc(s("agent"))}</div>${esc(m.text)}</div>`).join("");
    box.scrollTop = box.scrollHeight;
    const previews = data.previews || [];
    if (previews.length) showPreview(previews[previews.length - 1]);
  }

  async function renderPending() {
    const { esc } = ctx;
    const data = await ctx.api("/api/pending");
    const items = data.pending || [];
    $("pending-count").textContent = items.length ? String(items.length) : "";
    const box = $("pending");
    if (!box) return;
    box.innerHTML = items.length ? items.map((p) => `<div class="pend">
      <div><b>${esc(p.tool)}</b> <span class="num">${esc(p.id)}</span> · ${esc(p.actor)}</div><pre>${esc(JSON.stringify(p.args, null, 1))}</pre>
      <div class="row"><button class="xb" data-approve="${esc(p.id)}">${esc(s("approve"))}</button><button class="xb ghost" data-reject="${esc(p.id)}">${esc(s("reject"))}</button></div></div>`).join("")
      : `<p class="lead">${esc(s("noPending"))}</p>`;
    box.querySelectorAll("[data-approve],[data-reject]").forEach((b) => {
      b.onclick = async () => {
        const id = b.dataset.approve || b.dataset.reject;
        await ctx.api(`/api/pending/${encodeURIComponent(id)}/decide`, { method: "POST", body: { approve: Boolean(b.dataset.approve) } });
        renderPending();
        ctx.stage.refresh();
      };
    });
  }

  async function renderInbox() {
    const { esc } = ctx;
    const data = await ctx.api("/api/inbox");
    if (!$("inbox-list")) return;
    $("inbox-folder").textContent = data.folder || "";
    const items = data.pictures || [];
    $("inbox-list").innerHTML = items.length ? items.slice(0, 6).map((p) => `<li><span dir="ltr">${esc(p.name)}</span> · <span class="num">${esc(p.modified)}</span>${p.width ? ` · <span class="num">${esc(p.width)}×${esc(p.height)}</span>` : ""}</li>`).join("") : `<li>${esc(s("inboxEmpty"))}</li>`;
  }

  let requestsTimer = null;
  async function renderRequests() {
    const { esc } = ctx;
    const data = await ctx.api("/api/requests");
    const items = data.requests || [];
    const box = $("requests");
    if (!box) return;
    box.innerHTML = items.length ? items.slice(0, 8).map((r) => `<div class="pend"><div><b class="num">${esc(r.id)}</b> · ${esc(s(`st_${r.status}`) || r.status)}${r.story_key ? ` · <span dir="ltr">${esc(r.story_key)}</span>` : ""}</div>
      <div>${esc(String(r.text || "").slice(0, 160))}</div></div>`).join("") : `<p class="lead">${esc(s("noRequests"))}</p>`;
    const latestDone = items.find((r) => r.status === "done" && r.preview_sha);
    if (latestDone) ctx.stage.refresh();
    clearTimeout(requestsTimer);
    if (items.some((r) => r.status === "new" || r.status === "claimed")) requestsTimer = setTimeout(renderRequests, 5000);
  }

  async function upload(file, statusId) {
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const result = await ctx.api("/api/inbox", { method: "POST", body: { name: file.name, data_b64: data } });
    if (result.ok) { state.attached.push({ ...result.reference, inbox: result.name }); renderAttached(); renderInbox(); }
    else { const el = $(statusId); if (el) el.textContent = `${s("failed")}: ${JSON.stringify(result.detail || result).slice(0, 200)}`; }
  }

  function renderAttached() {
    const { esc } = ctx;
    $("attached").innerHTML = state.attached.map((ref, i) => `<span class="thumb"><img src="/api/blobs/${esc(ref.sha)}" alt=""><button type="button" data-i="${i}" aria-label="×">×</button></span>`).join("");
    document.querySelectorAll("#attached button").forEach((b) => { b.onclick = () => { state.attached.splice(Number(b.dataset.i), 1); renderAttached(); }; });
  }

  function droppable(el) {
    el.ondragover = (e) => { e.preventDefault(); el.classList.add("drop"); };
    el.ondragleave = () => el.classList.remove("drop");
    el.ondrop = async (e) => { e.preventDefault(); el.classList.remove("drop"); for (const f of e.dataTransfer.files) if (f.type.startsWith("image/")) await upload(f, "chat-status"); };
  }

  /* ---------------------------------------------------------------- اطلب */
  async function renderAsk() {
    const { esc, api } = ctx;
    const [model, chats] = await Promise.all([modelState(), api("/api/agent/conversations")]);
    const list = chats.conversations || [];
    if (!state.conversation && list.length) state.conversation = list[0].id;
    const banner = model.prepare ? `<div class="note" id="prep-note"><b>${esc(s("prepTitle"))}</b><br>${esc(s("prepLead"))}</div>`
      : model.mode !== "full" ? `<div class="banner">${esc((ctx.lang === "ar" ? model.check.ar : model.check.en) || s("suggest"))} <button class="xb ghost" id="qualify">${esc(s("qualify"))}</button></div>` : "";
    ctx.panes.ask.innerHTML = `${banner}
      <p class="lead">${esc(s("lead"))}</p>
      ${list.length ? `<div class="row"><select id="chat-select" aria-label="${esc(s("newChat"))}">${list.map((c) => `<option value="${esc(c.id)}" ${c.id === state.conversation ? "selected" : ""}>${esc(c.title || c.id)}</option>`).join("")}</select>
        <button class="xb ghost" id="new-chat">${esc(s("newChat"))}</button></div>` : `<button class="xb ghost" id="new-chat" hidden>${esc(s("newChat"))}</button>`}
      <div id="messages" class="messages"></div>
      <div id="composer" class="composer">
        <textarea id="chat-text" rows="3" placeholder="${esc(s("placeholder"))}" aria-label="${esc(s("placeholder"))}"></textarea>
        <div id="attached" class="attached"></div>
        <div class="row"><label class="filebtn">${esc(s("attach"))}<input id="chat-files" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden></label>
          <button class="xb" id="chat-send">${esc(model.prepare ? s("saveReq") : s("send"))}</button></div>
        <div id="chat-status" class="status" role="status"></div>
      </div>
      <div id="inbox-drop" class="dropzone"><div class="mx-sub">${esc(s("inbox"))}</div><p class="lead">${esc(s("inboxLead"))}</p><code dir="ltr" id="inbox-folder"></code><ul id="inbox-list" class="steps"></ul></div>
      <div class="mx-sub">${esc(s("requests"))}</div><div id="requests"></div>`;
    renderAttached();
    $("chat-files").onchange = async (event) => { for (const f of event.target.files) await upload(f, "chat-status"); event.target.value = ""; };
    droppable($("composer"));
    droppable($("inbox-drop"));
    if ($("chat-select")) $("chat-select").onchange = (e) => { state.conversation = e.target.value; renderMessages(); };
    $("new-chat").onclick = async () => { state.conversation = (await api("/api/agent/conversations", { method: "POST", body: {} })).id; renderAsk(); };
    if ($("qualify")) $("qualify").onclick = async () => { $("chat-status").textContent = s("qualifying"); const r = await api("/api/agent/qualify", { method: "POST", body: {} }); $("chat-status").textContent = r.ar || JSON.stringify(r.detail || r).slice(0, 200); };
    $("chat-send").onclick = async () => {
      const text = $("chat-text").value.trim();
      if (!text && !state.attached.length) return;
      const button = $("chat-send");
      button.disabled = true;
      const ok = await submit(text || "(see the image)", state.attached.map((r) => r.sha), "chat-status");
      button.disabled = false;
      if (ok) { $("chat-text").value = ""; state.attached = []; renderAttached(); }
    };
    await Promise.all([renderMessages(), renderInbox(), renderRequests()]);
  }

  /* ---------------------------------------------------------------- عدّل */
  function renderEdit() {
    const { esc } = ctx;
    const page = ctx.stage.selected();
    if (!page) { ctx.panes.edit.innerHTML = `<p class="lead">${esc(s("editPick"))}</p>`; return; }
    const kinds = s("kinds");
    const box = page.text_box ? page.text_box.map((v) => Math.round(v * 100)).join(" · ") : s("auto");
    ctx.panes.edit.innerHTML = `
      <div class="mx-sub">${esc(s("editPage"))} ${esc(page.number)} — ${esc(kinds[page.kind] || page.kind)}</div>
      <p class="lead">${esc(page.text || "")}</p>
      <div class="mx-facts">
        <div class="mx-fact"><b>${esc(s("place"))}</b>${esc(box)}</div>
        <div class="mx-fact"><b>${esc(s("tilt"))}</b><span dir="ltr">${page.rotate === null || page.rotate === undefined ? esc(s("auto")) : esc(page.rotate) + "°"}</span></div>
        <div class="mx-fact"><b>${esc(s("nameStyle"))}</b>${esc(page.name_style || s("auto"))}</div>
        <div class="mx-fact"><b>${esc(s("art"))}</b>${esc(page.has_art ? s("yes") : s("no"))}</div>
      </div>
      <div class="mx-quick">${s("quick").map((q, i) => `<button type="button" data-quick="${i}">${esc(q)}</button>`).join("")}</div>
      <label for="edit-text">${esc(s("editAsk"))}</label>
      <textarea id="edit-text" rows="3" style="width:100%"></textarea>
      <div class="row"><button class="xb" id="edit-send">${esc(s("editSend"))}</button></div>
      <div id="edit-status" class="status" role="status"></div>
      <p class="lead">${esc(s("editNote"))}</p>`;
    document.querySelectorAll("[data-quick]").forEach((b) => {
      b.onclick = () => { const area = $("edit-text"); area.value = (area.value ? area.value + "، " : "") + s("quick")[Number(b.dataset.quick)]; area.focus(); };
    });
    $("edit-send").onclick = async () => {
      const words = $("edit-text").value.trim();
      if (!words) return;
      const current = ctx.stage.current();
      const prefix = ctx.lang === "ar"
        ? `تعديل في القالب ${current.story_key || ""}، صفحة ${page.number} (${kinds[page.kind] || page.kind}): `
        : `Change in template ${current.story_key || ""}, page ${page.number} (${page.kind}): `;
      $("edit-send").disabled = true;
      const ok = await submit(prefix + words, [], "edit-status");
      $("edit-send").disabled = false;
      if (ok) $("edit-text").value = "";
    };
  }

  /* ---------------------------------------------------------------- وافق */
  function renderApprove() {
    ctx.panes.approve.innerHTML = `<div id="pending"></div>`;
    return renderPending();
  }

  async function start(context) {
    ctx = context;
    await Promise.all([renderAsk(), renderApprove()]);
    renderEdit();
  }

  start.renderEdit = () => ctx && renderEdit();
  start.rerender = async () => { if (ctx) { await Promise.all([renderAsk(), renderApprove()]); renderEdit(); } };
  start.refreshPending = () => ctx && renderPending();
  return start;
})();
