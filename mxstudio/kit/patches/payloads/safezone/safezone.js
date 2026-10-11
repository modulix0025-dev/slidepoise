// MODULEX_MAG P-SAFEZONE: draws the safe-zone frame over the editor's page images.
// Reads /api/editor/mag/safezone/<order>; the order ref is taken from the page URL (?order= or last path part).
(function () {
  "use strict";
  var q = new URLSearchParams(location.search);
  var order = q.get("order") || location.pathname.split("/").filter(Boolean).pop();
  if (!order) { return; }
  fetch("/api/editor/mag/safezone/" + encodeURIComponent(order), { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (g) {
      if (!g || !g.ok) { return; }
      var imgs = document.querySelectorAll("[data-slide] img, img[data-slide]");
      imgs.forEach(function (img) {
        var host = img.parentElement; if (!host) { return; }
        var t = g.trim_emu, s = g.safe_emu;
        var box = document.createElement("div");
        box.className = "mx-mag-safezone";
        box.title = "منطقة الأمان · safe zone";
        box.style.cssText = "position:absolute;pointer-events:none;border:1px dashed #d33;" +
          "left:" + (100 * s[0] / t[2]) + "%;top:" + (100 * s[1] / t[3]) + "%;" +
          "width:" + (100 * (s[2] - s[0]) / t[2]) + "%;height:" + (100 * (s[3] - s[1]) / t[3]) + "%;";
        if (getComputedStyle(host).position === "static") { host.style.position = "relative"; }
        host.appendChild(box);
      });
    })
    .catch(function () { /* overlay is advisory; never break the editor */ });
})();
