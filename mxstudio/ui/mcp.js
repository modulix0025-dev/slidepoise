/* «توصيل Claude Desktop» — connect the local MCP server to Claude Desktop, step by step.
   Loaded before app.js; app.js calls window.MXS_MCP(ctx). HTTP only. */
"use strict";

window.MXS_MCP = (function () {
  const S = {
    ar: {
      title: "توصيل Claude Desktop بالاستوديو (MCP)",
      lead: "بعد التوصيل، Claude Desktop (باشتراكك العادي، من غير مفتاح API) يقدر يبني ويعدّل القوالب في الاستوديو بالكلام. أي اعتماد أو نشر بيستنى موافقتك هنا.",
      status: "الحالة", found: "Claude Desktop متسطّب", notFound: "Claude Desktop مش متسطّب على الجهاز ده (أو لسه ماتفتحش ولا مرة)",
      connected: "متوصّل ✓", notConnected: "لسه مش متوصّل", file: "ملف الإعدادات", others: "سيرفرات MCP تانية موجودة (مش هتتلمس)",
      install: "وصّل تلقائيًا", test: "اختبر التوصيل", remove: "شيل التوصيل", copy: "انسخ", copied: "اتنسخ ✓", working: "شغّال…",
      steps: "الخطوات",
      s1: "نزّل Claude Desktop من claude.ai/download وسجّل دخول بحسابك.",
      s2: "دوس «وصّل تلقائيًا» تحت — بيضيف الاستوديو لإعدادات Claude Desktop وبياخد نسخة احتياطية من الإعدادات القديمة. (أو يدوي: Claude Desktop ← Settings ← Developer ← Edit Config، وحط جزء «modulex-studio» جوه mcpServers.)",
      s3: "اقفل Claude Desktop خالص: كليك يمين على أيقونته جنب الساعة ← Quit، وبعدين افتحه تاني. (قفل الشباك بس مش كفاية.)",
      s4: "في Claude Desktop هتلاقي أدوات «modulex-studio» من زرار الأدوات تحت مربع الكتابة.",
      s5: "جرّب: «استخدم modulex-studio واعمل قصة عن طفل بيزور الهرم، 6 صفحات، والاسم كبير على الغلاف». Claude هيشوف صور الصفحات اللي اتبنت ويعدّل على كلامك.",
      s6: "الاعتماد والنشر هيظهروا هنا في «ابدأ هنا» ← «طلبات الموافقة»؛ خلّي الاستوديو مفتوح علشان توافق.",
      manual: "الإعداد يدويًا", trouble: "لو ماظهرش",
      t1: "اتأكد إنك قفلت Claude Desktop من أيقونة جنب الساعة مش من الشباك بس.",
      t2: "دوس «اختبر التوصيل»: لو قال شغّال، المشكلة في Claude Desktop مش في الاستوديو.",
      t3: "لوج Claude Desktop: %APPDATA%\\Claude\\logs\\mcp-server-modulex-studio.log",
      t4: "الإعدادات بتشاور على مشغّل ثابت (mxstudio-mcp.exe في بيانات البرنامج)، فنقل البرنامج أو إعادة تسطيبه مش محتاجين توصيل من جديد.",
      restartNeeded: "Claude Desktop لازم يتقفل ويتفتح علشان يشوف الاستوديو.", restart: "أعد تشغيل Claude Desktop",
      restartAsk: "ده هيقفل Claude Desktop ويفتحه تاني — أي رد شغّال فيه هيقف. أكمّل؟",
      log: "آخر حالة في لوج Claude Desktop", logStates: { connected: "متوصّل ✓", error: "خطأ", starting: "بيبدأ", unknown: "مش واضح", no_log: "مفيش لوج لسه (Claude Desktop ماحاولش يشغّل الاستوديو)" },
      selfTest: "اختبار التوصيل الأخير", launcher: "المشغّل الثابت", heal: "صلّح التوصيل", perConfig: "ملفات الإعدادات",
    },
    en: {
      title: "Connect Claude Desktop to the Studio (MCP)",
      lead: "Once connected, Claude Desktop (your normal subscription, no API key) can build and revise templates in the Studio in plain words. Approvals and publishing still wait for you here.",
      status: "Status", found: "Claude Desktop is installed", notFound: "Claude Desktop is not installed on this PC (or has never been opened)",
      connected: "Connected ✓", notConnected: "Not connected yet", file: "Config file", others: "Other MCP servers already there (left untouched)",
      install: "Connect automatically", test: "Test the connection", remove: "Disconnect", copy: "Copy", copied: "Copied ✓", working: "Working…",
      steps: "Steps",
      s1: "Download Claude Desktop from claude.ai/download and sign in.",
      s2: "Press «Connect automatically» below — it adds the Studio to Claude Desktop's config and keeps a backup of the old one. (Manual: Claude Desktop → Settings → Developer → Edit Config, put the «modulex-studio» part inside mcpServers.)",
      s3: "Quit Claude Desktop completely: right-click its tray icon → Quit, then open it again. (Closing the window is not enough.)",
      s4: "In Claude Desktop the «modulex-studio» tools appear under the tools button below the message box.",
      s5: "Try: «Use modulex-studio to make a story about a child visiting the pyramids, 6 pages, big name on the cover». Claude looks at the built pages and revises on your words.",
      s6: "Approvals and publishing show up here under Start here → Pending approvals; keep the Studio open to approve.",
      manual: "Manual setup", trouble: "If it does not show up",
      t1: "Make sure you quit Claude Desktop from the tray icon, not just the window.",
      t2: "Press «Test the connection»: if it works, the problem is on Claude Desktop's side.",
      t3: "Claude Desktop log: %APPDATA%\\Claude\\logs\\mcp-server-modulex-studio.log",
      t4: "The config points at a fixed launcher (mxstudio-mcp.exe in the app data), so moving or reinstalling the program needs no reconnecting.",
      restartNeeded: "Claude Desktop must be quit and reopened to see the Studio.", restart: "Restart Claude Desktop",
      restartAsk: "This quits and reopens Claude Desktop; a reply in progress there stops. Continue?",
      log: "Last state in Claude Desktop's log", logStates: { connected: "connected ✓", error: "error", starting: "starting", unknown: "unclear", no_log: "no log yet (Claude Desktop has not tried to start the Studio)" },
      selfTest: "Last connection test", launcher: "Fixed launcher", heal: "Repair the connection", perConfig: "Config files",
    },
  };

  async function restartBar(ctx) {
    const { api, esc, lang } = ctx;
    const s = (key) => (S[lang] || S.ar)[key];
    const bar = document.getElementById("restart-bar");
    if (!bar) return;
    const health = await api("/api/mcp/health");
    const pending = health && health.restart && health.restart.pending;
    bar.hidden = !pending;
    if (!pending) { bar.innerHTML = ""; return; }
    bar.innerHTML = `<b>${esc(s("restartNeeded"))}</b><button class="xb" id="restart-claude">${esc(s("restart"))}</button><span class="status" id="restart-status"></span>`;
    document.getElementById("restart-claude").onclick = async () => {
      if (!window.confirm(s("restartAsk"))) return;
      document.getElementById("restart-status").textContent = s("working");
      const r = await api("/api/mcp/restart-claude", { method: "POST", body: { confirm: true } });
      document.getElementById("restart-status").textContent = (lang === "ar" ? r.ar : r.en) || JSON.stringify(r).slice(0, 200);
      setTimeout(() => restartBar(ctx), 8000);
    };
  }

  async function mcp(ctx) {
    const { api, esc, tile, view, lang } = ctx;
    const s = (key) => (S[lang] || S.ar)[key];
    const seq = ctx.seq();
    const [st, cfg, health] = await Promise.all([api("/api/mcp/claude-desktop"), api("/api/mcp/config"), api("/api/mcp/health")]);
    if (seq !== ctx.seq()) return;
    const logState = (health.claude_log || {});
    const lastTest = ((health.last_heal || {}).self_test) || null;
    const problem = st.problem || (st.detail && st.detail.ar ? st.detail : null);
    const snippet = JSON.stringify(cfg.config || {}, null, 2);
    view().innerHTML = tile(s("title"), `<p class="lead">${esc(s("lead"))}</p>`)
      + tile(s("status"), `
        <div class="row ${st.claude_desktop_found ? "ok" : "bad"}">${esc(st.claude_desktop_found ? s("found") : s("notFound"))}</div>
        <div class="row ${st.connected ? "ok" : "bad"}" id="mcp-connected">${esc(st.connected ? s("connected") : s("notConnected"))}</div>
        <div class="row"><label>${esc(s("file"))}</label><code dir="ltr">${esc(st.path || "")}</code></div>
        ${(st.other_servers || []).length ? `<div class="row"><label>${esc(s("others"))}</label>${esc(st.other_servers.join(", "))}</div>` : ""}
        ${problem ? `<div class="banner">${esc(problem.ar || problem.en || "")}</div>` : ""}
        <div class="row"><label>${esc(s("launcher"))}</label><code dir="ltr">${esc((health.entry || {}).command || "")}</code> ${health.launcher_present ? "✓" : "✗"}</div>
        <div class="row"><label>${esc(s("perConfig"))}</label><ul class="steps">${(health.configs || []).map((c) => `<li><code dir="ltr">${esc(c.path)}</code> — ${c.connected ? "✓" : esc((c.problem && (c.problem.ar || c.problem.en)) || c.reason || "✗")}</li>`).join("")}</ul></div>
        <div class="row ${logState.state === "connected" ? "ok" : logState.state === "error" ? "bad" : ""}"><label>${esc(s("log"))}</label>${esc((s("logStates") || {})[logState.state] || logState.state || "")} <code dir="ltr">${esc(logState.line || "")}</code></div>
        ${lastTest ? `<div class="row ${lastTest.ok ? "ok" : "bad"}"><label>${esc(s("selfTest"))}</label>${esc(lastTest.ar || "")}</div>` : ""}
        <div class="row"><button class="xb" id="mcp-install">${esc(s("install"))}</button>
          <button class="xb ghost" id="mcp-test">${esc(s("test"))}</button>
          <button class="xb ghost" id="mcp-heal">${esc(s("heal"))}</button>
          <button class="xb ghost" id="mcp-remove">${esc(s("remove"))}</button></div>
        <div id="mcp-result" class="status"></div>`)
      + tile(s("steps"), `<ol class="steps">${["s1", "s2", "s3", "s4", "s5", "s6"].map((k) => `<li>${esc(s(k))}</li>`).join("")}</ol>`)
      + tile(s("manual"), `<div class="row"><button class="xb ghost" id="mcp-copy">${esc(s("copy"))}</button></div><pre id="mcp-snippet">${esc(snippet)}</pre>`)
      + tile(s("trouble"), `<ul class="steps">${["t1", "t2", "t3", "t4"].map((k) => `<li>${esc(s(k))}</li>`).join("")}</ul>`);

    const result = (text) => { document.getElementById("mcp-result").textContent = text; };
    const say = (r) => result(r.ar || (r.detail && (r.detail.ar || r.detail.en)) || JSON.stringify(r).slice(0, 300));
    document.getElementById("mcp-install").onclick = async () => {
      result(s("working"));
      const r = await api("/api/mcp/claude-desktop/install", { method: "POST", body: {} });
      say(r);
      if (r.path) setTimeout(ctx.rerender, 1500);
    };
    document.getElementById("mcp-remove").onclick = async () => {
      result(s("working"));
      const r = await api("/api/mcp/claude-desktop/remove", { method: "POST", body: {} });
      result(r.removed ? "✓" : say(r) || "");
      setTimeout(ctx.rerender, 1200);
    };
    document.getElementById("mcp-test").onclick = async () => {
      result(s("working"));
      say(await api("/api/mcp/self-test", { method: "POST", body: {} }));
    };
    document.getElementById("mcp-heal").onclick = async () => {
      result(s("working"));
      const r = await api("/api/mcp/heal", { method: "POST", body: {} });
      say(r.self_test || r);
      setTimeout(ctx.rerender, 1500);
    };
    document.getElementById("mcp-copy").onclick = async () => {
      try { await navigator.clipboard.writeText(snippet); result(s("copied")); } catch { result(snippet); }
    };
    restartBar(ctx);
  }

  mcp.restartBar = restartBar;
  return mcp;
})();
