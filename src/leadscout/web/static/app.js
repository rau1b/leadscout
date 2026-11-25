// "Back" from a lead returns to the exact list you came from: same filters, same scroll position.
(function () {
  var LISTS = { "/": "Today", "/leads": "Leads", "/pitches": "Pitches", "/replies": "Replies", "/deals": "Deals", "/sent": "Sent", "/find": "Find leads" };
  var KEY = "leadscout-back";
  var store;
  try { store = window.sessionStorage; } catch (e) { return; }

  var path = location.pathname;
  var label = LISTS[path];
  if (path === "/leads") {
    var status = new URLSearchParams(location.search).get("status");
    if (status === "replied") label = "Replies";
    if (status === "opted_out") label = "Opt-outs";
  }

  if (label) {
    var here = path + location.search;
    var saved = null;
    try { saved = JSON.parse(store.getItem(KEY) || "null"); } catch (e) {}
    // Coming back from a lead: put the list where it was.
    if (saved && saved.restore && saved.url === here) {
      window.scrollTo(0, saved.y || 0);
      saved.restore = false;
      store.setItem(KEY, JSON.stringify(saved));
    }
    window.addEventListener("pagehide", function () {
      store.setItem(KEY, JSON.stringify({ url: here, label: label, y: window.scrollY, restore: false }));
    });
  }

  var link = document.getElementById("backlink");
  if (link) {
    var from = null;
    try { from = JSON.parse(store.getItem(KEY) || "null"); } catch (e) {}
    if (from && from.url) {
      link.href = from.url;
      link.querySelector("span").textContent = "Back to " + from.label;
    }
    link.addEventListener("click", function () {
      if (from) { from.restore = true; store.setItem(KEY, JSON.stringify(from)); }
    });
  }
})();


// City picker: suggestions from the offline list of Indian places, keyboard and mouse.
(function () {
  var input = document.getElementById("city");
  var list = document.getElementById("city-list");
  var hidden = document.getElementById("place_id");
  var picked = document.getElementById("city-picked");
  if (!input || !list) return;
  var items = [], active = -1, timer = null, defaultHint = picked.textContent;
  // USA: no offline list, so no suggestions; the city is looked up when the search starts.
  function us() { var c = document.querySelector("input[name=country]:checked"); return c && c.value === "US"; }
  document.querySelectorAll("input[name=country]").forEach(function (r) {
    r.addEventListener("change", function () {
      defaultHint = us() ? picked.dataset.us : picked.dataset.in;
      picked.textContent = defaultHint;
      picked.classList.remove("ok");
      hidden.value = "";
      input.placeholder = us() ? "e.g. Austin, TX" : "Start typing, e.g. Margao, Warangal, Hyderabad";
      close();
    });
  });

  function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); active = -1; }
  function highlight(i) {
    var opts = list.querySelectorAll("[role=option]");
    opts.forEach(function (o, n) { o.setAttribute("aria-selected", n === i ? "true" : "false"); });
    active = i;
    if (opts[i]) { input.setAttribute("aria-activedescendant", opts[i].id); opts[i].scrollIntoView({ block: "nearest" }); }
  }
  function choose(i) {
    var p = items[i];
    if (!p) return;
    input.value = p.name;
    hidden.value = p.id;
    picked.textContent = "Will search: " + p.label;
    picked.classList.add("ok");
    close();
  }
  function render() {
    list.innerHTML = "";
    if (!items.length) {
      var li = document.createElement("li");
      li.className = "combo-empty";
      li.textContent = "No Indian place by that name. Check the spelling.";
      list.appendChild(li);
    }
    items.forEach(function (p, i) {
      var li = document.createElement("li");
      li.id = "city-opt-" + i;
      li.setAttribute("role", "option");
      li.textContent = p.label;
      li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(i); });
      list.appendChild(li);
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    highlight(items.length ? 0 : -1);
  }
  input.addEventListener("input", function () {
    hidden.value = "";
    picked.textContent = defaultHint;
    picked.classList.remove("ok");
    clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2 || us()) { close(); return; }
    timer = setTimeout(function () {
      fetch("/places?q=" + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (data) {
        if (input.value.trim() !== q) return;
        items = data;
        render();
      });
    }, 120);
  });
  input.addEventListener("keydown", function (e) {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); highlight(Math.min(active + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); highlight(Math.max(active - 1, 0)); }
    else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(active); }
    else if (e.key === "Escape") { close(); }
  });
  input.addEventListener("blur", function () { setTimeout(close, 100); });
})();
