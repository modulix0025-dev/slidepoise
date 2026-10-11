// MODULEX_MAG P-PROOF: adds an "approve this proof" button to the editor page.
(function () {
  "use strict";
  var q = new URLSearchParams(location.search);
  var order = q.get("order") || location.pathname.split("/").filter(Boolean).pop();
  if (!order) { return; }
  var base = "/api/editor/mag/proof/" + encodeURIComponent(order);
  var btn = document.createElement("button");
  btn.type = "button";
  btn.className = "mx-mag-proof";
  btn.textContent = "موافق على البروفة · Approve proof";
  btn.addEventListener("click", function () {
    btn.disabled = true;
    fetch(base + "/approve", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: String(Date.now()) }) })
      .then(function (r) { return r.json(); })
      .then(function (j) { btn.textContent = j.ok ? "تمت الموافقة · Approved" : "تعذر الحفظ · Failed"; })
      .catch(function () { btn.disabled = false; });
  });
  document.body.appendChild(btn);
})();
