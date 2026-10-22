/* Oak wiki: 3D graph of README.md (Oak) -> hubs -> program pages.
   Data comes from graph.json, built by scripts/wiki/build_graph.py. */
(function () {
  "use strict";

  const REPO = "https://github.com/maxhawksby/go2-fusion";
  const BRANCH = "master";
  const HUB_COLORS = {
    driving: "#ff9f5a",
    driver: "#5aa8ff",
    senses: "#3be0a6",
    "maps-nav": "#ffd65a",
    brains: "#ff6fc8",
    "lab-setup": "#5ee6ff",
    team: "#a99bff",
  };
  const OAK_COLOR = "#f2f7ff";
  const FALLBACK = ["#ff8a80", "#b9f6ca", "#ffe57f", "#84ffff", "#ea80fc"];
  const SHELL = [0, 130, 280]; // distance from Oak by depth
  const HOME_CAM = { x: 0, y: -60, z: 680 };
  const PANEL_W = 470; // keep in sync with #panel width in style.css

  const $ = (id) => document.getElementById(id);
  const status = $("status");

  let settled = false, pendingFly = null;
  let graph, byId = {}, byPath = {}, nodes = [], current = null;

  fetch("graph.json")
    .then((r) => {
      if (!r.ok) throw new Error("graph.json not found");
      return r.json();
    })
    .then(start)
    .catch((err) => {
      status.textContent = "Could not load graph.json. Run: python3 scripts/wiki/build_graph.py (" + err.message + ")";
    });

  function colorOf(n) {
    if (n.depth === 0) return OAK_COLOR;
    if (HUB_COLORS[n.hub]) return HUB_COLORS[n.hub];
    const hubs = nodes.filter((x) => x.depth === 1).map((x) => x.id);
    return FALLBACK[Math.max(0, hubs.indexOf(n.hub)) % FALLBACK.length];
  }

  // Hubs sit on a ring facing the first camera, tilted in and out of the
  // screen so the graph still has depth when you orbit it.
  function directions(count) {
    const out = [];
    for (let i = 0; i < count; i++) {
      const t = (i / count) * Math.PI * 2 + Math.PI / 2;
      out.push({ t, x: Math.cos(t), y: Math.sin(t) * 0.72, z: (i % 2 ? 0.35 : -0.35) });
    }
    return out;
  }

  function glowTexture() {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const g = c.getContext("2d");
    const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.2, "rgba(255,255,255,0.55)");
    grad.addColorStop(0.5, "rgba(255,255,255,0.12)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  function addStars(scene) {
    const count = 1600;
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 900 + Math.random() * 1600;
      const u = Math.random() * 2 - 1;
      const t = Math.random() * Math.PI * 2;
      const s = Math.sqrt(1 - u * u);
      pos[i * 3] = r * s * Math.cos(t);
      pos[i * 3 + 1] = r * u;
      pos[i * 3 + 2] = r * s * Math.sin(t);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({ color: 0x9fb4ff, size: 2.2, sizeAttenuation: true, transparent: true, opacity: 0.55, depthWrite: false });
    scene.add(new THREE.Points(geo, mat));
  }

  function start(data) {
    nodes = data.nodes;
    nodes.forEach((n) => { byId[n.id] = n; byPath[n.path] = n; });

    // Pin Oak at the center and the hubs on the first shell.
    const hubs = nodes.filter((n) => n.depth === 1);
    const dirs = directions(hubs.length);
    hubs.forEach((h, i) => {
      h.dir = dirs[i];
      h.fx = dirs[i].x * SHELL[1]; h.fy = dirs[i].y * SHELL[1]; h.fz = dirs[i].z * SHELL[1];
    });
    // Program pages fan out on the outer shell around their hub's angle.
    // Deeper pages (if any are added later) go one shell further out.
    const ARC = 0.17; // radians between siblings
    nodes.forEach((n) => { if (n.depth === 0) { n.fx = 0; n.fy = 0; n.fz = 0; } });
    hubs.forEach((h) => {
      const kids = nodes.filter((n) => n.hub === h.id && n.depth >= 2);
      kids.forEach((n, i) => {
        const t = h.dir.t + (i - (kids.length - 1) / 2) * ARC;
        const r = SHELL[2] + (n.depth - 2) * 110;
        n.fx = Math.cos(t) * r;
        n.fy = Math.sin(t) * r * 0.72;
        n.fz = h.dir.z * r + (i % 2 ? 30 : -30);
      });
    });

    const links = data.edges.map((e) => ({ source: e.source, target: e.target, kind: e.kind }));
    const tex = glowTexture();

    graph = ForceGraph3D({ controlType: "orbit" })($("graph"))
      .backgroundColor("rgba(0,0,0,0)")
      .showNavInfo(false)
      .graphData({ nodes, links })
      .nodeId("id")
      .nodeLabel(() => "")
      .nodeThreeObject((n) => makeNode(n, tex))
      .linkColor((l) => {
        const c = colorOf(typeof l.target === "object" ? l.target : byId[l.target]);
        return l.kind === "parent" ? c : "#8fa6d8";
      })
      .linkOpacity(0.35)
      .linkWidth((l) => (l.kind === "parent" ? 0.9 : 0.25))
      .linkDirectionalParticles((l) => (l.kind === "parent" ? 2 : 0))
      .linkDirectionalParticleSpeed(0.005)
      .linkDirectionalParticleWidth(1.6)
      .linkDirectionalParticleColor((l) => colorOf(typeof l.target === "object" ? l.target : byId[l.target]))
      .onNodeClick((n) => focus(n.id))
      .onNodeHover((n) => { $("graph").style.cursor = n ? "pointer" : ""; })
      .cooldownTime(1500)
      .onEngineStop(() => { settled = true; if (pendingFly) { pendingFly(); pendingFly = null; } })
      .onBackgroundClick(() => {});

    // Every node is pinned to its shell, so the physics has nothing to do.
    graph.d3Force("charge", null);

    addStars(graph.scene());
    const ambient = new THREE.AmbientLight(0xffffff, 0.9);
    graph.scene().add(ambient);
    graph.cameraPosition(HOME_CAM, { x: 0, y: 0, z: 0 });
    const controls = graph.controls();
    if (controls) { controls.autoRotate = true; controls.autoRotateSpeed = 0.35; }
    $("graph").addEventListener("pointerdown", () => { if (controls) controls.autoRotate = false; }, { once: true });

    buildLegend(hubs);
    buildSearch();
    $("home").onclick = $("back").onclick = () => goHome();
    $("close").onclick = () => closePanel();
    window.addEventListener("resize", fitCanvas);
    window.addEventListener("hashchange", fromHash);
    status.textContent = "";
    fromHash();
  }

  function makeNode(n, tex) {
    const color = colorOf(n);
    const size = n.depth === 0 ? 14 : n.depth === 1 ? 8 : 4.2;
    const group = new THREE.Group();

    const core = new THREE.Mesh(
      new THREE.SphereGeometry(size, 24, 16),
      new THREE.MeshBasicMaterial({ color })
    );
    group.add(core);

    const glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, color, transparent: true, opacity: n.depth === 0 ? 0.9 : 0.75,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    glow.scale.setScalar(size * (n.depth === 0 ? 7 : 6));
    group.add(glow);

    const label = new SpriteText(n.title);
    label.color = n.depth === 2 ? "#c9d4f2" : "#ffffff";
    label.textHeight = n.depth === 0 ? 14 : n.depth === 1 ? 9 : 7;
    label.fontFace = "Space Grotesk, system-ui, sans-serif";
    label.fontWeight = n.depth === 2 ? "400" : "600";
    label.material.depthWrite = false;
    label.position.y = -(size + label.textHeight * 0.95);
    group.add(label);

    if (n.work && n.work.length) {
      const badge = new SpriteText(" " + n.work.length + " ");
      badge.color = "#1a1200";
      badge.backgroundColor = "#ffb547";
      badge.borderRadius = 6;
      badge.padding = 1;
      badge.textHeight = n.depth === 2 ? 6 : 8;
      badge.fontWeight = "700";
      badge.position.set(size * 1.1, size * 1.1, 0);
      group.add(badge);
    }
    return group;
  }

  function buildLegend(hubs) {
    const legend = $("legend");
    hubs.forEach((h) => {
      const b = document.createElement("button");
      b.innerHTML = '<span class="swatch"></span>';
      b.firstChild.style.background = colorOf(h);
      b.firstChild.style.boxShadow = "0 0 8px " + colorOf(h);
      b.append(h.title);
      b.onclick = () => focus(h.id);
      legend.append(b);
    });
  }

  function buildSearch() {
    const input = $("search"), list = $("results");
    let hits = [], sel = 0;
    const render = () => {
      list.innerHTML = "";
      hits.forEach((n, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", i === sel ? "true" : "false");
        const sw = document.createElement("span");
        sw.className = "swatch";
        sw.style.background = colorOf(n);
        li.append(sw, n.title);
        if (n.hub && n.depth > 1) {
          const s = document.createElement("small");
          s.textContent = byId[n.hub].title;
          li.append(s);
        }
        li.onmousedown = (e) => { e.preventDefault(); pick(n); };
        list.append(li);
      });
      list.hidden = hits.length === 0;
    };
    const pick = (n) => { input.value = ""; hits = []; render(); input.blur(); focus(n.id); };
    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      sel = 0;
      if (!q) { hits = []; return render(); }
      const score = (n) => {
        const t = n.title.toLowerCase();
        if (t.startsWith(q) || n.id.startsWith(q)) return 0;
        if (t.includes(q) || n.id.includes(q)) return 1;
        if ((n.code || []).join(" ").toLowerCase().includes(q)) return 2;
        if (n.markdown.toLowerCase().includes(q)) return 3;
        return 9;
      };
      hits = nodes.map((n) => [score(n), n]).filter((x) => x[0] < 9)
        .sort((a, b) => a[0] - b[0] || a[1].depth - b[1].depth).slice(0, 8).map((x) => x[1]);
      render();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { sel = Math.min(sel + 1, hits.length - 1); render(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); render(); e.preventDefault(); }
      else if (e.key === "Enter" && hits[sel]) pick(hits[sel]);
      else if (e.key === "Escape") { input.value = ""; hits = []; render(); input.blur(); }
    });
    input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 100));
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== input) { e.preventDefault(); input.focus(); }
    });
  }

  function fromHash() {
    const id = decodeURIComponent(location.hash.slice(1));
    if (id && byId[id] && id !== current) focus(id, true);
  }

  function goHome() {
    focus("oak");
  }

  function focus(id, fromHashChange) {
    const n = byId[id];
    if (!n) return;
    current = id;
    if (!fromHashChange && location.hash.slice(1) !== id) history.replaceState(null, "", "#" + id);
    const controls = graph.controls();
    if (controls) controls.autoRotate = false;

    const fly = () => {
      if (n.depth === 0) {
        graph.cameraPosition(HOME_CAM, { x: 0, y: 0, z: 0 }, 1200);
      } else {
        // Approach from the front, like the home view, so Oak and the hubs
        // never sit between the camera and the page.
        const dist = n.depth === 1 ? 320 : 220;
        graph.cameraPosition({ x: n.x, y: n.y - 30, z: n.z + dist }, { x: n.x, y: n.y, z: n.z }, 1200);
      }
    };
    openPanel(n);
    if (settled) fly();
    else {
      // Wait for the layout to settle, but never longer than a few seconds.
      pendingFly = fly;
      setTimeout(() => { if (pendingFly === fly) { pendingFly = null; fly(); } }, 4500);
    }
  }

  // On wide screens the graph shrinks to the space left of the panel, so the
  // focused node stays visible; on phones the panel is a bottom sheet.
  function fitCanvas() {
    const open = !$("panel").hidden && innerWidth > 760;
    graph.width(open ? innerWidth - PANEL_W : innerWidth).height(innerHeight);
  }

  function openPanel(n) {
    $("panel").hidden = false;
    fitCanvas();

    // Breadcrumb: Oak > hub > page
    const chain = [];
    for (let x = n; x; x = x.parent ? byId[x.parent] : null) chain.unshift(x);
    const crumbs = $("crumbs");
    crumbs.innerHTML = "";
    chain.forEach((x, i) => {
      if (i) { const s = document.createElement("span"); s.className = "sep"; s.textContent = ">"; crumbs.append(s); }
      if (x === n) {
        const s = document.createElement("span"); s.className = "here"; s.textContent = x.title; crumbs.append(s);
      } else {
        const a = document.createElement("a"); a.textContent = x.title; a.onclick = () => focus(x.id); crumbs.append(a);
      }
    });

    // Active work from GitHub issues labelled wiki:<slug>
    const work = $("work");
    work.innerHTML = "";
    (n.work || []).forEach((w) => {
      const a = document.createElement("a");
      a.className = "work-item";
      a.href = w.url; a.target = "_blank"; a.rel = "noopener";
      const who = w.assignees && w.assignees.length ? "Teammate " + w.assignees.join(", ") : "Someone";
      const b = document.createElement("b");
      b.textContent = who;
      a.append(b, " is working on: " + w.title + " (#" + w.number + ")");
      work.append(a);
    });

    const md = n.markdown.replace(/<!--[\s\S]*?-->/g, "");
    const content = $("content");
    content.innerHTML = marked.parse(md);
    fixLinks(content, n);
    content.scrollTop = 0;

    $("code").textContent = (n.code || []).join("  ");
    $("code").title = (n.code || []).join("\n");
    $("github").href = REPO + "/blob/" + BRANCH + "/" + n.path;
  }

  // Resolve a link relative to the page's own folder, like GitHub does.
  function resolvePath(base, href) {
    const parts = base.split("/").slice(0, -1);
    href.split("/").forEach((p) => {
      if (p === "..") parts.pop();
      else if (p && p !== ".") parts.push(p);
    });
    return parts.join("/");
  }

  function fixLinks(root, n) {
    root.querySelectorAll("a[href]").forEach((a) => {
      const href = a.getAttribute("href");
      if (/^[a-z][a-z0-9+.-]*:/i.test(href)) { a.target = "_blank"; a.rel = "noopener"; return; }
      if (href.startsWith("#")) { a.href = REPO + "/blob/" + BRANCH + "/" + n.path + href; a.target = "_blank"; return; }
      const [path] = href.split("#");
      const full = resolvePath(n.path, path);
      const target = byPath[full];
      if (target) {
        a.classList.add("node-link");
        a.href = "#" + target.id;
        a.onclick = (e) => { e.preventDefault(); focus(target.id); };
      } else {
        a.href = REPO + "/blob/" + BRANCH + "/" + full;
        a.target = "_blank"; a.rel = "noopener";
      }
    });
    root.querySelectorAll("img[src]").forEach((img) => {
      const src = img.getAttribute("src");
      if (!/^[a-z][a-z0-9+.-]*:/i.test(src)) img.src = REPO + "/raw/" + BRANCH + "/" + resolvePath(n.path, src);
      img.loading = "lazy";
    });
  }

  function closePanel() {
    $("panel").hidden = true;
    fitCanvas();
    current = null;
    history.replaceState(null, "", location.pathname);
  }
})();
