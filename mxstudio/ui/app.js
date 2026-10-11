/* ModuleX Magazine Studio UI — vanilla JS, HTTP only (no pywebview js_api).
   Every mutating call carries the CSRF token from /api/session. Irreversible tools
   ask the human through a dialog, then mint a single-use confirmation token. */
"use strict";

const I18N = {
  ar: {
    app: "استوديو المجلات", "nav.home": "الرئيسية", "nav.stories": "القصص والقوالب", "nav.fonts": "الخطوط",
    "nav.shapes": "الأشكال والرسم", "nav.colour": "الألوان والذوق", "nav.kit": "ربط أنظمتي", "nav.qa": "فحص قبل الطباعة",
    "nav.agent": "المساعد", "nav.doctor": "الفحص الشامل", "nav.settings": "الإعدادات", "nav.audit": "السجل",
    "confirm.title": "تأكيد خطوة مالهاش رجوع", "confirm.yes": "أيوه، نفّذ", "confirm.no": "لأ",
    status: "حالة الاستوديو", features: "الأجزاء", jobs: "المهام", budget: "مصاريف الذكاء الاصطناعي النهارده",
    providers: "مزوّدي الذكاء الاصطناعي", keys: "المفاتيح (بتتحفظ مشفّرة ومش بتظهر تاني)", save: "حفظ",
    test: "اختبار الاتصال", workspace: "مكان مساحة العمل", tools: "أدوات المساعد", run: "تشغيل",
    unavailable: "الجزء ده لسه مش متاح في النسخة دي.", actions: "الإجراءات", result: "النتيجة",
    confirmAsk: "الخطوة دي مالهاش رجوع:", baseUrl: "عنوان السيرفر", model: "الموديل", enabled: "مفعّل",
    perJob: "الحد للمهمة (دولار)", perDay: "الحد اليومي (دولار)", saved: "اتحفظ.", keyName: "اسم المفتاح",
    keyValue: "قيمة المفتاح", auditEmpty: "مفيش عمليات لسه.",
  },
  en: {
    app: "Magazine Studio", "nav.home": "Home", "nav.stories": "Stories & templates", "nav.fonts": "Fonts",
    "nav.shapes": "Shapes & drawing", "nav.colour": "Colour & taste", "nav.kit": "Connect my systems",
    "nav.qa": "Pre-print QA", "nav.agent": "Assistant", "nav.doctor": "Doctor", "nav.settings": "Settings",
    "nav.audit": "Audit log", "confirm.title": "Confirm an irreversible step", "confirm.yes": "Yes, do it",
    "confirm.no": "No", status: "Studio status", features: "Feature areas", jobs: "Jobs", budget: "AI spend today",
    providers: "AI providers", keys: "Keys (stored encrypted, never shown again)", save: "Save", test: "Test connection",
    workspace: "Workspace folder", tools: "Assistant tools", run: "Run", unavailable: "This area is not available in this build.",
    actions: "Actions", result: "Result", confirmAsk: "This step cannot be undone:", baseUrl: "Server URL",
    model: "Model", enabled: "Enabled", perJob: "Per-job limit (USD)", perDay: "Daily limit (USD)", saved: "Saved.",
    keyName: "Key name", keyValue: "Key value", auditEmpty: "No activity yet.",
  },
};
let lang = "ar";
let csrf = "";
const t = (key) => (I18N[lang] && I18N[lang][key]) || key;
const view = () => document.getElementById("view");
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: { "Content-Type": "application/json" }, credentials: "same-origin" };
  if (init.method !== "GET") init.headers["X-MXS-CSRF"] = csrf;
  if (options.body !== undefined) init.body = JSON.stringify(options.body);
  const response = await fetch(path, init);
  const text = await response.text();
  try { return JSON.parse(text); } catch { return { ok: false, status: response.status, text }; }
}

function applyLanguage() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
  document.getElementById("lang-toggle").textContent = lang === "ar" ? "English" : "العربية";
}

async function confirmAndCall(tool, args) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-text").textContent = `${t("confirmAsk")} ${tool}`;
  const yes = await new Promise((resolve) => {
    document.getElementById("confirm-yes").onclick = () => { dialog.close(); resolve(true); };
    document.getElementById("confirm-no").onclick = () => { dialog.close(); resolve(false); };
    dialog.showModal();
  });
  if (!yes) return { ok: false, code: "CANCELLED_BY_HUMAN" };
  const minted = await api("/api/confirm", { method: "POST", body: { tool, args } });
  return api(`/api/tools/${encodeURIComponent(tool)}`, { method: "POST", body: { args, actor: "ui", confirmation_token: minted.token } });
}

async function callTool(tool, args) {
  const result = await api(`/api/tools/${encodeURIComponent(tool)}`, { method: "POST", body: { args, actor: "ui" } });
  if (result && result.code === "CONFIRMATION_REQUIRED") return confirmAndCall(tool, args);
  return result;
}

function tile(title, inner) { return `<div class="tile"><h2>${esc(title)}</h2>${inner}</div>`; }
function pre(data) { return `<pre>${esc(JSON.stringify(data, null, 1))}</pre>`; }

const VIEWS = {
  async home() {
    const [health, features, jobs, budget] = await Promise.all([api("/api/health"), api("/api/features"),
      api("/api/jobs"), api("/api/budget")]);
    view().innerHTML = tile(t("status"), `<div class="row ${health.ok ? "ok" : "bad"}">${esc(health.app)} <span class="num">${esc(health.version)}</span></div>`)
      + tile(t("features"), `<table>${Object.entries(features.features || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>`)
      + tile(t("budget"), pre(budget)) + tile(t("jobs"), pre((jobs.jobs || []).slice(0, 20)));
  },
  async settings() {
    const settings = await api("/api/settings");
    const secrets = await api("/api/secrets");
    const tv = settings.providers.text_vision, im = settings.providers.image;
    view().innerHTML = tile(t("providers"), `
      <div class="row"><label>Text/Vision · ${t("baseUrl")}</label><input id="tv-url" value="${esc(tv.base_url)}" placeholder="http://gpu-host:8000"></div>
      <div class="row"><label>${t("model")}</label><input id="tv-model" value="${esc(tv.model)}"></div>
      <div class="row"><label>${t("enabled")}</label><input id="tv-on" type="checkbox" ${tv.enabled ? "checked" : ""}></div>
      <div class="row"><label>ComfyUI · ${t("baseUrl")}</label><input id="im-url" value="${esc(im.base_url)}" placeholder="http://gpu-host:8188"></div>
      <div class="row"><label>${t("enabled")}</label><input id="im-on" type="checkbox" ${im.enabled ? "checked" : ""}></div>
      <div class="row"><button class="xb" id="save-providers">${t("save")}</button>
        <button class="xb ghost" id="test-tv">${t("test")} (text)</button><button class="xb ghost" id="test-im">${t("test")} (image)</button></div>
      <div id="provider-result"></div>`)
      + tile(t("keys"), `<div class="row"><label>${t("keyName")}</label><input id="key-name" value="provider.text_vision"></div>
      <div class="row"><label>${t("keyValue")}</label><input id="key-value" type="password" autocomplete="off"></div>
      <div class="row"><button class="xb" id="save-key">${t("save")}</button></div>${pre(secrets)}`)
      + tile(t("budget"), `<div class="row"><label>${t("perJob")}</label><input id="per-job" class="num" value="${esc(settings.budget.per_job_usd)}"></div>
      <div class="row"><label>${t("perDay")}</label><input id="per-day" class="num" value="${esc(settings.budget.per_day_usd)}"></div>
      <div class="row"><label>${t("workspace")}</label><input id="workspace" value="${esc(settings.workspace || "")}"></div>
      <div class="row"><button class="xb" id="save-general">${t("save")}</button></div>`);
    const out = (data) => { document.getElementById("provider-result").innerHTML = pre(data); };
    document.getElementById("save-providers").onclick = async () => out(await api("/api/settings", { method: "POST", body: { providers: {
      text_vision: { base_url: document.getElementById("tv-url").value, model: document.getElementById("tv-model").value, enabled: document.getElementById("tv-on").checked },
      image: { base_url: document.getElementById("im-url").value, enabled: document.getElementById("im-on").checked } } } }));
    document.getElementById("test-tv").onclick = async () => out(await api("/api/providers/text_vision/test", { method: "POST", body: {} }));
    document.getElementById("test-im").onclick = async () => out(await api("/api/providers/image/test", { method: "POST", body: {} }));
    document.getElementById("save-key").onclick = async () => {
      const name = document.getElementById("key-name").value;
      const value = document.getElementById("key-value").value;
      document.getElementById("key-value").value = "";
      await api(`/api/secrets/${encodeURIComponent(name)}`, { method: "POST", body: { value } });
      VIEWS.settings();
    };
    document.getElementById("save-general").onclick = async () => {
      await api("/api/settings", { method: "POST", body: { budget: { per_job_usd: Number(document.getElementById("per-job").value),
        per_day_usd: Number(document.getElementById("per-day").value) }, workspace: document.getElementById("workspace").value || null } });
      out(t("saved"));
    };
  },
  async agent() {
    const tools = await api("/api/tools");
    view().innerHTML = tile(t("tools"), `<div class="row"><select id="tool">${(tools.tools || []).map((x) => `<option value="${esc(x.name)}">${esc(x.name)}${x.irreversible ? " ⚠" : ""} — ${esc(lang === "ar" ? x.description_ar : x.description_en)}</option>`).join("")}</select></div>
      <div class="row"><textarea id="tool-args" rows="6" dir="ltr">{}</textarea></div>
      <div class="row"><button class="xb" id="run-tool">${t("run")}</button></div><div id="tool-result"></div>`);
    document.getElementById("run-tool").onclick = async () => {
      let args = {};
      try { args = JSON.parse(document.getElementById("tool-args").value || "{}"); } catch (error) { args = { _invalid_json: String(error) }; }
      document.getElementById("tool-result").innerHTML = pre(await callTool(document.getElementById("tool").value, args));
    };
  },
  async audit() {
    const audit = await api("/api/audit");
    const rows = (audit.entries || []).map((e) => `<tr><td class="num">${new Date(e.ts * 1000).toLocaleString()}</td><td>${esc(e.actor)}</td><td>${esc(e.tool)}</td><td>${esc(e.outcome)}</td><td>${esc(e.code)}</td></tr>`).join("");
    view().innerHTML = tile(t("nav.audit"), rows ? `<table>${rows}</table>` : t("auditEmpty"));
  },
};

async function featureView(area) {
  const summary = await api(`/api/${area}/summary`);
  if (summary.status === 404 || summary.ok === false && summary.status) { view().innerHTML = tile(t(`nav.${area}`), t("unavailable")); return; }
  const actions = summary.actions || [];
  view().innerHTML = tile(t(`nav.${area}`), pre(summary.facts || summary))
    + tile(t("actions"), actions.map((a, i) => `<div class="row"><button class="xb ghost" data-action="${i}">${esc(lang === "ar" ? a.label_ar : a.label_en)}</button></div>`).join("") + `<div id="action-result"></div>`);
  view().querySelectorAll("[data-action]").forEach((button) => {
    button.onclick = async () => {
      const action = actions[Number(button.dataset.action)];
      document.getElementById("action-result").innerHTML = pre(await callTool(action.tool, action.args || {}));
    };
  });
}

async function route() {
  const name = (location.hash || "#home").slice(1);
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${name}`));
  const area = { stories: "factory", fonts: "fonts", shapes: "shapes", colour: "colour", kit: "kit", qa: "qa", doctor: "doctor" }[name];
  try {
    if (VIEWS[name]) await VIEWS[name]();
    else if (area) await featureView(area);
    else await VIEWS.home();
  } catch (error) {
    view().innerHTML = tile("⚠", esc(String(error)));
  }
}

async function boot() {
  const session = await api("/api/session");
  csrf = session.csrf || "";
  try { lang = localStorage.getItem("mxs.lang") || "ar"; } catch { lang = "ar"; }
  let theme = "day";
  try { theme = localStorage.getItem("mxs.theme") || "day"; } catch { theme = "day"; }
  document.documentElement.dataset.theme = theme;
  document.getElementById("lang-toggle").onclick = () => { lang = lang === "ar" ? "en" : "ar"; try { localStorage.setItem("mxs.lang", lang); } catch {} applyLanguage(); route(); };
  document.getElementById("theme-toggle").onclick = () => {
    const next = document.documentElement.dataset.theme === "day" ? "night" : "day";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("mxs.theme", next); } catch {}
  };
  window.addEventListener("hashchange", route);
  applyLanguage();
  route();
}

if (typeof window !== "undefined" && typeof document !== "undefined") boot();
