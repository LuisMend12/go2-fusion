/* Oak workspace v2: sidebar (search, page tree, work, recent), reading pane
   (page, backlinks, ask box) and a fixed 2D map of the pages.
   Data: graph.json (scripts/wiki/build_graph.py), else sample-graph.json. */
(function () {
  "use strict";

  const OAK_COLOR = "#f0e6cf";
  const HUB_COLORS = {
    driving: "#e39a62", driver: "#78a6e8", senses: "#5fc9a3", "maps-nav": "#d9c160",
    brains: "#d684bf", "lab-setup": "#67c3d4", team: "#a397e8",
  };
  const FALLBACK = ["#e88f86", "#9bd08a", "#d8b4f0", "#8fd3e0", "#e6c27a"];
  const BG = "#0f0e12";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const $ = (id) => document.getElementById(id);

  // ---------- tiny DOM helper (always textContent for data) ----------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") el.style.cssText = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
    return el;
  }
  const dot = (color) => h("span", { class: "dot", style: "background:" + color, "aria-hidden": "true" });

  // ---------- state ----------
  let D = null;               // graph data
  const byId = {}, byPath = {}, kids = {}, nbrs = {}, people = {};
  let hubs = [], current = null, filterPerson = null;

  // ---------- load ----------
  function getJSON(url) {
    return fetch(url, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(url + " " + r.status);
      return r.json();
    });
  }
  getJSON("graph.json")
    .catch(() => getJSON("sample-graph.json").then((d) => Object.assign(d, { sample: true })))
    .then(start)
    .catch((err) => {
      $("content").innerHTML = "";
      $("content").append(h("p", { class: "error" },
        "Could not load the wiki data. Run python3 scripts/wiki/build_graph.py, then reload. (" + err.message + ")"));
    });

  function start(data) {
    D = normalize(data);
    index();
    if (D.nodes.some((n) => typeof n.x !== "number" || typeof n.y !== "number")) layout();
    renderTree(); renderWork(); renderRecent(); renderPeople(); renderLegend(); renderDataNote();
    setupSearch(); setupAsk(); setupDrawer();
    Graph.init();
    window.addEventListener("hashchange", route);
    route();
  }

  function normalize(d) {
    const arr = (x) => (Array.isArray(x) ? x : []);
    const out = {
      repo: d.repo || "maxhawksby/go2-fusion",
      branch: d.branch || "master",
      published: d.published !== false,
      generated_at: d.generated_at || null,
      sample: !!d.sample,
      people: arr(d.people), nodes: arr(d.nodes), edges: arr(d.edges),
      work: arr(d.work), questions: arr(d.questions), recent: arr(d.recent),
    };
    out.nodes.forEach((n) => {
      n.code = arr(n.code); n.markdown = n.markdown || ""; n.depth = n.depth ?? (n.id === "oak" ? 0 : 2);
      n.hub = n.hub || (n.depth === 1 ? n.id : null);
    });
    out.work.forEach((w) => { w.pages = arr(w.pages); w.assignees = arr(w.assignees); });
    out.recent.forEach((r) => { r.pages = arr(r.pages); });
    return out;
  }

  function index() {
    D.people.forEach((p) => { people[p.id] = p; });
    D.nodes.forEach((n) => { byId[n.id] = n; if (n.path) byPath[n.path] = n; kids[n.id] = []; nbrs[n.id] = new Set(); });
    D.nodes.forEach((n) => { if (n.parent && kids[n.parent]) kids[n.parent].push(n); });
    D.edges.forEach((e) => {
      if (!byId[e.source] || !byId[e.target]) return;
      nbrs[e.source].add(e.target); nbrs[e.target].add(e.source);
    });
    D.nodes.forEach((n) => {
      if (!Array.isArray(n.backlinks)) {
        n.backlinks = D.edges.filter((e) => e.target === n.id && byId[e.source]).map((e) => e.source);
      }
    });
    // reading order: where each child is first mentioned in its parent's text
    const order = (parent, list) => list.sort((a, b) => pos(parent, a) - pos(parent, b) || a.title.localeCompare(b.title));
    const pos = (parent, n) => { const i = parent.markdown.indexOf(n.id + ".md"); return i < 0 ? 1e9 : i; };
    Object.keys(kids).forEach((id) => order(byId[id], kids[id]));
    hubs = kids.oak ? kids.oak.filter((n) => n.depth === 1) : D.nodes.filter((n) => n.depth === 1);
  }

  // ---------- colors, people, scope ----------
  function hubColor(hubId) {
    if (HUB_COLORS[hubId]) return HUB_COLORS[hubId];
    const i = Math.max(0, hubs.findIndex((x) => x.id === hubId));
    return FALLBACK[i % FALLBACK.length];
  }
  const nodeColor = (n) => (n.depth === 0 ? OAK_COLOR : hubColor(n.hub));
  const personColor = (pid) => (people[pid] && people[pid].color) || "#9a958c";
  const personName = (pid, fallback) => (people[pid] && people[pid].name) || fallback || "someone";
  const workPerson = (w) => w.person || w.assignees[0] || null;
  function descendants(id) {
    const out = [id];
    for (let i = 0; i < out.length; i++) (kids[out[i]] || []).forEach((k) => out.push(k.id));
    return out;
  }
  const scopeOf = (n) => new Set(n.depth < 2 ? descendants(n.id) : [n.id]);
  const workOn = (ids) => D.work.filter((w) => w.pages.some((p) => ids.has(p)));
  function personPages(pid) {
    const s = new Set();
    D.work.forEach((w) => { if (w.person === pid || w.assignees.includes(pid)) w.pages.forEach((p) => s.add(p)); });
    D.recent.forEach((r) => { if (r.person === pid) r.pages.forEach((p) => s.add(p)); });
    return s;
  }
  const workByPage = {};
  function workIndex() { D.work.forEach((w) => w.pages.forEach((p) => { (workByPage[p] = workByPage[p] || []).push(w); })); }

  // ---------- time ----------
  function rel(iso) {
    if (!iso) return "";
    const t = Date.parse(iso);
    if (isNaN(t)) return "";
    const s = (Date.now() - t) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    const d = Math.round(s / 86400);
    if (d === 1) return "yesterday";
    if (d < 30) return d + " days ago";
    return new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }

  // ---------- URLs ----------
  const GH = () => "https://github.com/" + D.repo;
  const blobUrl = (path) => GH() + "/blob/" + D.branch + "/" + path;
  const codeDir = (glob) => glob.split(/[*?[]/)[0].replace(/\/+$/, "");
  const treeUrl = (glob) => GH() + "/tree/" + D.branch + "/" + codeDir(glob);
  const pageHash = (id, anchor) => "#" + id + (anchor ? "/" + anchor : "");

  function resolvePath(base, href) {
    const dir = base.includes("/") ? base.slice(0, base.lastIndexOf("/") + 1) : "";
    const out = [];
    (dir + href).split("/").forEach((seg) => {
      if (seg === "..") out.pop(); else if (seg !== "." && seg !== "") out.push(seg);
    });
    return out.join("/");
  }

  // ---------- layout fallback: seeded, run to completion once ----------
  function layout() {
    let seed = 48;
    const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    const R = 300;
    const P = {};
    D.nodes.forEach((n) => { if (n.depth === 0) P[n.id] = [0, 0]; });
    const hs = hubs.slice().sort((a, b) => a.id.localeCompare(b.id));
    hs.forEach((hub, i) => {
      const a = (i / hs.length) * Math.PI * 2 - Math.PI / 2;
      const hx = R * Math.cos(a), hy = R * Math.sin(a);
      P[hub.id] = [hx, hy];
      const ks = descendants(hub.id).slice(1).map((id) => byId[id]);
      const m = ks.length;
      ks.forEach((k, j) => {
        const ka = a + (j - (m - 1) / 2) * Math.min(1.9 / Math.max(m - 1, 1), 0.55);
        const r = j % 2 ? 175 : 120;
        P[k.id] = [hx + r * Math.cos(ka) + rnd() - 0.5, hy + r * Math.sin(ka) + rnd() - 0.5];
      });
    });
    let stray = 0;
    D.nodes.forEach((n) => { if (!P[n.id]) { const a = stray++ * 2.4; P[n.id] = [560 * Math.cos(a), 560 * Math.sin(a)]; } });
    const ids = Object.keys(P).sort();
    for (let it = 0; it < 300; it++) {
      for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
        const p = P[ids[i]], q = P[ids[j]];
        const dx = q[0] - p[0], dy = q[1] - p[1], d = Math.hypot(dx, dy) || 0.01;
        if (d >= 62) continue;
        const push = (62 - d) / 2 / d;
        if (byId[ids[i]].depth) { p[0] -= dx * push; p[1] -= dy * push; }
        if (byId[ids[j]].depth) { q[0] += dx * push; q[1] += dy * push; }
      }
    }
    D.nodes.forEach((n) => { n.x = P[n.id][0]; n.y = P[n.id][1]; });
  }

  // ---------- sidebar: tree ----------
  const treeLinks = {};
  const treeGroups = {};
  function renderTree() {
    workIndex();
    const tree = $("tree");
    const chevron = () => {
      const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      s.setAttribute("viewBox", "0 0 12 12"); s.setAttribute("width", "10"); s.setAttribute("height", "10");
      s.setAttribute("aria-hidden", "true");
      s.innerHTML = '<path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5"/>';
      return s;
    };
    function item(n, level) {
      const children = level > 0 ? kids[n.id] : [];
      const li = h("li", { class: n.depth === 1 ? "t-hub" : null });
      const w = workByPage[n.id];
      const link = h("button", { type: "button", class: "t-link", onclick: () => go(n.id) },
        dot(nodeColor(n)), h("span", { class: "t-label" }, n.title),
        w ? h("span", { class: "dot t-work", style: "background:" + personColor(workPerson(w[0])), title: personName(workPerson(w[0])) + " is working on this" }) : null);
      treeLinks[n.id] = link;
      const row = h("div", { class: "t-row" });
      if (children.length) {
        const ul = h("ul", { id: "tree-" + n.id, hidden: true });
        const tog = h("button", { type: "button", class: "t-tog", "aria-expanded": "false", "aria-controls": "tree-" + n.id, "aria-label": "Show pages in " + n.title },
          chevron());
        tog.addEventListener("click", () => setOpen(n.id, tog.getAttribute("aria-expanded") !== "true"));
        treeGroups[n.id] = { ul, tog };
        row.append(tog, link);
        children.forEach((c) => ul.append(item(c, 0)));
        li.append(row, ul);
      } else {
        row.append(h("span", { class: "t-spacer" }), link);
        li.append(row);
      }
      return li;
    }
    const oak = D.nodes.find((n) => n.depth === 0);
    if (oak) tree.append(item(oak, 0));
    hubs.forEach((hb) => tree.append(item(hb, 1)));
    D.nodes.filter((n) => n.depth === 1 && !hubs.includes(n)).forEach((hb) => tree.append(item(hb, 1)));
  }
  function setOpen(id, open) {
    const g = treeGroups[id];
    if (!g) return;
    g.ul.hidden = !open;
    g.tog.setAttribute("aria-expanded", String(open));
  }

  // ---------- sidebar: work + recent ----------
  function pageLabel(ids) {
    const titles = ids.filter((p) => byId[p]).map((p) => byId[p].title);
    return titles.length ? titles.slice(0, 2).join(", ") + (titles.length > 2 ? " +" + (titles.length - 2) : "") : "";
  }
  function renderWork() {
    const ul = $("work");
    const items = D.work.slice().sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    if (!items.length) {
      ul.append(h("li", { class: "none" }, D.sample ? "Nothing open." : "No open issues or pull requests linked to pages."));
      return;
    }
    items.forEach((w) => {
      const pid = workPerson(w);
      const first = w.pages.find((p) => byId[p]);
      ul.append(h("li", null, h("button", { type: "button", class: "f-item", onclick: () => first && go(first),
        title: first ? "Open " + byId[first].title : null },
        dot(personColor(pid)),
        h("span", { class: "f-title" }, w.title),
        h("span", { class: "f-sub" },
          h("span", { class: "who", style: "color:" + personColor(pid) }, personName(pid, w.author)),
          h("span", null, (w.kind === "pr" ? "PR" : "Issue") + " #" + w.number),
          h("span", null, pageLabel(w.pages)),
          w.review_requested ? h("span", { class: "tag" }, "review requested") : null,
          w.draft ? h("span", { class: "tag draft" }, "draft") : null))));
    });
  }
  function renderRecent() {
    const ul = $("recent");
    const items = D.recent.slice(0, 12);
    if (!items.length) { ul.append(h("li", { class: "none" }, "No recent changes recorded.")); return; }
    items.forEach((r) => {
      const first = r.pages.find((p) => byId[p]);
      ul.append(h("li", null, h("button", { type: "button", class: "f-item", onclick: () => first && go(first) },
        dot(personColor(r.person)),
        h("span", { class: "f-title" }, r.message),
        h("span", { class: "f-sub" },
          h("span", { class: "who", style: "color:" + personColor(r.person) }, personName(r.person, r.author)),
          h("span", null, pageLabel(r.pages)),
          h("span", null, rel(r.date))))));
    });
  }
  function renderDataNote() {
    const el = $("data-note");
    if (D.sample) {
      el.append(h("span", { class: "pill sample" }, "Sample data"), " People, work, questions and changes are made up until the data builder runs.");
    } else {
      el.append("Built from ", h("code", null, D.branch), D.generated_at ? " " + rel(D.generated_at) : "",
        D.published ? "" : ". Not on GitHub yet.");
    }
  }

  // ---------- map bar: people + legend ----------
  function renderPeople() {
    const box = $("people");
    D.people.forEach((p) => {
      const b = h("button", { type: "button", class: "person", "aria-pressed": "false", style: "--c:" + p.color,
        title: p.focus ? p.name + ": " + p.focus : p.name }, h("span", { class: "dot", "aria-hidden": "true" }), p.name);
      b.addEventListener("click", () => {
        filterPerson = filterPerson === p.id ? null : p.id;
        box.querySelectorAll(".person").forEach((x) => x.setAttribute("aria-pressed", String(x === b && !!filterPerson)));
        renderLegend();
        if (filterPerson) Graph.fit(); else Graph.draw();
      });
      box.append(b);
    });
    // ?person=<id> preselects a teammate (handy for sharing a view)
    const pre = new URLSearchParams(location.search).get("person");
    if (pre && people[pre]) box.querySelector('[title^="' + people[pre].name + '"]').click();
  }
  function renderLegend() {
    const el = $("legend");
    el.textContent = "";
    if (filterPerson) {
      const p = people[filterPerson];
      const n = personPages(filterPerson).size;
      el.append(h("span", null, dot(p.color), p.name + (p.focus ? " - " + p.focus : "") + " (" + n + (n === 1 ? " page" : " pages") + ")"));
      return;
    }
    hubs.forEach((hb) => el.append(h("span", null, dot(hubColor(hb.id)), hb.title)));
  }

  // ---------- search ----------
  let searchIndex = [];
  function plain(md) {
    return md.replace(/```[\s\S]*?```/g, " ").replace(/<[^>]+>/g, " ").replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/[#*_`>|]/g, " ").replace(/\s+/g, " ").trim();
  }
  function setupSearch() {
    searchIndex = D.nodes.map((n) => ({ kind: "page", n, title: n.title, text: plain(n.markdown) }))
      .concat(D.work.map((w) => ({ kind: w.kind === "pr" ? "Pull request" : "Issue", n: byId[w.pages.find((p) => byId[p])], title: w.title, text: personName(workPerson(w), w.author) })))
      .concat(D.questions.map((q) => ({ kind: "Question", n: byId[q.page], title: q.title, text: q.answer_excerpt || "" })))
      .filter((e) => e.n);
    const input = $("search"), list = $("results");
    let hits = [], sel = 0;
    function show() {
      const q = input.value.trim().toLowerCase();
      list.textContent = "";
      if (!q) { close(); return; }
      const terms = q.split(/\s+/);
      hits = searchIndex.map((e) => {
        const t = e.title.toLowerCase(), b = e.text.toLowerCase();
        let s = 0;
        for (const term of terms) {
          if (t.includes(term)) s += t.startsWith(term) ? 12 : 8;
          else if (b.includes(term)) s += 2;
          else return null;
        }
        return { e, s: s + (e.kind === "page" ? 1 : 0) };
      }).filter(Boolean).sort((a, b) => b.s - a.s || a.e.title.localeCompare(b.e.title)).slice(0, 12);
      sel = 0;
      if (!hits.length) list.append(h("li", { class: "empty", role: "option", "aria-disabled": "true" }, "No matches"));
      hits.forEach((hit, i) => {
        const e = hit.e;
        const li = h("li", { role: "option", id: "res-" + i, "aria-selected": String(i === 0) },
          h("span", { class: "r-title" }, dot(nodeColor(e.n)), e.title),
          h("span", { class: "r-snip" }, e.kind === "page" ? snippet(e.text, terms[0]) : [e.kind + " on " + e.n.title + (e.text ? " - " : ""), ...snippet(e.text, terms[0])]));
        li.addEventListener("mousedown", (ev) => { ev.preventDefault(); pick(i); });
        list.append(li);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      input.setAttribute("aria-activedescendant", hits.length ? "res-0" : "");
    }
    function snippet(text, term) {
      const i = text.toLowerCase().indexOf(term);
      if (i < 0) return [text.slice(0, 90) + (text.length > 90 ? "..." : "")];
      const a = Math.max(0, i - 40), b = Math.min(text.length, i + term.length + 60);
      return [(a ? "..." : "") + text.slice(a, i), h("mark", null, text.slice(i, i + term.length)), text.slice(i + term.length, b) + (b < text.length ? "..." : "")];
    }
    function move(d) {
      if (!hits.length) return;
      sel = (sel + d + hits.length) % hits.length;
      list.querySelectorAll("li").forEach((li, i) => li.setAttribute("aria-selected", String(i === sel)));
      input.setAttribute("aria-activedescendant", "res-" + sel);
      const li = $("res-" + sel); if (li) li.scrollIntoView({ block: "nearest" });
    }
    function pick(i) { const hit = hits[i]; if (!hit) return; close(); input.value = ""; go(hit.e.n.id); }
    function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); }
    input.addEventListener("input", show);
    input.addEventListener("focus", () => { if (input.value.trim()) show(); });
    input.addEventListener("blur", () => setTimeout(close, 100));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") { e.preventDefault(); pick(sel); }
      else if (e.key === "Escape") { input.value = ""; close(); input.blur(); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      if (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      e.preventDefault();
      openDrawer();
      input.focus();
    });
  }

  // ---------- routing ----------
  function go(id, anchor) {
    const target = pageHash(id, anchor);
    if (location.hash === target) route(); else location.hash = target;
  }
  function route() {
    const raw = decodeURIComponent(location.hash.slice(1));
    const [id, anchor] = raw.split("/");
    const oak = D.nodes.find((n) => n.depth === 0) || D.nodes[0];
    const n = byId[id] || oak;
    closeDrawer();
    if (!n) return;
    if (current !== n) openPage(n);
    if (anchor) {
      const el = document.getElementById(anchor);
      if (el && $("content").contains(el)) el.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "start" });
    }
  }

  // ---------- reading pane ----------
  function openPage(n) {
    const first = !current;
    current = n;
    document.title = n.depth === 0 ? "Oak Workspace" : n.title + " - Oak Workspace";
    Object.entries(treeLinks).forEach(([id, el]) => { if (id === n.id) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current"); });
    if (n.hub && n.depth > 1) setOpen(n.hub, true);
    if (n.depth === 1) setOpen(n.id, true);
    const tl = treeLinks[n.id]; if (tl) tl.scrollIntoView({ block: "nearest" });

    renderCrumbs(n); renderBanner(n); renderContent(n); renderMeta(n); renderBacklinks(n); renderSaved(n); resetAsk();

    const page = $("page");
    page.classList.remove("enter"); void page.offsetWidth; page.classList.add("enter");
    $("reader-scroll").scrollTop = 0;
    if (!first && window.matchMedia("(max-width: 900px)").matches) window.scrollTo({ top: 0, behavior: "auto" });
    Graph.focus(n, first);
  }

  function renderCrumbs(n) {
    const chain = [];
    for (let x = n; x; x = x.parent ? byId[x.parent] : null) { chain.unshift(x); if (chain.length > 8) break; }
    const nav = $("crumbs");
    nav.textContent = "";
    chain.forEach((x, i) => {
      if (i) nav.append(h("span", { class: "sep", "aria-hidden": "true" }, "/"));
      nav.append(i === chain.length - 1 ? h("span", { "aria-current": "page" }, x.title)
        : h("button", { type: "button", onclick: () => go(x.id) }, x.title));
    });
  }

  function renderBanner(n) {
    const box = $("banner");
    box.textContent = "";
    (workByPage[n.id] || []).forEach((w) => {
      const pid = workPerson(w);
      const others = w.assignees.filter((a) => a !== pid).map((a) => personName(a));
      box.append(h("div", { class: "banner", style: "--c:" + personColor(pid) },
        dot(personColor(pid)),
        h("div", null,
          h("div", null, h("strong", null, personName(pid, w.author)), others.length ? " and " + others.join(", ") : "",
            w.kind === "pr" ? (w.review_requested ? " wants a review on this page's code" : " has a pull request open here")
              : " is working on this"),
          h("div", { class: "b-line" },
            h("a", { href: w.url, target: "_blank", rel: "noopener" }, (w.kind === "pr" ? "PR" : "Issue") + " #" + w.number + ": " + w.title),
            w.review_requested ? h("span", { class: "tag" }, "review requested") : null,
            w.draft ? h("span", { class: "tag draft" }, "draft") : null,
            h("span", null, rel(w.updated_at))))));
    });
  }

  function slugger() {
    const seen = {};
    return (text) => {
      let s = text.toLowerCase().trim().replace(/[^\w\- ]+/g, "").replace(/ /g, "-");
      if (seen[s] != null) { seen[s] += 1; s += "-" + seen[s]; } else seen[s] = 0;
      return s;
    };
  }

  function renderContent(n) {
    const el = $("content");
    const md = n.markdown.replace(/^---\n[\s\S]*?\n---\n/, "");
    el.innerHTML = window.marked ? window.marked.parse(md) : "";
    if (!window.marked) el.append(h("pre", null, md));
    const slug = slugger();
    el.querySelectorAll("h1,h2,h3,h4,h5,h6").forEach((hd) => { hd.id = slug(hd.textContent); });
    el.querySelectorAll("a[href]").forEach((a) => {
      const href = a.getAttribute("href");
      if (href.startsWith("#")) { a.setAttribute("href", pageHash(n.id, href.slice(1))); return; }
      if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("//")) {
        a.target = "_blank"; a.rel = "noopener"; return;
      }
      const [path, anchor] = href.split("#");
      const full = resolvePath(n.path || "", path);
      const page = byPath[full];
      if (page) { a.setAttribute("href", pageHash(page.id, anchor)); a.classList.add("internal"); return; }
      a.href = GH() + "/blob/" + (D.published ? D.branch : "master") + "/" + full + (anchor ? "#" + anchor : "");
      a.target = "_blank"; a.rel = "noopener";
    });
    el.querySelectorAll("img[src]").forEach((img) => {
      const src = img.getAttribute("src");
      if (!/^[a-z][a-z0-9+.-]*:/i.test(src) && !src.startsWith("//")) {
        img.src = GH() + "/raw/" + (D.published ? D.branch : "master") + "/" + resolvePath(n.path || "", src);
      }
      img.loading = "lazy";
    });
  }

  function ghLink(label, url, sub) {
    if (D.published) return h("a", { class: "btn", href: url, target: "_blank", rel: "noopener" }, label, sub ? h("code", null, sub) : null);
    return h("span", { class: "btn", role: "link", "aria-disabled": "true", title: "Not on GitHub yet" }, label, sub ? h("code", null, sub) : null);
  }

  function renderMeta(n) {
    const box = $("meta");
    box.textContent = "";
    const lc = n.last_change;
    if (lc && (lc.date || lc.message)) {
      box.append(h("div", { class: "changed" }, dot(personColor(lc.person)),
        h("span", null, "Last changed by ", h("strong", { style: "color:" + personColor(lc.person) }, personName(lc.person, lc.author)),
          " " + rel(lc.date) + (lc.message ? ": " + lc.message : ""), " ", lc.sha ? h("code", null, lc.sha.slice(0, 7)) : null)));
    }
    const links = h("div", { class: "links" });
    if (n.path) links.append(ghLink("Open in GitHub", blobUrl(n.path)));
    n.code.forEach((c) => links.append(ghLink("Open code folder", treeUrl(c), codeDir(c))));
    if (links.childNodes.length) box.append(links);
    if (!D.published) box.append(h("p", { class: "note" }, "Not on GitHub yet: the branch ", h("code", null, D.branch), " has not been pushed, so these links are turned off."));
  }

  function renderBacklinks(n) {
    const box = $("backlinks");
    box.textContent = "";
    const list = n.backlinks.filter((id) => byId[id] && id !== n.id);
    if (!list.length) return;
    box.append(h("h2", { id: "h-back" }, "Linked from"));
    const ul = h("ul");
    list.forEach((id) => {
      const b = byId[id];
      ul.append(h("li", null, h("button", { type: "button", class: "bl", onclick: () => go(id) },
        h("span", { class: "bl-t" }, dot(nodeColor(b)), b.title),
        b.summary ? h("span", { class: "bl-s" }, b.summary) : null)));
    });
    box.append(ul);
  }

  // ---------- ask box ----------
  function resetAsk() {
    $("answer").hidden = true;
    $("answer").textContent = "";
    document.querySelectorAll(".ask-quick .chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
    $("copy-fallback").hidden = true;
    toast("");
  }
  function toast(msg, err) { const t = $("toast"); t.textContent = msg; t.classList.toggle("err", !!err); }

  function answer(kind) {
    const n = current, scope = scopeOf(n);
    const where = n.depth < 2 && scope.size > 1 ? " (this page and the pages under it)" : "";
    const box = $("answer");
    box.textContent = "";
    const noGithub = !D.work.length && !D.questions.length && !D.sample;
    const workLine = (w) => {
      const pid = workPerson(w);
      return h("li", null, h("span", { class: "who", style: "color:" + personColor(pid) }, personName(pid, w.author)), " - ",
        h("a", { href: w.url, target: "_blank", rel: "noopener" }, (w.kind === "pr" ? "PR" : "Issue") + " #" + w.number + ": " + w.title),
        w.review_requested ? [" ", h("span", { class: "tag" }, "review requested")] : null,
        scope.size > 1 ? " (" + pageLabel(w.pages.filter((p) => scope.has(p))) + ")" : "");
    };
    if (kind === "who") {
      const ws = workOn(scope);
      if (ws.length) box.append(h("p", null, "Open work" + where + ":"), h("ul", null, ws.map(workLine)));
      else {
        box.append(h("p", null, noGithub ? "No open work found. This copy of the site was built without GitHub access, so issues and pull requests are not shown."
          : "Nobody has an open issue or pull request on this page right now."));
        const lc = n.last_change;
        if (lc && lc.date) box.append(h("p", null, "Last change: ", h("span", { class: "who", style: "color:" + personColor(lc.person) }, personName(lc.person, lc.author)), ", " + rel(lc.date) + "."));
      }
    } else if (kind === "recent") {
      const rs = D.recent.filter((r) => r.pages.some((p) => scope.has(p))).slice(0, 6);
      if (rs.length) {
        box.append(h("p", null, "Latest changes" + where + ":"), h("ul", null, rs.map((r) => h("li", null,
          h("span", { class: "who", style: "color:" + personColor(r.person) }, personName(r.person, r.author)), ", " + rel(r.date) + ": " + r.message,
          scope.size > 1 ? " (" + pageLabel(r.pages.filter((p) => scope.has(p))) + ")" : ""))));
      } else if (n.last_change && n.last_change.date) {
        const lc = n.last_change;
        box.append(h("p", null, "No changes in the last 40 commits. Before that: ", h("span", { class: "who" }, personName(lc.person, lc.author)), ", " + rel(lc.date) + (lc.message ? ": " + lc.message : "") + "."));
      } else box.append(h("p", null, "No recent changes recorded for this page."));
    } else {
      const ws = workOn(scope);
      const qs = D.questions.filter((q) => scope.has(q.page) && !q.answered);
      if (!ws.length && !qs.length) box.append(h("p", null, noGithub ? "Nothing to show: this copy of the site was built without GitHub access." : "Nothing open here: no issues, pull requests, or unanswered questions."));
      if (ws.length) box.append(h("p", null, "Issues and pull requests" + where + ":"), h("ul", null, ws.map(workLine)));
      if (qs.length) box.append(h("p", null, "Unanswered questions:"), h("ul", null, qs.map((q) => h("li", null,
        h("a", { href: q.url, target: "_blank", rel: "noopener" }, "#" + q.number + ": " + q.title), " - asked by " + q.asker + ", " + rel(q.updated_at)))));
    }
    box.hidden = false;
  }

  function promptFor(q) {
    const n = current;
    const code = n.code.map(codeDir).filter(Boolean);
    return "In github.com/" + D.repo + " (branch " + D.branch + "), read " + (n.path || "README.md") +
      (code.length ? " and the code in " + code.join(", ") : "") +
      ", then answer in plain English: " + (q || "<your question>");
  }

  function setupAsk() {
    document.querySelectorAll(".ask-quick .chip").forEach((c) => c.addEventListener("click", () => {
      document.querySelectorAll(".ask-quick .chip").forEach((x) => x.setAttribute("aria-pressed", String(x === c)));
      answer(c.dataset.q);
    }));
    $("ask-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("ask-input").value.trim();
      if (!q) { toast("Type your question first.", true); $("ask-input").focus(); return; }
      const n = current;
      const link = D.published && n.path ? blobUrl(n.path) : (n.path || "README.md") + " (branch " + D.branch + ")";
      const body = "Question about the **" + n.title + "** page.\n\nPage: " + link + "\n\n" + q + "\n\n_Asked from the Oak workspace._";
      const url = GH() + "/issues/new?title=" + encodeURIComponent(q) + "&labels=" + encodeURIComponent("question,wiki:" + n.id) + "&body=" + encodeURIComponent(body);
      window.open(url, "_blank", "noopener");
      toast("Opened GitHub in a new tab. Press Submit there to save your question.");
    });
    $("ask-agent").addEventListener("click", () => {
      const text = promptFor($("ask-input").value.trim());
      const fallback = () => {
        $("copy-fallback").hidden = false;
        const ta = $("copy-text"); ta.value = text; ta.focus(); ta.select();
        toast("Your browser blocked copying. Select the text below and copy it.", true);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
          $("copy-fallback").hidden = true;
          toast("Prompt copied. Paste it into Claude Code, Codex, or your own agent.");
        }, fallback);
      } else fallback();
    });
  }

  function renderSaved(n) {
    const box = $("saved");
    box.textContent = "";
    const qs = D.questions.filter((q) => q.page === n.id);
    if (!qs.length) return;
    box.append(h("div", { class: "saved" }, h("h3", null, "Questions asked here"), h("ul", null, qs.map((q) => h("li", null,
      h("span", { class: "state " + (q.answered ? "yes" : "no") }, q.answered ? "Answered" : "Unanswered"),
      h("span", null, h("a", { href: q.url, target: "_blank", rel: "noopener" }, q.title),
        h("span", { class: "excerpt" }, "Asked by " + q.asker + ", " + rel(q.updated_at) + (q.answer_excerpt ? " - " + q.answer_excerpt : "")))))))
    );
  }

  // ---------- narrow-screen drawer ----------
  function openDrawer() {
    if (!window.matchMedia("(max-width: 900px)").matches) return;
    $("side").classList.add("open"); $("scrim").hidden = false; $("side-open").setAttribute("aria-expanded", "true");
  }
  function closeDrawer() {
    if (!$("side").classList.contains("open")) return;
    $("side").classList.remove("open"); $("scrim").hidden = true; $("side-open").setAttribute("aria-expanded", "false");
  }
  function setupDrawer() {
    $("side-open").addEventListener("click", () => { openDrawer(); $("search").focus(); });
    $("side-close").addEventListener("click", () => { closeDrawer(); $("side-open").focus(); });
    $("scrim").addEventListener("click", closeDrawer);
    $("home").addEventListener("click", () => go("oak"));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  }

  // ---------- the map ----------
  const Graph = (function () {
    const cv = $("graph"), ctx = cv.getContext("2d"), tip = $("tip");
    let W = 0, H = 0, dpr = 1, fitK = 1, ready = false;
    const cam = { x: 0, y: 0, k: 1 };
    let hover = null, anim = null, raf = 0;
    const halos = [];

    const toScreen = (x, y) => [(x - cam.x) * cam.k + W / 2, (y - cam.y) * cam.k + H / 2];
    const toWorld = (sx, sy) => [(sx - W / 2) / cam.k + cam.x, (sy - H / 2) / cam.k + cam.y];

    function bounds() {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      D.nodes.forEach((n) => { x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y); });
      return { x0, y0, x1, y1 };
    }
    function computeFit() {
      const b = bounds();
      const padX = 70, padY = 46;
      fitK = Math.min(W / (b.x1 - b.x0 + padX * 2), (H - 30) / (b.y1 - b.y0 + padY * 2));
      fitK = Math.max(0.15, Math.min(fitK, 2));
      return { x: (b.x0 + b.x1) / 2, y: (b.y0 + b.y1) / 2 - 12 / fitK, k: fitK };
    }
    function resize() {
      const r = cv.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const firstSize = !W;
      const oldFit = fitK;
      W = r.width; H = r.height; dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      const f = computeFit();
      if (firstSize || !ready) { ready = true; if (current && !filterPerson) focus(current, true); else Object.assign(cam, f); }
      else cam.k *= fitK / oldFit;
      draw();
    }

    function init() {
      hubs.forEach((hb) => {
        const members = descendants(hb.id).map((id) => byId[id]);
        const cx = members.reduce((s, m) => s + m.x, 0) / members.length;
        const cy = members.reduce((s, m) => s + m.y, 0) / members.length;
        const r = Math.max(...members.map((m) => Math.hypot(m.x - cx, m.y - cy))) + 46;
        halos.push({ hub: hb.id, x: cx, y: cy, r });
      });
      new ResizeObserver(resize).observe(cv);
      if (document.fonts) document.fonts.ready.then(draw);
      bindPointer();
      $("zoom-in").addEventListener("click", () => zoomBy(1.35));
      $("zoom-out").addEventListener("click", () => zoomBy(1 / 1.35));
      $("zoom-fit").addEventListener("click", () => animateTo(computeFit()));
    }

    function targetFor(n) {
      if (n.depth === 0) return computeFit();
      const k = Math.max(cam.k, fitK * (n.depth === 1 ? 1.45 : 1.8));
      return { x: n.x, y: n.y, k: Math.min(k, fitK * 4) };
    }
    function focus(n, instant) {
      if (!W) return;
      const t = targetFor(n);
      if (instant) { Object.assign(cam, t); draw(); } else animateTo(t);
    }
    function animateTo(t) {
      if (reduceMotion.matches) { Object.assign(cam, t); draw(); return; }
      const from = { ...cam }, t0 = performance.now(), dur = 620;
      anim = (now) => {
        const p = Math.min(1, (now - t0) / dur);
        const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
        // interpolate zoom in log space so it feels even
        cam.k = Math.exp(Math.log(from.k) + (Math.log(t.k) - Math.log(from.k)) * e);
        cam.x = from.x + (t.x - from.x) * e;
        cam.y = from.y + (t.y - from.y) * e;
        if (p >= 1) anim = null;
      };
      tick();
    }
    function tick() {
      if (raf) return;
      raf = requestAnimationFrame((now) => { raf = 0; if (anim) { anim(now); draw(); if (anim) tick(); } });
    }
    function zoomAt(sx, sy, f) {
      const [wx, wy] = toWorld(sx, sy);
      cam.k = Math.max(fitK * 0.5, Math.min(fitK * 7, cam.k * f));
      cam.x = wx - (sx - W / 2) / cam.k; cam.y = wy - (sy - H / 2) / cam.k;
      draw();
    }
    function zoomBy(f) {
      const t = { x: cam.x, y: cam.y, k: Math.max(fitK * 0.5, Math.min(fitK * 7, cam.k * f)) };
      animateTo(t);
    }

    // ---- drawing ----
    function radius(n) {
      const s = Math.max(0.85, Math.min(1.9, Math.sqrt(cam.k / fitK)));
      return (n.depth === 0 ? 13 : n.depth === 1 ? 8.5 : 4.6) * s;
    }
    function draw() {
      if (!W || !D) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = BG; ctx.fillRect(0, 0, W, H);

      const cur = current ? current.id : null;
      const lit = new Set(cur ? [cur, ...nbrs[cur]] : []);
      const pf = filterPerson ? personPages(filterPerson) : null;
      const pcol = filterPerson ? personColor(filterPerson) : null;
      const isLit = (id) => (pf ? pf.has(id) || id === cur : lit.has(id));
      const dimAll = !!pf || (cur && cur !== "oak");

      // hub halos
      halos.forEach((hl) => {
        const [x, y] = toScreen(hl.x, hl.y), r = hl.r * cam.k;
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        const c = hubColor(hl.hub);
        g.addColorStop(0, hexA(c, pf ? 0.04 : 0.11)); g.addColorStop(0.7, hexA(c, pf ? 0.02 : 0.05)); g.addColorStop(1, hexA(c, 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      });

      // edges
      ctx.lineCap = "round";
      D.edges.forEach((e) => {
        const a = byId[e.source], b = byId[e.target];
        if (!a || !b) return;
        const hot = cur && !pf && (e.source === cur || e.target === cur);
        const pfHot = pf && pf.has(e.source) && pf.has(e.target);
        const [x1, y1] = toScreen(a.x, a.y), [x2, y2] = toScreen(b.x, b.y);
        const col = e.kind === "parent" ? nodeColor(b.depth ? b : a) : "#a8a196";
        let alpha = e.kind === "parent" ? 0.42 : 0.2;
        if (dimAll) alpha *= 0.35;
        if (hot) alpha = 0.95;
        if (pfHot) alpha = 0.8;
        ctx.strokeStyle = hexA(pfHot ? pcol : col, alpha);
        ctx.lineWidth = hot ? 1.8 : e.kind === "parent" ? 1.1 : 0.9;
        ctx.setLineDash(e.kind === "link" ? [3, 4] : []);
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      });
      ctx.setLineDash([]);

      // nodes
      const order = D.nodes.slice().sort((a, b) => b.depth - a.depth);
      order.forEach((n) => {
        const [x, y] = toScreen(n.x, n.y), r = radius(n);
        const on = !dimAll || isLit(n.id) || hover === n;
        const col = nodeColor(n);
        if (n.id === cur) {
          const g = ctx.createRadialGradient(x, y, r, x, y, r * 3.2);
          g.addColorStop(0, hexA(col, 0.45)); g.addColorStop(1, hexA(col, 0));
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 3.2, 0, Math.PI * 2); ctx.fill();
        }
        if (n.depth === 0) {
          const g = ctx.createRadialGradient(x, y, r, x, y, r * 3);
          g.addColorStop(0, "rgba(240,230,207,.22)"); g.addColorStop(1, "rgba(240,230,207,0)");
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 3, 0, Math.PI * 2); ctx.fill();
        }
        ctx.globalAlpha = on ? 1 : 0.22;
        ctx.fillStyle = col;
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
        if (pf && pf.has(n.id)) {
          ctx.strokeStyle = pcol; ctx.lineWidth = 2.5;
          ctx.beginPath(); ctx.arc(x, y, r + 4, 0, Math.PI * 2); ctx.stroke();
        }
        if (n.id === cur) {
          ctx.strokeStyle = "#fffaf0"; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(x, y, r + 3, 0, Math.PI * 2); ctx.stroke();
        }
        const w = workByPage[n.id];
        if (w && !pf) {
          ctx.fillStyle = personColor(workPerson(w[0]));
          ctx.strokeStyle = BG; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(x + r * 0.85, y - r * 0.85, 3.4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      });

      // labels
      const showPages = cam.k >= fitK * 1.55;
      ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.lineJoin = "round";
      order.slice().reverse().forEach((n) => {
        const hot = n.id === cur || hover === n || (pf ? pf.has(n.id) : lit.has(n.id) && cur !== "oak");
        if (n.depth === 2 && !showPages && !hot) return;
        const [x, y] = toScreen(n.x, n.y), r = radius(n);
        const on = !dimAll || isLit(n.id) || hover === n;
        const size = n.depth === 0 ? 15 : n.depth === 1 ? 13 : 11.5;
        const weight = n.depth === 2 && n.id !== cur ? 400 : 600;
        ctx.font = weight + " " + size + 'px "IBM Plex Sans", system-ui, sans-serif';
        ctx.lineWidth = 4; ctx.strokeStyle = BG;
        ctx.strokeText(n.title, x, y + r + 4);
        ctx.fillStyle = on ? (n.depth === 2 ? "#d6d1c7" : "#f2ede4") : "rgba(214,209,199,.3)";
        ctx.fillText(n.title, x, y + r + 4);
      });
    }

    function hexA(hex, a) {
      const m = /^#?([0-9a-f]{6})$/i.exec(hex);
      if (!m) return hex;
      const v = parseInt(m[1], 16);
      return "rgba(" + (v >> 16) + "," + ((v >> 8) & 255) + "," + (v & 255) + "," + a + ")";
    }

    // ---- pointer: pan, pinch, wheel, hover, click (no node dragging) ----
    function hit(sx, sy) {
      let best = null, bd = Infinity;
      D.nodes.forEach((n) => {
        const [x, y] = toScreen(n.x, n.y), d = Math.hypot(x - sx, y - sy);
        if (d < radius(n) + 7 && d < bd) { best = n; bd = d; }
      });
      return best;
    }
    function bindPointer() {
      const pts = new Map();
      let moved = 0, pinchD = 0;
      const local = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      cv.addEventListener("pointerdown", (e) => {
        cv.setPointerCapture(e.pointerId);
        pts.set(e.pointerId, local(e));
        moved = 0; anim = null;
        if (pts.size === 2) { const [a, b] = [...pts.values()]; pinchD = Math.hypot(a[0] - b[0], a[1] - b[1]); }
      });
      cv.addEventListener("pointermove", (e) => {
        const p = local(e);
        if (pts.has(e.pointerId)) {
          const prev = pts.get(e.pointerId);
          pts.set(e.pointerId, p);
          if (pts.size === 2) {
            const [a, b] = [...pts.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
            if (pinchD) zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d / pinchD);
            pinchD = d; moved += 10; return;
          }
          moved += Math.abs(p[0] - prev[0]) + Math.abs(p[1] - prev[1]);
          if (moved > 4) {
            cv.classList.add("grabbing"); hideTip();
            cam.x -= (p[0] - prev[0]) / cam.k; cam.y -= (p[1] - prev[1]) / cam.k; draw();
          }
          return;
        }
        const n = hit(p[0], p[1]);
        if (n !== hover) { hover = n; cv.classList.toggle("pointing", !!n); draw(); }
        if (n) showTip(n, p); else hideTip();
      });
      const end = (e) => {
        const wasClick = pts.size === 1 && moved <= 4;
        const p = local(e);
        pts.delete(e.pointerId);
        if (pts.size < 2) pinchD = 0;
        cv.classList.remove("grabbing");
        if (wasClick && e.type === "pointerup") { const n = hit(p[0], p[1]); if (n) go(n.id); }
      };
      cv.addEventListener("pointerup", end);
      cv.addEventListener("pointercancel", end);
      cv.addEventListener("pointerleave", () => { if (!pts.size && hover) { hover = null; cv.classList.remove("pointing"); hideTip(); draw(); } });
      cv.addEventListener("wheel", (e) => {
        e.preventDefault(); anim = null;
        const [sx, sy] = local(e);
        zoomAt(sx, sy, Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0015)));
      }, { passive: false });
    }
    function showTip(n, p) {
      tip.textContent = "";
      tip.append(h("strong", null, n.title));
      const w = workByPage[n.id];
      if (n.summary) tip.append(h("span", null, n.summary));
      if (w) tip.append(h("div", { style: "margin-top:4px;color:" + personColor(workPerson(w[0])) }, personName(workPerson(w[0]), w[0].author) + " is working here"));
      tip.hidden = false;
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      tip.style.left = Math.min(W - tw - 8, Math.max(8, p[0] + 14)) + "px";
      tip.style.top = Math.min(H - th - 8, Math.max(8, p[1] + 14)) + "px";
    }
    function hideTip() { tip.hidden = true; }

    // fit the whole map, e.g. so all of a teammate's pages are in view
    function fit() { if (W) animateTo(computeFit()); }

    return { init, focus, draw, fit };
  })();
})();
