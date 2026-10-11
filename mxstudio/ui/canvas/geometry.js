/* ModuleX Magazine Studio - drawing-canvas geometry (dependency-free, browser + Node).
 *
 * Path commands match the server's path model (mxstudio/shapes/custgeom.py):
 *   ["M",x,y] ["L",x,y] ["C",x1,y1,x2,y2,x,y] ["Q",x1,y1,x,y] ["Z"]
 *
 * Freehand outlines port the algorithm of perfect-freehand (Steve Ruiz, MIT): streamlined
 * input points, pressure (real or simulated from speed), thinning, smoothing and round caps,
 * turned into a closed outline polygon that prints as a filled shape. No code or npm package
 * is copied; parameters keep perfect-freehand's meaning.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MXGeom = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
  const mul = (a, k) => [a[0] * k, a[1] * k];
  const len = (a) => Math.hypot(a[0], a[1]);
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const unit = (a) => { const l = len(a); return l ? [a[0] / l, a[1] / l] : [0, 0]; };
  const perp = (a) => [a[1], -a[0]];
  const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  const rotAround = (p, c, rad) => {
    const s = Math.sin(rad), co = Math.cos(rad), x = p[0] - c[0], y = p[1] - c[1];
    return [c[0] + x * co - y * s, c[1] + x * s + y * co];
  };
  const r4 = (v) => Math.round(v * 10000) / 10000;

  /* ---------------------------------------------------------------- freehand */
  const DEFAULTS = { size: 16, thinning: 0.5, smoothing: 0.5, streamline: 0.5, simulatePressure: true, last: true };

  function strokePoints(input, opts) {
    const o = Object.assign({}, DEFAULTS, opts || {});
    const pts = input.map((p) => (Array.isArray(p) ? [p[0], p[1], p[2] == null ? 0.5 : p[2]] : [p.x, p.y, p.pressure == null ? 0.5 : p.pressure]));
    if (pts.length === 0) return [];
    if (pts.length === 1) pts.push([pts[0][0] + 1, pts[0][1] + 1, pts[0][2]]);
    const t = 0.15 + (1 - o.streamline) * 0.85;
    const out = [{ point: [pts[0][0], pts[0][1]], pressure: pts[0][2], vector: [1, 1], distance: 0, running: 0 }];
    let prev = out[0];
    for (let i = 1; i < pts.length; i++) {
      const point = (o.last && i === pts.length - 1) ? [pts[i][0], pts[i][1]] : lerp(prev.point, [pts[i][0], pts[i][1]], t);
      const d = dist(point, prev.point);
      if (d < 1e-6) continue;
      const running = prev.running + d;
      if (i < pts.length - 1 && running < o.size / 3 && out.length < 2) continue;
      prev = { point, pressure: pts[i][2], vector: unit(sub(prev.point, point)), distance: d, running };
      out.push(prev);
    }
    out[0].vector = out[1] ? out[1].vector : [0, 0];
    return out;
  }

  function strokeOutline(points, opts) {
    const o = Object.assign({}, DEFAULTS, opts || {});
    if (!points.length) return [];
    const total = points[points.length - 1].running;
    const minD = Math.pow(o.size * o.smoothing, 2) / 4;
    const left = [], right = [];
    let prevPressure = points[0].pressure, radius = o.size / 2;
    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      let pressure = p.pressure;
      if (o.simulatePressure) {
        const sp = Math.min(1, p.distance / o.size);
        const rp = Math.min(1, 1 - sp);
        pressure = Math.min(1, prevPressure + (rp - prevPressure) * (sp * 0.275));
      }
      prevPressure = pressure;
      radius = o.thinning ? Math.max(0.01, o.size * (0.5 - o.thinning * (0.5 - pressure))) : o.size / 2;
      const next = points[i + 1] ? points[i + 1].vector : p.vector;
      const dir = unit(add(p.vector, next));
      const off = mul(perp(dir.every((v) => v === 0) ? p.vector : dir), radius);
      const l = sub(p.point, off), r = add(p.point, off);
      if (i === 0 || i === points.length - 1 || !left.length || dist(l, left[left.length - 1]) ** 2 > minD) left.push(l);
      if (i === 0 || i === points.length - 1 || !right.length || dist(r, right[right.length - 1]) ** 2 > minD) right.push(r);
    }
    // round caps: half circles from one side to the other, bulging away from the stroke
    const first = points[0], last = points[points.length - 1];
    const fwd = mul(last.vector, -1), back = first.vector;
    const endCap = capPoints(last.point, left[left.length - 1], right[right.length - 1], fwd);
    const startCap = capPoints(first.point, right[0], left[0], back);
    return left.concat(endCap, right.slice().reverse(), startCap);
  }

  function capPoints(center, from, to, via, steps) {
    steps = steps || 8;
    const r = dist(from, center);
    if (r < 1e-9) return [];
    const a0 = Math.atan2(from[1] - center[1], from[0] - center[0]);
    let sweep = Math.atan2(to[1] - center[1], to[0] - center[0]) - a0;
    while (sweep <= -Math.PI) sweep += 2 * Math.PI;
    while (sweep > Math.PI) sweep -= 2 * Math.PI;
    const mid = a0 + sweep / 2;
    if (Math.cos(mid) * via[0] + Math.sin(mid) * via[1] < 0) sweep = sweep > 0 ? sweep - 2 * Math.PI : sweep + 2 * Math.PI;
    const out = [];
    for (let k = 1; k < steps; k++) {
      const a = a0 + sweep * k / steps;
      out.push([center[0] + Math.cos(a) * r, center[1] + Math.sin(a) * r]);
    }
    return out;
  }

  function getStroke(input, opts) { return strokeOutline(strokePoints(input, opts), opts); }

  /* outline polygon -> smooth closed path of quadratic Beziers through edge midpoints */
  function outlineToCommands(poly) {
    if (poly.length < 3) return [];
    const cmds = [];
    const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const m0 = mid(poly[0], poly[1]);
    cmds.push(["M", r4(m0[0]), r4(m0[1])]);
    for (let i = 1; i <= poly.length; i++) {
      const p = poly[i % poly.length], q = poly[(i + 1) % poly.length];
      const m = mid(p, q);
      cmds.push(["Q", r4(p[0]), r4(p[1]), r4(m[0]), r4(m[1])]);
    }
    cmds.push(["Z"]);
    return cmds;
  }

  /* ---------------------------------------------------------------- pen / bezier */
  // anchor: {x, y, hin: [x,y] | null, hout: [x,y] | null}
  function penToCommands(anchors, closed) {
    if (!anchors.length) return [];
    const cmds = [["M", r4(anchors[0].x), r4(anchors[0].y)]];
    const seg = (a, b) => {
      if (!a.hout && !b.hin) cmds.push(["L", r4(b.x), r4(b.y)]);
      else {
        const c1 = a.hout || [a.x, a.y], c2 = b.hin || [b.x, b.y];
        cmds.push(["C", r4(c1[0]), r4(c1[1]), r4(c2[0]), r4(c2[1]), r4(b.x), r4(b.y)]);
      }
    };
    for (let i = 1; i < anchors.length; i++) seg(anchors[i - 1], anchors[i]);
    if (closed && anchors.length > 2) { seg(anchors[anchors.length - 1], anchors[0]); cmds.push(["Z"]); }
    return cmds;
  }

  function smoothHandles(anchor, dragTo) {
    // dragging from an anchor creates mirrored handles (symmetric smooth node)
    const d = sub(dragTo, [anchor.x, anchor.y]);
    return Object.assign({}, anchor, { hout: [anchor.x + d[0], anchor.y + d[1]], hin: [anchor.x - d[0], anchor.y - d[1]] });
  }

  /* ---------------------------------------------------------------- snapping */
  function snapPoint(p, o) {
    o = o || {};
    const tol = o.tolerance == null ? 8 : o.tolerance;
    let best = null, bestD = tol;
    for (const a of o.anchors || []) {
      const d = dist(p, a);
      if (d <= bestD) { best = [a[0], a[1]]; bestD = d; }
    }
    if (best) return { point: best, kind: "anchor" };
    if (o.angleFrom && o.angleStep) {
      const v = sub(p, o.angleFrom), l = len(v);
      const step = o.angleStep * Math.PI / 180;
      const ang = Math.round(Math.atan2(v[1], v[0]) / step) * step;
      return { point: [r4(o.angleFrom[0] + Math.cos(ang) * l), r4(o.angleFrom[1] + Math.sin(ang) * l)], kind: "angle" };
    }
    if (o.grid) return { point: [Math.round(p[0] / o.grid) * o.grid, Math.round(p[1] / o.grid) * o.grid], kind: "grid" };
    return { point: [p[0], p[1]], kind: "none" };
  }

  /* ---------------------------------------------------------------- symmetry */
  function mapCommands(cmds, fn) {
    return cmds.map((c) => {
      if (c[0] === "Z") return ["Z"];
      const out = [c[0]];
      for (let i = 1; i < c.length; i += 2) { const q = fn([c[i], c[i + 1]]); out.push(r4(q[0]), r4(q[1])); }
      return out;
    });
  }
  function mirrorCommands(cmds, axisX) { return mapCommands(cmds, (p) => [2 * axisX - p[0], p[1]]); }
  function mirrorCommandsY(cmds, axisY) { return mapCommands(cmds, (p) => [p[0], 2 * axisY - p[1]]); }
  function radialCopies(cmds, n, cx, cy) {
    const out = [];
    for (let k = 1; k < n; k++) out.push(mapCommands(cmds, (p) => rotAround(p, [cx, cy], 2 * Math.PI * k / n)));
    return out;
  }
  function symmetryCopies(cmds, sym) {
    // sym: {mirror: bool, radial: N, cx, cy}
    let all = [cmds];
    if (sym && sym.mirror) all = all.concat(all.map((c) => mirrorCommands(c, sym.cx)));
    if (sym && sym.radial > 1) {
      const base = all.slice();
      for (const c of base) all = all.concat(radialCopies(c, sym.radial, sym.cx, sym.cy));
    }
    return all;
  }

  /* ---------------------------------------------------------------- svg */
  function toSvgD(cmds) {
    return cmds.map((c) => c[0] + (c.length > 1 ? c.slice(1).join(" ") : "")).join(" ");
  }
  const DASHES = { solid: "", dash: "4 2", dot: "0.1 2", dashDot: "4 2 0.1 2", longDash: "8 3" };
  function dashArray(style, width) {
    const d = DASHES[style] || "";
    return d.split(" ").filter(Boolean).map((v) => r4(parseFloat(v) * width)).join(" ");
  }
  // DrawingML a:ln/@prstDash values for the same names
  const PRST_DASH = { solid: "solid", dash: "dash", dot: "sysDot", dashDot: "dashDot", longDash: "lgDash" };

  return { getStroke, strokePoints, strokeOutline, outlineToCommands, penToCommands, smoothHandles, snapPoint,
    mirrorCommands, mirrorCommandsY, radialCopies, symmetryCopies, mapCommands, toSvgD, dashArray, PRST_DASH, dist };
});
