/* ModuleX Magazine Studio - drawing canvas (vanilla JS, no dependencies).
 *
 * Draws on an SVG board; every path is kept as server path-model commands (see geometry.js).
 * Server endpoints (mxstudio/shapes/service.py ENDPOINTS):
 *   POST /api/shapes/boolean        {op, subject:[{width,height,commands}], clip:[...]}
 *   POST /api/shapes/canvas/commit  {width,height,paths:[{commands,closed,fill,stroke}],line,save,author,...}
 *   GET  /api/shapes/presets        POST /api/shapes/presets/xml {prst, adj}
 * Mutating calls carry the CSRF token from GET /api/session (same rule as the main UI).
 */
(function () {
  "use strict";
  const G = window.MXGeom;
  const W = 1000, H = 700;
  const $ = (id) => document.getElementById(id);
  const board = $("board"), layer = $("layer"), overlay = $("overlay");
  const NS = "http://www.w3.org/2000/svg";
  let csrf = "";
  let tool = "pen";
  let paths = [];          // {commands, closed, fill, stroke, line:{width_pt,dash,cap}}
  let history = [];
  let selected = new Set();
  let pen = null;          // {anchors: [], dragging: false}
  let free = null;         // [[x,y,pressure], ...]

  function status(ar, en) { $("status").textContent = ar + (en ? " — " + en : ""); }

  async function api(path, body) {
    const init = { method: body === undefined ? "GET" : "POST", headers: {}, credentials: "same-origin" };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.headers["X-MXS-CSRF"] = csrf;
      init.body = JSON.stringify(body);
    }
    const res = await fetch(path, init);
    const data = await res.json().catch(() => ({ ok: false, ar: "رد مش مفهوم", en: "unreadable reply" }));
    if (!res.ok || data.ok === false) throw data;
    return data;
  }

  function svgPoint(evt) {
    const pt = board.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const p = pt.matrixTransform(board.getScreenCTM().inverse());
    return [p.x, p.y];
  }

  function allAnchors() {
    const out = [];
    for (const p of paths) for (const c of p.commands) if (c.length >= 3) out.push([c[c.length - 2], c[c.length - 1]]);
    if (pen) for (const a of pen.anchors) out.push([a.x, a.y]);
    return out;
  }

  function snap(p, evt, from) {
    return G.snapPoint(p, {
      anchors: $("snap-anchor").checked ? allAnchors() : [],
      grid: $("snap-grid").checked ? Number($("grid").value) || 10 : 0,
      angleFrom: ($("snap-angle").checked || (evt && evt.shiftKey)) && from ? from : null,
      angleStep: 15, tolerance: 8,
    }).point;
  }

  function lineStyle() {
    return { width_pt: Number($("stroke-w").value) || 0, dash: $("stroke-dash").value, cap: $("stroke-cap").value };
  }

  function symmetry() {
    return { mirror: $("sym-mirror").checked, radial: Math.max(1, Number($("sym-radial").value) || 1), cx: W / 2, cy: H / 2 };
  }

  function pushPath(commands, closed, filled) {
    history.push(JSON.stringify(paths));
    for (const copy of G.symmetryCopies(commands, symmetry())) {
      paths.push({ commands: copy, closed, fill: filled && closed, stroke: true, line: lineStyle() });
    }
    render();
  }

  function render() {
    layer.textContent = "";
    paths.forEach((p, i) => {
      const el = document.createElementNS(NS, "path");
      el.setAttribute("d", G.toSvgD(p.commands));
      el.setAttribute("fill", p.fill ? "#e63946" : "none");
      el.setAttribute("fill-rule", "evenodd");
      const w = (p.line && p.line.width_pt) || 0;
      el.setAttribute("stroke", p.stroke && w ? "#222" : "none");
      el.setAttribute("stroke-width", String(w * 1.33));
      el.setAttribute("stroke-dasharray", G.dashArray(p.line ? p.line.dash : "solid", Math.max(w, 1)));
      el.setAttribute("stroke-linecap", { rnd: "round", flat: "butt", sq: "square" }[(p.line || {}).cap] || "round");
      if (selected.has(i)) el.classList.add("sel");
      el.dataset.index = String(i);
      layer.appendChild(el);
    });
    overlay.textContent = "";
    if (pen && pen.anchors.length) {
      const pv = document.createElementNS(NS, "path");
      pv.setAttribute("d", G.toSvgD(G.penToCommands(pen.anchors, false)));
      pv.setAttribute("fill", "none"); pv.setAttribute("stroke", "#1d70b8"); pv.setAttribute("stroke-width", "1.5");
      overlay.appendChild(pv);
      for (const a of pen.anchors) {
        for (const h of [a.hin, a.hout]) if (h) {
          const c = document.createElementNS(NS, "circle");
          c.setAttribute("cx", h[0]); c.setAttribute("cy", h[1]); c.setAttribute("r", "3"); c.setAttribute("class", "handle");
          overlay.appendChild(c);
        }
        const r = document.createElementNS(NS, "rect");
        r.setAttribute("x", a.x - 4); r.setAttribute("y", a.y - 4); r.setAttribute("width", "8"); r.setAttribute("height", "8");
        r.setAttribute("class", "anchor"); overlay.appendChild(r);
      }
    }
    if (free && free.length > 1) {
      const outline = G.getStroke(free, freehandOptions());
      const fp = document.createElementNS(NS, "path");
      fp.setAttribute("d", G.toSvgD(G.outlineToCommands(outline)));
      fp.setAttribute("fill", "#e6394699");
      overlay.appendChild(fp);
    }
  }

  function freehandOptions() {
    const s = Number($("fh-smooth").value) / 100;
    return { size: Number($("fh-size").value), smoothing: s, streamline: s, thinning: Number($("fh-thin").value) / 100,
      simulatePressure: true };
  }

  function finishPen(closed) {
    if (pen && pen.anchors.length > 1) pushPath(G.penToCommands(pen.anchors, closed), closed, $("fill-on").checked);
    pen = null;
    render();
  }

  board.addEventListener("pointerdown", (evt) => {
    board.setPointerCapture(evt.pointerId);
    const raw = svgPoint(evt);
    if (tool === "select") {
      const idx = evt.target && evt.target.dataset ? evt.target.dataset.index : undefined;
      if (idx === undefined) selected.clear();
      else if (evt.shiftKey) selected.has(+idx) ? selected.delete(+idx) : selected.add(+idx);
      else { selected.clear(); selected.add(+idx); }
      render();
      return;
    }
    if (tool === "freehand") { free = [[raw[0], raw[1], evt.pressure || 0.5]]; return; }
    // pen
    pen = pen || { anchors: [], dragging: false };
    const last = pen.anchors.length ? [pen.anchors[pen.anchors.length - 1].x, pen.anchors[pen.anchors.length - 1].y] : null;
    const p = snap(raw, evt, last);
    if (pen.anchors.length > 2 && G.dist(p, [pen.anchors[0].x, pen.anchors[0].y]) < 8) { finishPen(true); return; }
    pen.anchors.push({ x: p[0], y: p[1], hin: null, hout: null });
    pen.dragging = true;
    render();
  });

  board.addEventListener("pointermove", (evt) => {
    const raw = svgPoint(evt);
    if (free) { free.push([raw[0], raw[1], evt.pressure || 0.5]); render(); return; }
    if (pen && pen.dragging) {
      const a = pen.anchors[pen.anchors.length - 1];
      if (G.dist(raw, [a.x, a.y]) > 3) { pen.anchors[pen.anchors.length - 1] = G.smoothHandles(a, raw); render(); }
    }
  });

  board.addEventListener("pointerup", () => {
    if (free) {
      if (free.length > 2) pushPath(G.outlineToCommands(G.getStroke(free, freehandOptions())), true, true);
      free = null;
      render();
    }
    if (pen) pen.dragging = false;
  });

  board.addEventListener("dblclick", () => finishPen(false));
  document.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") finishPen(false);
    if (evt.key === "Escape") { pen = null; free = null; render(); }
    if ((evt.ctrlKey || evt.metaKey) && evt.key === "z") undo();
  });

  function undo() {
    if (!history.length) return;
    paths = JSON.parse(history.pop());
    selected.clear();
    render();
  }

  $("tools").addEventListener("click", (evt) => {
    const b = evt.target.closest("button[data-tool]");
    if (!b) return;
    tool = b.dataset.tool;
    for (const x of $("tools").querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b));
    if (tool !== "pen") finishPen(false);
  });

  $("snap-grid").addEventListener("change", () => { $("gridrect").style.display = $("snap-grid").checked ? "" : "none"; });
  $("undo").addEventListener("click", undo);
  $("clear").addEventListener("click", () => { history.push(JSON.stringify(paths)); paths = []; selected.clear(); render(); });

  for (const b of document.querySelectorAll("button[data-op]")) {
    b.addEventListener("click", async () => {
      const idx = [...selected].sort((a, c) => a - c);
      if (idx.length < 2) { status("اختار شكلين أو أكتر (Shift + نقرة)", "select two or more shapes (Shift+click)"); return; }
      const asGeom = (i) => ({ width: W, height: H, commands: paths[i].commands });
      const op = b.dataset.op;
      const body = op === "union" ? { op, subject: idx.map(asGeom), clip: [] }
        : { op, subject: [asGeom(idx[0])], clip: idx.slice(1).map(asGeom) };
      try {
        const res = await api("/api/shapes/boolean", body);
        history.push(JSON.stringify(paths));
        const merged = res.geometry.parts.map((p) => ({ commands: p.commands, closed: true, fill: true, stroke: true, line: lineStyle() }));
        paths = paths.filter((_, i) => !selected.has(i)).concat(merged);
        selected.clear();
        render();
        status("تم", op);
      } catch (err) { status(err.ar || "حصلت مشكلة", err.en || String(err)); }
    });
  }

  async function commit(save) {
    if (!paths.length) { status("ارسم حاجة الأول", "draw something first"); return; }
    const body = { width: W, height: H, line: lineStyle(), style: $("style").value, name_ar: $("name").value,
      name_en: $("name").value, save, author: $("author").value,
      paths: paths.map((p) => ({ commands: p.commands, closed: p.closed, fill: p.fill, stroke: p.stroke })) };
    try {
      const res = await api("/api/shapes/canvas/commit", body);
      status(save ? "اتحفظ في المكتبة" : "اتحول لشكل قابل للتعديل",
        (save ? "saved " + res.asset_id : "custGeom ready") + " (" + res.custgeom.length + " bytes)");
      window.dispatchEvent(new CustomEvent("mxs-shape-committed", { detail: res }));
    } catch (err) { status(err.ar || "حصلت مشكلة", err.en || String(err)); }
  }
  $("commit").addEventListener("click", () => commit(false));
  $("save").addEventListener("click", () => commit(true));

  /* ---- preset geometries with adjust handles ---- */
  let presetCatalog = [];
  function renderPresetList() {
    const q = $("preset-filter").value.trim().toLowerCase();
    const list = $("preset-list");
    list.textContent = "";
    for (const p of presetCatalog.filter((x) => !q || x.prst.toLowerCase().includes(q) || x.category_en.toLowerCase().includes(q))) {
      const d = document.createElement("div");
      d.textContent = p.prst + "  (" + p.handles.length + ")";
      d.title = p.category_ar + " — " + p.category_en;
      d.addEventListener("click", () => showHandles(p));
      list.appendChild(d);
    }
  }
  async function showHandles(p) {
    const box = $("preset-handles");
    box.textContent = "";
    const values = {};
    const update = async () => {
      try { $("preset-xml").textContent = (await api("/api/shapes/presets/xml", { prst: p.prst, adj: values })).xml; }
      catch (err) { $("preset-xml").textContent = err.en || String(err); }
    };
    for (const h of p.handles) {
      values[h.name] = h.default;
      const lab = document.createElement("label");
      lab.textContent = p.prst + "." + h.name + (h.kind === "angle" ? " (°)" : " (%)") + " ";
      const r = document.createElement("input");
      r.type = "range"; r.min = h.min; r.max = h.max; r.value = h.default;
      r.step = h.kind === "angle" ? 60000 : 100;
      r.addEventListener("input", () => { values[h.name] = Number(r.value); update(); });
      lab.appendChild(r);
      box.appendChild(lab);
    }
    if (!p.handles.length) box.textContent = "مفيش أذرع ضبط — no adjust handles";
    update();
  }
  $("preset-filter").addEventListener("input", renderPresetList);

  (async function init() {
    try {
      csrf = (await api("/api/session")).csrf || "";
    } catch (err) { status("افتح الاستوديو من الشاشة الرئيسية الأول", "open the Studio window first"); }
    try {
      presetCatalog = (await api("/api/shapes/presets")).presets || [];
      renderPresetList();
    } catch (err) { /* presets panel stays empty offline */ }
    render();
  })();
})();
