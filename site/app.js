/* Oak workspace v3: sidebar (page tree, people, recent), quick switcher,
   reading pane (page, connections, ask box, or a teammate's view) and a fixed
   2D map. Pages are grey; a page takes a teammate's color while they work on it.
   Data: graph.json (scripts/wiki/build_graph.py), else sample-graph.json. */
(function () {
  "use strict";

  const GREYS = ["#e6e6e6", "#9a9a9a", "#666666"];   // Oak, hubs, pages
  const BG = "#161616";
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
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
    return el;
  }
  const dot = (color) => h("span", { class: "dot", style: "background:" + color, "aria-hidden": "true" });

  // ---------- state ----------
  let D = null;               // graph data
  const byId = {}, byPath = {}, kids = {}, nbrs = {}, people = {};
  let hubs = [], current = null, filterPerson = null, viewedPerson = null;

  // ---------- load ----------
  function getJSON(url) {
    return fetch(url, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(url + " " + r.status);
      return r.json();
    });
  }
  (window.OAK_GRAPH ? Promise.resolve(window.OAK_GRAPH) : getJSON("graph.json"))
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
    renderTree(); renderWork(); renderRecent(); renderPeopleList(); renderLegend(); renderDataNote();
    setupSearch(); setupAsk(); setupDrawer(); setupMapToggle();
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
      work: arr(d.work), questions: arr(d.questions), recent: arr(d.recent), branches: arr(d.branches),
    };
    out.nodes.forEach((n) => {
      n.code = arr(n.code); n.markdown = n.markdown || ""; n.depth = n.depth ?? (n.id === "oak" ? 0 : 2);
      n.hub = n.hub || (n.depth === 1 ? n.id : null);
    });
    out.work.forEach((w) => { w.pages = arr(w.pages); w.assignees = arr(w.assignees); });
    out.recent.forEach((r) => { r.pages = arr(r.pages); });
    out.branches.forEach((b) => { b.pages = arr(b.pages); b.last_commit = b.last_commit || {}; });
    out.people.forEach((p) => {
      p.past = arr(p.past); p.contributed = arr(p.contributed);
      p.worked_on = arr(p.worked_on).length ? arr(p.worked_on) : [...new Set(p.past.concat(p.contributed))];
    });
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
  // Color means "who": a page is grey unless someone has open work or an
  // active branch on it, then it takes that teammate's color.
  const greyOf = (n) => GREYS[Math.min(n.depth, 2)];
  const nodeColor = (n) => { const pid = pagePerson(n.id); return pid ? personColor(pid) : greyOf(n); };
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
  const workOf = (pid) => D.work.filter((w) => w.person === pid || w.assignees.includes(pid));
  const branchesOf = (pid) => D.branches.filter((b) => b.person === pid);
  function personPages(pid) {
    const s = new Set((people[pid] && people[pid].worked_on) || []);
    workOf(pid).forEach((w) => w.pages.forEach((p) => s.add(p)));
    branchesOf(pid).forEach((b) => b.pages.forEach((p) => s.add(p)));
    s.delete("oak");
    return s;
  }
  const workByPage = {}, branchesByPage = {};
  function workIndex() {
    D.work.forEach((w) => w.pages.forEach((p) => { (workByPage[p] = workByPage[p] || []).push(w); }));
    D.branches.forEach((b) => b.pages.forEach((p) => { (branchesByPage[p] = branchesByPage[p] || []).push(b); }));
  }
  // everyone working on a page right now: open work first, then active branches
  function pagePeople(id) {
    const out = [];
    (workByPage[id] || []).forEach((w) => { const pid = workPerson(w); if (pid && !out.includes(pid)) out.push(pid); });
    (branchesByPage[id] || []).forEach((b) => { if (b.person && !out.includes(b.person)) out.push(b.person); });
    return out;
  }
  const pagePerson = (id) => (id === "oak" ? null : pagePeople(id)[0] || null);

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
  const branchUrl = (name) => GH() + "/tree/" + name.split("/").map(encodeURIComponent).join("/");
  const pageHash = (id, anchor) => "#" + id + (anchor ? "/" + anchor : "");
  const personHash = (pid) => "#people/" + pid;

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
      const pid = pagePerson(n.id);
      const link = h("button", { type: "button", class: "t-link", onclick: () => go(n.id) },
        h("span", { class: "t-label" }, n.title),
        pid ? h("span", { class: "dot t-work", style: "background:" + personColor(pid), title: personName(pid) + " is working on this" }) : null);
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
    const items = D.recent.slice(0, 6);
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
      el.append(h("span", { class: "pill sample" }, "Sample data."), " People, work and changes are made up until the data builder runs.");
    } else {
      el.append("Built from ", h("code", null, D.branch), D.generated_at ? " " + rel(D.generated_at) : "",
        D.published ? "" : ". Not on GitHub yet.");
    }
  }

  // ---------- sidebar: people ----------
  const personLinks = {};
  function renderPeopleList() {
    const ul = $("people-list");
    D.people.forEach((p) => {
      const open = workOf(p.id).length;
      const b = h("button", { type: "button", class: "p-link", style: "--c:" + p.color, onclick: () => goPerson(p.id) },
        dot(p.color),
        h("span", { class: "p-name" }, p.name),
        open ? h("span", { class: "p-count", title: open + " open " + (open === 1 ? "item" : "items") }, open + " open") : null,
        p.focus ? h("span", { class: "p-focus" }, p.focus) : null);
      personLinks[p.id] = b;
      ul.append(h("li", null, b));
    });
    if (!D.people.length) ul.append(h("li", { class: "none" }, "No team file yet (docs/team.yml)."));
    const tog = $("work-tog"), work = $("work");
    tog.addEventListener("click", () => {
      const show = tog.getAttribute("aria-expanded") !== "true";
      tog.setAttribute("aria-expanded", String(show));
      work.hidden = !show;
    });
    // old links with ?person=<id> open that teammate's view
    const pre = new URLSearchParams(location.search).get("person");
    if (pre && people[pre] && !location.hash) history.replaceState(null, "", personHash(pre));
  }
  // map legend: one button per teammate; pressing one lights up their pages
  let lastPage = "oak";
  function renderLegend() {
    const el = $("legend");
    el.textContent = "";
    D.people.forEach((p) => {
      const on = filterPerson === p.id;
      el.append(h("button", { type: "button", class: "lg", "aria-pressed": String(on),
        title: on ? "Back to the page you were reading" : "Show " + p.name + "'s pages",
        onclick: () => (on ? go(lastPage) : goPerson(p.id)) }, dot(p.color), p.name));
    });
  }

  // ---------- search ----------
  let searchIndex = [];
  function plain(md) {
    return md.replace(/```[\s\S]*?```/g, " ").replace(/<[^>]+>/g, " ").replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/[#*_`>|]/g, " ").replace(/\s+/g, " ").trim();
  }
  function setupSearch() {
    searchIndex = D.nodes.map((n) => ({ kind: "page", n, title: n.title, text: plain(n.markdown) }))
      .concat(D.people.map((p) => ({ kind: "Person", person: p, title: p.name, text: p.focus || "" })))
      .concat(D.work.map((w) => ({ kind: w.kind === "pr" ? "Pull request" : "Issue", n: byId[w.pages.find((p) => byId[p])], title: w.title, text: personName(workPerson(w), w.author) })))
      .concat(D.questions.map((q) => ({ kind: "Question", n: byId[q.page], title: q.title, text: q.answer_excerpt || "" })))
      .filter((e) => e.n || e.person);
    const back = $("qs"), input = $("search"), list = $("results");
    let hits = [], sel = 0, returnTo = null;
    const parentTitle = (n) => (n.parent && byId[n.parent] ? byId[n.parent].title : "");
    function show() {
      const q = input.value.trim().toLowerCase();
      list.textContent = "";
      const terms = q ? q.split(/\s+/) : [];
      if (!q) {
        // empty box: the pages people are working on, then hubs
        hits = D.nodes.filter((n) => pagePerson(n.id)).concat(hubs).filter((n, i, a) => a.indexOf(n) === i)
          .slice(0, 10).map((n) => ({ e: { kind: "page", n, title: n.title, text: "" } }));
      } else {
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
      }
      sel = 0;
      if (!hits.length) list.append(h("li", { class: "empty", role: "option", "aria-disabled": "true" }, "No matches"));
      hits.forEach((hit, i) => {
        const e = hit.e;
        const color = e.person ? e.person.color : pagePerson(e.n.id) ? personColor(pagePerson(e.n.id)) : null;
        const kind = e.kind === "page" ? parentTitle(e.n) : e.kind;
        const snip = e.kind === "page" ? (q && !e.title.toLowerCase().includes(terms[0]) ? snippet(e.text, terms[0]) : null)
          : e.person ? (e.text ? [e.text] : null) : [e.kind + " on " + e.n.title + (e.text ? " - " : ""), ...snippet(e.text, terms[0] || "")];
        const li = h("li", { role: "option", id: "res-" + i, "aria-selected": String(i === 0) },
          h("span", { class: "r-title" }, color ? dot(color) : null, mark(e.title, terms[0]), kind ? h("span", { class: "r-kind" }, kind) : null),
          snip ? h("span", { class: "r-snip" }, snip) : null);
        li.addEventListener("mousedown", (ev) => { ev.preventDefault(); pick(i); });
        li.addEventListener("mousemove", () => { if (sel !== i) { sel = i; paint(); } });
        list.append(li);
      });
      input.setAttribute("aria-expanded", "true");
      input.setAttribute("aria-activedescendant", hits.length ? "res-0" : "");
    }
    function mark(text, term) {
      const i = term ? text.toLowerCase().indexOf(term) : -1;
      if (i < 0) return h("span", null, text);
      return h("span", null, text.slice(0, i), h("mark", null, text.slice(i, i + term.length)), text.slice(i + term.length));
    }
    function snippet(text, term) {
      const i = term ? text.toLowerCase().indexOf(term) : -1;
      if (i < 0) return [text.slice(0, 90) + (text.length > 90 ? "..." : "")];
      const a = Math.max(0, i - 40), b = Math.min(text.length, i + term.length + 60);
      return [(a ? "..." : "") + text.slice(a, i), h("mark", null, text.slice(i, i + term.length)), text.slice(i + term.length, b) + (b < text.length ? "..." : "")];
    }
    function paint() {
      list.querySelectorAll("li").forEach((li, i) => li.setAttribute("aria-selected", String(i === sel)));
      input.setAttribute("aria-activedescendant", "res-" + sel);
    }
    function move(d) {
      if (!hits.length) return;
      sel = (sel + d + hits.length) % hits.length;
      paint();
      const li = $("res-" + sel); if (li) li.scrollIntoView({ block: "nearest" });
    }
    function pick(i) {
      const hit = hits[i]; if (!hit) return;
      close(true);
      if (hit.e.person) goPerson(hit.e.person.id); else go(hit.e.n.id);
    }
    function open() {
      if (!back.hidden) return;
      returnTo = document.activeElement;
      closeDrawer();
      back.hidden = false; input.value = ""; show(); input.focus();
    }
    function close(picked) {
      if (back.hidden) return;
      back.hidden = true; input.setAttribute("aria-expanded", "false");
      if (!picked && returnTo && returnTo.focus) returnTo.focus();
    }
    $("search-open").addEventListener("click", open);
    back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
    input.addEventListener("input", show);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") { e.preventDefault(); pick(sel); }
      else if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "Tab") e.preventDefault();
    });
    document.addEventListener("keydown", (e) => {
      const t = e.target;
      const typing = t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") { e.preventDefault(); if (back.hidden) open(); else close(); return; }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "/") { e.preventDefault(); open(); }
      else if (e.key === "m" || e.key === "M") toggleMap();
    });
  }

  // ---------- map show/hide (remembered per browser) ----------
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function setMap(show) {
    $("app").classList.toggle("no-map", !show);
    $("map-tog").setAttribute("aria-pressed", String(show));
    store("oak.map", show ? "1" : "0");
  }
  function toggleMap() { setMap($("app").classList.contains("no-map")); }
  function setupMapToggle() {
    setMap(store("oak.map") !== "0");
    $("map-tog").addEventListener("click", toggleMap);
  }

  // ---------- routing ----------
  function go(id, anchor) {
    const target = pageHash(id, anchor);
    if (location.hash === target) route(); else location.hash = target;
  }
  function goPerson(pid) {
    const target = personHash(pid);
    if (location.hash === target) route(); else location.hash = target;
  }
  function route() {
    const raw = decodeURIComponent(location.hash.slice(1));
    const [id, anchor] = raw.split("/");
    closeDrawer();
    if (id === "people" && anchor && people[anchor]) { openPerson(people[anchor]); return; }
    const oak = D.nodes.find((n) => n.depth === 0) || D.nodes[0];
    const n = byId[id] || oak;
    if (!n) return;
    if (current !== n) openPage(n);
    if (anchor) {
      const el = document.getElementById(anchor);
      if (el && $("content").contains(el)) el.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "start" });
    }
  }

  // ---------- reading pane ----------
  function setMode(personId) {
    filterPerson = personId;
    Object.entries(personLinks).forEach(([id, el]) => { if (id === personId) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current"); });
    $("ask").hidden = !!personId;
    $("ask-jump").hidden = !!personId;
    renderLegend();
  }

  function openPage(n) {
    const first = !current && !filterPerson && !viewedPerson;
    current = n;
    lastPage = n.id;
    viewedPerson = null;
    setMode(null);
    document.title = n.depth === 0 ? "Oak Workspace" : n.title + " - Oak Workspace";
    Object.entries(treeLinks).forEach(([id, el]) => { if (id === n.id) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current"); });
    if (n.hub && n.depth > 1) setOpen(n.hub, true);
    if (n.depth === 1) setOpen(n.id, true);
    const narrow = window.matchMedia("(max-width: 900px)").matches;
    const tl = treeLinks[n.id]; if (tl && !narrow) tl.scrollIntoView({ block: "nearest" });

    renderCrumbs(n); renderContent(n); renderProps(n); renderConnections(n); renderBacklinks(n); renderSaved(n); resetAsk();

    const page = $("page");
    page.classList.remove("enter"); void page.offsetWidth; page.classList.add("enter");
    $("reader-scroll").scrollTop = 0;
    if (!first && window.matchMedia("(max-width: 900px)").matches) window.scrollTo({ top: 0, behavior: "auto" });
    Graph.focus(n, first);
  }

  // ---------- a teammate's view ----------
  function openPerson(p) {
    const first = !current && !viewedPerson;
    current = null;
    viewedPerson = p;
    setMode(p.id);
    document.title = p.name + " - Oak Workspace";
    Object.values(treeLinks).forEach((el) => el.removeAttribute("aria-current"));
    const pl = personLinks[p.id]; if (pl && !window.matchMedia("(max-width: 900px)").matches) pl.scrollIntoView({ block: "nearest" });

    const nav = $("crumbs");
    nav.textContent = "";
    nav.append(h("button", { type: "button", onclick: () => go("people") }, "People"),
      h("span", { class: "sep", "aria-hidden": "true" }, "/"), h("span", { "aria-current": "page" }, p.name));
    ["connections", "backlinks", "saved"].forEach((id) => { $(id).textContent = ""; });

    const el = $("content");
    el.textContent = "";
    const pageBtn = (id) => byId[id] ? h("button", { type: "button", class: "pg-chip", onclick: () => go(id) }, dot(nodeColor(byId[id])), byId[id].title) : null;
    const sec = (title, count, body) => h("section", { class: "pv-sec" },
      h("h2", null, title, count ? h("span", { class: "pv-n" }, String(count)) : null), body);

    el.append(h("header", { class: "pv-head", style: "--c:" + p.color },
      h("span", { class: "pv-dot", "aria-hidden": "true" }),
      h("div", null,
        h("h1", null, p.name),
        h("p", { class: "pv-focus" }, h("span", { class: "pv-label" }, "Current focus"), p.focus || "TODO(" + p.id + "): add a focus line in docs/team.yml"),
        p.github ? h("a", { class: "pv-gh", href: "https://github.com/" + p.github, target: "_blank", rel: "noopener" }, "@" + p.github + " on GitHub") : null)));

    // Working on now
    const ws = workOf(p.id).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    const noGithub = !D.work.length && !D.sample;
    el.append(sec("Working on now", ws.length, ws.length
      ? h("ul", { class: "pv-work", style: "--c:" + p.color }, ws.map((w) => h("li", null,
          h("div", { class: "pv-w-top" },
            h("a", { href: w.url, target: "_blank", rel: "noopener" }, (w.kind === "pr" ? "PR" : "Issue") + " #" + w.number + ": " + w.title),
            w.review_requested ? h("span", { class: "tag" }, "review requested") : null,
            w.draft ? h("span", { class: "tag draft" }, "draft") : null,
            h("span", { class: "pv-when" }, rel(w.updated_at))),
          w.pages.some((x) => byId[x]) ? h("div", { class: "pv-pages" }, w.pages.map(pageBtn)) : null)))
      : h("p", { class: "pv-none" }, noGithub ? "No open work shown: this copy was built without GitHub access."
        : "No open issues or pull requests right now.")));

    // Active branches: sandbox work pushed lately, before any issue or PR
    const bs = branchesOf(p.id);
    el.append(sec("Active branches", bs.length, bs.length
      ? h("ul", { class: "pv-work pv-branches", style: "--c:" + p.color }, bs.map((b) => h("li", null,
          h("div", { class: "pv-w-top" },
            h("a", { class: "pv-branch", href: branchUrl(b.name), target: "_blank", rel: "noopener", title: "Open this branch on GitHub" }, b.name),
            b.pr ? h("a", { class: "tag", href: b.pr.url, target: "_blank", rel: "noopener" }, "Pull request #" + b.pr.number) : null,
            b.ahead ? h("span", { class: "tag draft" }, "ahead by " + b.ahead) : null),
          h("div", { class: "pv-when" }, "pushed " + rel(b.last_commit.date)),
          b.last_commit.message ? h("div", { class: "pv-msg" }, b.last_commit.message) : null,
          b.pages.some((x) => byId[x]) ? h("div", { class: "pv-pages" }, b.pages.map(pageBtn)) : null)))
      : h("p", { class: "pv-none" }, "No branches pushed in the last 14 days.")));

    // Has worked on
    const past = new Set(p.past);
    const worked = p.worked_on.filter((id) => byId[id]);
    el.append(sec("Has worked on", worked.length, worked.length
      ? h("ul", { class: "pv-grid" }, worked.map((id) => {
          const b = byId[id];
          return h("li", null, h("button", { type: "button", class: "bl", onclick: () => go(id), title: b.summary || null },
            b.title, past.has(id) ? h("span", { class: "tag draft" }, "earlier work") : null));
        }))
      : h("p", { class: "pv-none" }, "No pages yet. Commits to a page or its code show up here.")));

    // Recent changes by them
    const rs = D.recent.filter((r) => r.person === p.id).slice(0, 8);
    el.append(sec("Recent changes", rs.length, rs.length
      ? h("ul", { class: "feed pv-recent" }, rs.map((r) => {
          const firstPage = r.pages.find((x) => byId[x]);
          return h("li", null, h("button", { type: "button", class: "f-item", onclick: () => firstPage && go(firstPage) },
            dot(p.color), h("span", { class: "f-title" }, r.message),
            h("span", { class: "f-sub" }, h("span", null, pageLabel(r.pages)), h("span", null, rel(r.date)),
              r.sha ? h("code", null, r.sha.slice(0, 7)) : null)));
        }))
      : h("p", { class: "pv-none" }, "No changes by " + p.name + " in the last 40 commits that touched the wiki or its code.")));

    const page = $("page");
    page.classList.remove("enter"); void page.offsetWidth; page.classList.add("enter");
    $("reader-scroll").scrollTop = 0;
    if (!first && window.matchMedia("(max-width: 900px)").matches) window.scrollTo({ top: 0, behavior: "auto" });
    Graph.fit(first);
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

  // properties under the title: who is working here, open work, last change, code
  function renderProps(n) {
    const rows = [];
    const row = (label, ...lines) => { if (lines.some(Boolean)) rows.push(h("dt", null, label), h("dd", null, ...lines.filter(Boolean))); };
    const who = (pid, fallback) => h("span", { class: "who", style: "color:" + personColor(pid) }, personName(pid, fallback));
    const ext = (label, url) => (D.published ? h("a", { href: url, target: "_blank", rel: "noopener" }, label) : h("span", { class: "off", title: "Not on GitHub yet" }, label));

    // one line per item, newest first; long lists fold after 3
    const works = (workByPage[n.id] || []).slice().sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    const workLines = works.map((w) => {
      const pid = workPerson(w);
      const names = [pid].concat(w.assignees.filter((a) => a !== pid));
      return h("div", { class: "line one", title: w.title },
        dot(personColor(pid)), names.map((a, i) => [i ? ", " : "", who(a, i ? null : w.author)]), " · ",
        h("a", { href: w.url, target: "_blank", rel: "noopener" }, (w.kind === "pr" ? "PR" : "Issue") + " #" + w.number + " " + w.title),
        w.review_requested ? h("span", { class: "tag" }, "wants review") : null,
        w.draft ? h("span", { class: "tag draft" }, "draft") : null);
    });
    if (workLines.length > 3) {
      const rest = workLines.splice(3);
      rest.forEach((l) => { l.hidden = true; });
      const more = h("button", { type: "button", class: "more", onclick: () => { rest.forEach((l) => { l.hidden = false; }); more.remove(); } },
        rest.length + " more");
      workLines.push(...rest, more);
    }
    row("Open work", ...workLines);
    const bs = (branchesByPage[n.id] || []).filter((b) => !b.pr || !works.some((w) => w.number === b.pr.number));
    row("Branches", ...bs.map((b) => h("div", { class: "line" }, dot(personColor(b.person)), who(b.person), " on ",
      D.published ? h("a", { href: branchUrl(b.name), target: "_blank", rel: "noopener" }, h("code", null, b.name)) : h("code", null, b.name),
      " ", h("span", { class: "off" }, "pushed " + rel(b.last_commit.date)))));
    const lc = n.last_change;
    if (lc && (lc.date || lc.message)) {
      row("Last change", h("div", { class: "line" }, who(lc.person, lc.author), " " + rel(lc.date) + (lc.message ? ": " + lc.message : ""),
        lc.sha ? [" ", h("code", null, lc.sha.slice(0, 7))] : null));
    }
    if (n.code.length) row("Code", h("div", { class: "line" }, n.code.map((c, i) => [i ? ", " : "", ext(codeDir(c), treeUrl(c))])));
    if (n.path) row("Source", h("div", { class: "line" }, ext(n.path, blobUrl(n.path)),
      D.published ? null : h("span", { class: "off" }, " (branch " + D.branch + " is not on GitHub yet)")));
    if (!rows.length) return;
    const dl = h("dl", { class: "props", "aria-label": "About this page" }, rows);
    const h1 = $("content").querySelector("h1");
    if (h1) h1.after(dl); else $("content").prepend(dl);
  }

  // Connections: every page this one links to, with the sentence the link sits
  // in (what the link is about) and who is working on that page.
  function renderConnections(n) {
    const box = $("connections");
    box.textContent = "";
    const seen = new Set([n.id]), items = [];
    const md = n.markdown.replace(/^---\n[\s\S]*?\n---\n/, "").replace(/```[\s\S]*?```/g, "");
    md.split("\n").forEach((line) => {
      const re = /\[([^\]]*)\]\(([^)\s]+)\)/g;
      let m;
      while ((m = re.exec(line))) {
        if (/^[a-z][a-z0-9+.-]*:/i.test(m[2]) || m[2].startsWith("#")) continue;
        const page = byPath[resolvePath(n.path || "", m[2].split("#")[0])];
        if (!page || seen.has(page.id)) continue;
        seen.add(page.id);
        let about = line.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/<[^>]+>/g, " ").replace(/\*\*|__|`/g, "")
          .replace(/^\s*(?:[-+*]|\d+[.)]|#+|>)\s*/, "").replace(/\s+/g, " ").trim();
        if (/^part of:/i.test(about)) about = "The section this page belongs to.";
        else if (about === page.title || about.length < page.title.length + 4) about = page.summary || "";
        if (about.length > 180) about = about.slice(0, 177).replace(/\s+\S*$/, "") + "...";
        items.push({ page, about });
      }
    });
    if (!items.length) return;
    box.append(h("h2", { id: "h-conn" }, "Connects to " + items.length + (items.length === 1 ? " page" : " pages")));
    box.append(h("ul", { class: "conn" }, items.map(({ page, about }) => {
      const ps = pagePeople(page.id);
      return h("li", null, h("button", { type: "button", class: "cn", onclick: () => go(page.id),
        onmouseenter: () => Graph.peek(page), onmouseleave: () => Graph.peek(null) },
        h("span", { class: "cn-t" }, ps.length ? dot(personColor(ps[0])) : null, page.title),
        h("span", { class: "cn-s" }, about,
          ps.length ? [about ? " · " : "", ps.map((pid, i) => [i ? ", " : "", h("span", { class: "who", style: "color:" + personColor(pid) }, personName(pid))]),
            " working here"] : null)));
    })));
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
    // no id on the title: it would match the page's own #slug and make the browser jump past it
    el.querySelectorAll("h2,h3,h4,h5,h6").forEach((hd) => { hd.id = slug(hd.textContent); });
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

  function renderBacklinks(n) {
    const box = $("backlinks");
    box.textContent = "";
    const list = n.backlinks.filter((id) => byId[id] && id !== n.id);
    if (!list.length) return;
    box.append(h("h2", { id: "h-back" }, "Linked from " + list.length + (list.length === 1 ? " page" : " pages")));
    box.append(h("p", null, list.map((id, i) => [i ? ", " : "",
      h("button", { type: "button", onclick: () => go(id), title: byId[id].summary || null }, byId[id].title)])));
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
    $("side-open").addEventListener("click", () => { openDrawer(); $("side-close").focus(); });
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
    let hover = null, peeked = null, anim = null, raf = 0;

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
      return (n.depth === 0 ? 10 : n.depth === 1 ? 6.5 : 4.2) * s;
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

      // edges: grey; the current page's links light up, a teammate's in their color
      ctx.lineCap = "round";
      D.edges.forEach((e) => {
        const a = byId[e.source], b = byId[e.target];
        if (!a || !b) return;
        const hot = cur && !pf && (e.source === cur || e.target === cur);
        const pfHot = pf && pf.has(e.source) && pf.has(e.target);
        const [x1, y1] = toScreen(a.x, a.y), [x2, y2] = toScreen(b.x, b.y);
        let col = e.kind === "parent" ? "rgba(255,255,255,.13)" : "rgba(255,255,255,.07)";
        if (dimAll) col = e.kind === "parent" ? "rgba(255,255,255,.07)" : "rgba(255,255,255,.04)";
        if (hot) col = peeked && (e.source === peeked.id || e.target === peeked.id) ? "rgba(255,255,255,.85)" : "rgba(255,255,255,.26)";
        if (pfHot) col = hexA(pcol, 0.35);
        ctx.strokeStyle = col;
        ctx.lineWidth = hot ? 1.4 : 1;
        ctx.setLineDash(e.kind === "link" && !hot && !pfHot ? [2, 4] : []);
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      });
      ctx.setLineDash([]);

      // nodes: grey, or the color of the teammate working there
      const order = D.nodes.slice().sort((a, b) => b.depth - a.depth);
      order.forEach((n) => {
        const [x, y] = toScreen(n.x, n.y), r = radius(n);
        const on = !dimAll || isLit(n.id) || hover === n || peeked === n;
        ctx.globalAlpha = on ? 1 : 0.3;
        ctx.fillStyle = pf ? (pf.has(n.id) ? pcol : greyOf(n)) : nodeColor(n);
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
        if (n.id === cur || peeked === n) {
          ctx.strokeStyle = n.id === cur ? "#ffffff" : "rgba(255,255,255,.6)"; ctx.lineWidth = 1.6;
          ctx.beginPath(); ctx.arc(x, y, r + 3.5, 0, Math.PI * 2); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      });

      // labels: Oak and hubs always, pages when zoomed in or connected
      const showPages = cam.k >= fitK * 1.55;
      ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.lineJoin = "round";
      order.slice().reverse().forEach((n) => {
        const hot = n.id === cur || hover === n || peeked === n || (pf ? pf.has(n.id) : lit.has(n.id) && cur !== "oak");
        if (n.depth === 2 && !showPages && !hot) return;
        const [x, y] = toScreen(n.x, n.y), r = radius(n);
        const on = !dimAll || isLit(n.id) || hover === n || peeked === n;
        const size = n.depth === 0 ? 14 : n.depth === 1 ? 12.5 : 11.5;
        const weight = n.id === cur || n.depth === 0 ? 600 : n.depth === 1 ? 500 : 400;
        ctx.font = weight + " " + size + 'px "Inter", system-ui, sans-serif';
        ctx.lineWidth = 4; ctx.strokeStyle = BG;
        ctx.strokeText(n.title, x, y + r + 5);
        ctx.fillStyle = !on ? "rgba(200,200,200,.28)" : n.id === cur ? "#ffffff" : n.depth === 2 ? "#a8a8a8" : "#d0d0d0";
        ctx.fillText(n.title, x, y + r + 5);
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
      if (n.summary) tip.append(h("span", null, n.summary));
      const ps = pagePeople(n.id);
      if (ps.length) tip.append(h("span", { class: "tip-meta" }, ps.map((pid, i) => [i ? ", " : "",
        h("span", { style: "color:" + personColor(pid) + ";font-weight:500" }, personName(pid))]), " working here"));
      const k = nbrs[n.id] ? nbrs[n.id].size : 0;
      tip.append(h("span", { class: "tip-meta" }, k + (k === 1 ? " connection" : " connections") + " · click to open"));
      tip.hidden = false;
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      tip.style.left = Math.min(W - tw - 8, Math.max(8, p[0] + 14)) + "px";
      tip.style.top = Math.min(H - th - 8, Math.max(8, p[1] + 14)) + "px";
    }
    function hideTip() { tip.hidden = true; }

    // fit the whole map, e.g. so all of a teammate's pages are in view
    function fit(instant) {
      if (!W) return;
      if (instant) { Object.assign(cam, computeFit()); draw(); } else animateTo(computeFit());
    }

    // light up a page from the reader (hovering a connection)
    function peek(n) { if (peeked !== n) { peeked = n; draw(); } }

    return { init, focus, draw, fit, peek };
  })();
})();
