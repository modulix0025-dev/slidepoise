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
      mcpHelp: "حط ده في إعدادات MCP عند العميل (claude_desktop_config.json أو .mcp.json). أي خطوة مالهاش رجوع هتظهرلك هنا في «طلبات الموافقة».",
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
      mcpHelp: "Put this in the client's MCP settings (claude_desktop_config.json or .mcp.json). Irreversible steps show up here under Pending approvals.",
      you: "You", agent: "Assistant", plan: "Plan", open: "Open full size", failed: "Something went wrong",
    },
  };

  let state = { conversation: null, attached: [] };

  return async function start(ctx) {
    const { api, esc, tile, view, lang } = ctx;
    const s = (key) => (S[lang] || S.ar)[key];
    const seq = ctx.seq();
    const [settings, chats, mcp] = await Promise.all([api("/api/settings"), api("/api/agent/conversations"), api("/api/mcp/config")]);
    if (seq !== ctx.seq()) return;
    const tv = (settings.providers || {}).text_vision || {};
    const mode = (settings.agent || {}).mode || "suggest_only";
    const list = chats.conversations || [];
    if (!state.conversation && list.length) state.conversation = list[0].id;

    const banner = !tv.enabled ? `<div class="banner">${esc(s("noModel"))} <a href="#settings">⚙</a></div>`
      : mode !== "full" ? `<div class="banner">${esc(s("suggest"))} <button class="xb ghost" id="qualify">${esc(s("qualify"))}</button></div>` : "";

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
              <button class="xb" id="chat-send">${esc(s("send"))}</button><span id="chat-status" class="status"></span></div>
          </div>`)}
      </div>
      <div class="side-col">
        ${tile(s("preview"), `<div id="preview">${esc(s("noPreview"))}</div>`)}
        ${tile(s("pending"), `<div id="pending"></div>`)}
        ${tile(s("mcp"), `<p class="lead">${esc(s("mcpHelp"))}</p><pre>${esc(JSON.stringify(mcp.config || mcp, null, 2))}</pre>`)}
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
      const result = await api("/api/uploads", { method: "POST", body: { name: file.name, data_b64: data } });
      if (result.ok) { state.attached.push(result.reference); renderAttached(); } else status(`${s("failed")}: ${JSON.stringify(result.detail || result).slice(0, 200)}`);
    };

    document.getElementById("chat-files").onchange = async (event) => { for (const f of event.target.files) await upload(f); event.target.value = ""; };
    const composer = document.getElementById("composer");
    composer.ondragover = (e) => { e.preventDefault(); composer.classList.add("drop"); };
    composer.ondragleave = () => composer.classList.remove("drop");
    composer.ondrop = async (e) => { e.preventDefault(); composer.classList.remove("drop"); for (const f of e.dataTransfer.files) if (f.type.startsWith("image/")) await upload(f); };
    document.getElementById("chat-select").onchange = (e) => { state.conversation = e.target.value; renderMessages(); };
    document.getElementById("new-chat").onclick = async () => { state.conversation = (await api("/api/agent/conversations", { method: "POST", body: {} })).id; ctx.rerender(); };
    const qualifyButton = document.getElementById("qualify");
    if (qualifyButton) qualifyButton.onclick = async () => { status(s("qualifying")); const r = await api("/api/agent/qualify", { method: "POST", body: {} }); status(r.ar || JSON.stringify(r.detail || r).slice(0, 200)); };
    document.getElementById("chat-send").onclick = async () => {
      const text = document.getElementById("chat-text").value.trim();
      if (!text && !state.attached.length) return;
      if (!state.conversation) state.conversation = (await api("/api/agent/conversations", { method: "POST", body: { title: text.slice(0, 60) } })).id;
      const button = document.getElementById("chat-send");
      button.disabled = true; status(s("working"));
      const result = await api(`/api/agent/conversations/${encodeURIComponent(state.conversation)}/messages`, { method: "POST", body: { text, references: state.attached.map((r) => r.sha) } });
      button.disabled = false;
      if (result.status === undefined) { status(`${s("failed")}: ${JSON.stringify(result.detail || result).slice(0, 300)}`); return; }
      document.getElementById("chat-text").value = ""; state.attached = []; renderAttached(); status("");
      await renderMessages();
      if (result.preview_sha) showPreview(result.preview_sha);
      renderPending();
    };
    await Promise.all([renderMessages(), renderPending()]);
  };
})();
