/* «ابدأ هنا» — talk to the Studio: write what you want, attach design pictures, ask for changes.
   Loaded before app.js; app.js calls window.MXS_START(ctx). HTTP only (no pywebview js_api). */
"use strict";

window.MXS_START = (function () {
  const S = {
    ar: {
      title: "ابدأ هنا", lead: "اكتب اللي عايزه أو ارفع صورة التصميم، وبعدين قول التعديلات بالكلام.",
      placeholder: "مثال: قصة عن طفل بيزور الهرم، 6 صفحات، ألوان دافية زي الصورة دي، والاسم كبير على الغلاف",
      attach: "إرفاق صور", send: "ابعت", working: "المساعد شغّال… (البناء بياخد دقيقة أو اتنين)",
      newChat: "محادثة جديدة", chats: "المحادثات", preview: "المعاينة", noPreview: "لسه مفيش معاينة — أول ما يتبني قالب هيظهر هنا.",
      pending: "طلبات الموافقة", noPending: "مفيش طلبات مستنية.", approve: "موافق، نفّذ", reject: "رفض",
      noModel: "مفيش موديل متظبط. من «الإعدادات» اختار Claude وحط المفتاح، أو حط عنوان موديل الـGPU بتاعك — أو وصّل Claude Desktop بالـMCP تحت.",
      suggest: "المساعد في وضع «اقتراح بس»: هيقترح ومش هينفّذ لحد ما الموديل يعدّي اختبار الأمان.",
      qualify: "اختبر الموديل", qualifying: "بيختبر… (بيكلّم الموديل كام مرة)", mcp: "التحكم من Claude Desktop / Claude Code (MCP)",
      mcpHelp: "خلّي Claude Desktop يبني ويعدّل في الاستوديو باشتراكك العادي. أي خطوة مالهاش رجوع هتظهرلك هنا في «طلبات الموافقة».",
      mcpGo: "خطوات التوصيل ←",
      prepTitle: "وضع «تحضير طلب لـClaude Desktop»", prepLead: "مفيش موديل متظبط في الاستوديو، وده عادي: اكتب طلبك هنا واسحب الصور، والطلب هيتحفظ. بعدين افتح Claude Desktop واكتب: «نفّذ طلبات الاستوديو». (الاستوديو مايقدرش يشغّل Claude Desktop لوحده.)",
      saveReq: "احفظ الطلب لـClaude Desktop", saved: "اتحفظ ✓", requests: "طلبات Claude Desktop", noRequests: "مفيش طلبات لسه.",
      st_new: "مستني Claude Desktop", st_claimed: "Claude Desktop شغّال عليه", st_done: "خلص", st_failed: "فشل",
      inbox: "الوارد (صور لـClaude Desktop)", inboxLead: "اسحب الصور هنا (أو في اختصار «الوارد» على سطح المكتب). في Claude Desktop قول: «استخدم آخر صورة».", inboxEmpty: "لسه مفيش صور.",
      you: "انت", agent: "المساعد", plan: "الخطة", open: "افتح بالحجم الكامل", failed: "حصلت مشكلة",
    },
    en: {
      title: "Start here", lead: "Write what you want or attach a design picture, then ask for changes in plain words.",
      placeholder: "Example: a story about a child visiting the pyramids, 6 pages, warm colours like this picture, big name on the cover",
      attach: "Attach pictures", send: "Send", working: "The assistant is working… (a build takes a minute or two)",
      newChat: "New conversation", chats: "Conversations", preview: "Preview", noPreview: "No preview yet — it appears here after the first build.",
      pending: "Pending approvals", noPending: "Nothing is waiting.", approve: "Approve and run", reject: "Reject",
      noModel: "No model is configured. In Settings choose Claude and add the key, or set your GPU model URL — or connect Claude Desktop through MCP below.",
      suggest: "The assistant is in suggestion-only mode until the model passes the safety check.",
      qualify: "Check the model", qualifying: "Checking… (calls the model a few times)", mcp: "Control from Claude Desktop / Claude Code (MCP)",
      mcpHelp: "Let Claude Desktop build and revise in the Studio with your normal subscription. Irreversible steps show up here under Pending approvals.",
      mcpGo: "Connection steps →",
      prepTitle: "“Prepare a request for Claude Desktop” mode", prepLead: "No model is configured in the Studio, and that is fine: write the request here and drop pictures; it is saved. Then in Claude Desktop write: “run the Studio requests”. (The Studio cannot start Claude Desktop by itself.)",
      saveReq: "Save the request for Claude Desktop", saved: "Saved ✓", requests: "Claude Desktop requests", noRequests: "No requests yet.",
      st_new: "waiting for Claude Desktop", st_claimed: "Claude Desktop is on it", st_done: "done", st_failed: "failed",
      inbox: "Inbox (pictures for Claude Desktop)", inboxLead: "Drop pictures here (or into the «Inbox» desktop shortcut). In Claude Desktop say: “use the last picture”.", inboxEmpty: "No pictures yet.",
      you: "You", agent: "Assistant", plan: "Plan", open: "Open full size", failed: "Something went wrong",
    },
  };

  let state = { conversation: null, attached: [] };

  return async function start(ctx) {
    const { api, esc, tile, view, lang } = ctx;
    const s = (key) => (S[lang] || S.ar)[key];
    const seq = ctx.seq();
    const [settings, chats, check] = await Promise.all([api("/api/settings"), api("/api/agent/conversations"), api("/api/agent/model-check")]);
    if (seq !== ctx.seq()) return;
    const tv = (settings.providers || {}).text_vision || {};
    const mode = (settings.agent || {}).mode || "suggest_only";
    const prepare = !tv.enabled; // no model here: requests are prepared for Claude Desktop (not an error)
    const list = chats.conversations || [];
    if (!state.conversation && list.length) state.conversation = list[0].id;

    const banner = prepare ? `<div class="note" id="prep-note"><b>${esc(s("prepTitle"))}</b><br>${esc(s("prepLead"))}</div>`
      : mode !== "full" ? `<div class="banner">${esc((lang === "ar" ? check.ar : check.en) || s("suggest"))} <button class="xb ghost" id="qualify">${esc(s("qualify"))}</button></div>` : "";

    view().innerHTML = `<div class="start">
      <div class="chat-col">
        ${tile(s("title"), `<p class="lead">${esc(s("lead"))}</p>${banner}
          <div class="row"><select id="chat-select">${list.map((c) => `<option value="${esc(c.id)}" ${c.id === state.conversation ? "selected" : ""}>${esc(c.title || c.id)}</option>`).join("")}</select>
          <button class="xb ghost" id="new-chat">${esc(s("newChat"))}</button></div>
          <div id="messages" class="messages"></div>
          <div id="composer" class="composer">
            <textarea id="chat-text" rows="4" placeholder="${esc(s("placeholder"))}"></textarea>
            <div id="attached" class="attached"></div>
            <div class="row"><label class="xb ghost filebtn">${esc(s("attach"))}<input id="chat-files" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden></label>
              <button class="xb" id="chat-send">${esc(prepare ? s("saveReq") : s("send"))}</button><span id="chat-status" class="status"></span></div>
          </div>`)}
      </div>
      <div class="side-col">
        ${tile(s("preview"), `<div id="preview">${esc(s("noPreview"))}</div>`)}
        ${tile(s("inbox"), `<div id="inbox-drop" class="dropzone"><p class="lead">${esc(s("inboxLead"))}</p><code dir="ltr" id="inbox-folder"></code><ul id="inbox-list" class="steps"></ul></div>`)}
        ${tile(s("requests"), `<div id="requests"></div>`)}
        ${tile(s("pending"), `<div id="pending"></div>`)}
        ${tile(s("mcp"), `<p class="lead">${esc(s("mcpHelp"))}</p><a class="xb ghost linkbtn" href="#mcp">${esc(s("mcpGo"))}</a>`)}
      </div></div>`;

    const status = (text) => { document.getElementById("chat-status").textContent = text || ""; };
    const showPreview = (sha) => {
      if (!sha) return;
      document.getElementById("preview").innerHTML = `<a href="/api/blobs/${esc(sha)}" target="_blank" rel="noopener" title="${esc(s("open"))}"><img class="preview-img" src="/api/blobs/${esc(sha)}" alt="${esc(s("preview"))}"></a>`;
    };
    const renderAttached = () => {
      document.getElementById("attached").innerHTML = state.attached.map((ref, i) => `<span class="thumb"><img src="/api/blobs/${esc(ref.sha)}" alt=""><button type="button" data-i="${i}">×</button></span>`).join("");
      document.querySelectorAll("#attached button").forEach((b) => { b.onclick = () => { state.attached.splice(Number(b.dataset.i), 1); renderAttached(); }; });
    };
    const renderPending = async () => {
      const data = await api("/api/pending");
      const items = data.pending || [];
      document.getElementById("pending").innerHTML = items.length ? items.map((p) => `<div class="pend">
        <div><b>${esc(p.tool)}</b> <span class="num">${esc(p.id)}</span> · ${esc(p.actor)}</div><pre>${esc(JSON.stringify(p.args, null, 1))}</pre>
        <div class="row"><button class="xb" data-approve="${esc(p.id)}">${esc(s("approve"))}</button><button class="xb ghost" data-reject="${esc(p.id)}">${esc(s("reject"))}</button></div></div>`).join("") : esc(s("noPending"));
      document.querySelectorAll("[data-approve],[data-reject]").forEach((b) => {
        b.onclick = async () => {
          const id = b.dataset.approve || b.dataset.reject;
          const result = await api(`/api/pending/${encodeURIComponent(id)}/decide`, { method: "POST", body: { approve: Boolean(b.dataset.approve) } });
          status(result.ok ? result.status : `${s("failed")}: ${JSON.stringify(result.detail || result).slice(0, 200)}`);
          renderPending();
        };
      });
    };
    const renderMessages = async () => {
      const box = document.getElementById("messages");
      if (!state.conversation) { box.innerHTML = ""; return; }
      const data = await api(`/api/agent/conversations/${encodeURIComponent(state.conversation)}`);
      box.innerHTML = (data.messages || []).map((m) => m.who === "operator"
        ? `<div class="bubble me"><div class="who">${esc(s("you"))}</div>${esc(m.text)}${(m.image_shas || []).map((sha) => `<img class="inline-img" src="/api/blobs/${esc(sha)}" alt="">`).join("")}</div>`
        : m.plan ? `<div class="bubble bot"><div class="who">${esc(s("plan"))}</div><ol>${m.plan.map((step) => `<li>${esc(step)}</li>`).join("")}</ol></div>`
          : `<div class="bubble bot ${m.status === "needs_confirmation" ? "waiting" : ""}"><div class="who">${esc(s("agent"))}</div>${esc(m.text)}</div>`).join("");
      box.scrollTop = box.scrollHeight;
      const previews = data.previews || [];
      if (previews.length) showPreview(previews[previews.length - 1]);
    };
    const upload = async (file) => {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const result = await api("/api/inbox", { method: "POST", body: { name: file.name, data_b64: data } });
      if (result.ok) { state.attached.push({ ...result.reference, inbox: result.name }); renderAttached(); renderInbox(); } else status(`${s("failed")}: ${JSON.stringify(result.detail || result).slice(0, 200)}`);
    };
    const renderInbox = async () => {
      const data = await api("/api/inbox");
      document.getElementById("inbox-folder").textContent = data.folder || "";
      const items = data.pictures || [];
      document.getElementById("inbox-list").innerHTML = items.length ? items.slice(0, 8).map((p) => `<li><span dir="ltr">${esc(p.name)}</span> · <span class="num">${esc(p.modified)}</span>${p.width ? ` · <span class="num">${esc(p.width)}×${esc(p.height)}</span>` : ""}</li>`).join("") : `<li>${esc(s("inboxEmpty"))}</li>`;
    };
    let requestsTimer = null;
    const renderRequests = async () => {
      const data = await api("/api/requests");
      const items = data.requests || [];
      const box = document.getElementById("requests");
      if (!box) return;
      box.innerHTML = items.length ? items.slice(0, 10).map((r) => `<div class="pend"><div><b class="num">${esc(r.id)}</b> · ${esc(s(`st_${r.status}`) || r.status)}${r.story_key ? ` · <span dir="ltr">${esc(r.story_key)}</span>` : ""}</div>
        <div>${esc(String(r.text || "").slice(0, 160))}</div>${r.preview_sha ? `<a href="/api/blobs/${esc(r.preview_sha)}" target="_blank" rel="noopener"><img class="preview-img" src="/api/blobs/${esc(r.preview_sha)}" alt=""></a>` : ""}</div>`).join("") : esc(s("noRequests"));
      const latestDone = items.find((r) => r.status === "done" && r.preview_sha);
      if (latestDone) showPreview(latestDone.preview_sha);
      clearTimeout(requestsTimer);
      if (items.some((r) => r.status === "new" || r.status === "claimed")) requestsTimer = setTimeout(() => { if (seq === ctx.seq()) renderRequests(); }, 5000);
    };

    document.getElementById("chat-files").onchange = async (event) => { for (const f of event.target.files) await upload(f); event.target.value = ""; };
    const composer = document.getElementById("composer");
    composer.ondragover = (e) => { e.preventDefault(); composer.classList.add("drop"); };
    composer.ondragleave = () => composer.classList.remove("drop");
    composer.ondrop = async (e) => { e.preventDefault(); composer.classList.remove("drop"); for (const f of e.dataTransfer.files) if (f.type.startsWith("image/")) await upload(f); };
    const drop = document.getElementById("inbox-drop");
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("drop"); };
    drop.ondragleave = () => drop.classList.remove("drop");
    drop.ondrop = async (e) => { e.preventDefault(); drop.classList.remove("drop"); for (const f of e.dataTransfer.files) if (f.type.startsWith("image/")) await upload(f); };
    document.getElementById("chat-select").onchange = (e) => { state.conversation = e.target.value; renderMessages(); };
    document.getElementById("new-chat").onclick = async () => { state.conversation = (await api("/api/agent/conversations", { method: "POST", body: {} })).id; ctx.rerender(); };
    const qualifyButton = document.getElementById("qualify");
    if (qualifyButton) qualifyButton.onclick = async () => { status(s("qualifying")); const r = await api("/api/agent/qualify", { method: "POST", body: {} }); status(r.ar || JSON.stringify(r.detail || r).slice(0, 200)); };
    document.getElementById("chat-send").onclick = async () => {
      const text = document.getElementById("chat-text").value.trim();
      if (!text && !state.attached.length) return;
      if (!state.conversation) state.conversation = (await api("/api/agent/conversations", { method: "POST", body: { title: text.slice(0, 60) } })).id;
      const button = document.getElementById("chat-send");
      if (prepare) {
        button.disabled = true;
        const saved = await api("/api/requests", { method: "POST", body: { text, image_shas: state.attached.map((r) => r.sha) } });
        button.disabled = false;
        if (!saved.ok) { status(`${s("failed")}: ${JSON.stringify(saved.detail || saved).slice(0, 300)}`); return; }
        document.getElementById("chat-text").value = ""; state.attached = []; renderAttached();
        status(`${s("saved")} — ${lang === "ar" ? saved.ar : saved.en}`);
        renderRequests();
        return;
      }
      button.disabled = true; status(s("working"));
      const result = await api(`/api/agent/conversations/${encodeURIComponent(state.conversation)}/messages`, { method: "POST", body: { text, references: state.attached.map((r) => r.sha) } });
      button.disabled = false;
      if (result.status === undefined) { status(`${s("failed")}: ${JSON.stringify(result.detail || result).slice(0, 300)}`); return; }
      document.getElementById("chat-text").value = ""; state.attached = []; renderAttached(); status("");
      await renderMessages();
      if (result.preview_sha) showPreview(result.preview_sha);
      renderPending();
    };
    await Promise.all([renderMessages(), renderPending(), renderInbox(), renderRequests()]);
  };
})();
