#!/usr/bin/env node
// `npm run wiki`: builds the Oak wiki data, serves site/ on localhost, opens
// the browser and reloads it whenever a wiki page changes.
//
//   npm run wiki                    # http://localhost:4410/
//   npm run wiki -- --port 4500     # another port
//   npm run wiki -- --no-open       # do not open a browser
//
// Node built-ins only. The page files in site/ are served as they are; the
// small reload script is added to index.html on the way out.
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawn, spawnSync } = require("child_process");
const { ROOT, findPython, noPythonMessage, runPython } = require("./python");

const SITE = path.join(ROOT, "site");
const GRAPH = path.join(SITE, "graph.json");
const DEFAULT_PORT = 4410;
const DEFAULT_REPO = "maxhawksby/go2-fusion";
const REFRESH_MS = 5 * 60 * 1000; // re-read GitHub this often
const POLL_MS = 1500; // backup check for file systems where fs.watch is silent
const DEBOUNCE_MS = 250;

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/plain; charset=utf-8",
};

// Runs in the browser: reload on "reload", show a note on "error".
const RELOAD_CLIENT = `(() => {
  let note;
  function show(msg) {
    if (!note) {
      note = document.createElement("div");
      note.setAttribute("role", "status");
      note.style.cssText = "position:fixed;left:16px;right:16px;bottom:16px;z-index:9999;max-width:640px;margin:0 auto;" +
        "padding:12px 14px;border-radius:8px;background:#3a1d1d;color:#ffd9d4;border:1px solid #a4483d;" +
        "font:13px/1.45 system-ui,sans-serif;white-space:pre-wrap;box-shadow:0 6px 24px rgba(0,0,0,.4)";
      document.body.appendChild(note);
    }
    note.textContent = msg;
  }
  const es = new EventSource("/__oak/events");
  es.addEventListener("reload", () => location.reload());
  es.addEventListener("error-note", (e) => show("The wiki could not rebuild, so you are seeing the last good version.\\n\\n" + JSON.parse(e.data).message));
  es.addEventListener("ok", () => { if (note) { note.remove(); note = null; } });
})();
`;

// ---------------------------------------------------------------- options

function parseArgs(argv) {
  const opts = { port: DEFAULT_PORT, open: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--no-open") opts.open = false;
    else if (a === "--port" || a.startsWith("--port=")) {
      const v = a.includes("=") ? a.split("=")[1] : argv[++i];
      opts.port = Number(v);
      if (!Number.isInteger(opts.port) || opts.port < 0 || opts.port > 65535) {
        throw new Error(`--port needs a number from 1 to 65535, got "${v}".`);
      }
    } else if (a === "--help" || a === "-h") opts.help = true;
    else throw new Error(`Unknown option "${a}". Try --port <number> or --no-open.`);
  }
  return opts;
}

// ---------------------------------------------------------------- GitHub

function git(...args) {
  const r = spawnSync("git", args, { cwd: ROOT, encoding: "utf8", windowsHide: true });
  return r.status === 0 ? r.stdout.trim() : "";
}

// owner/name from the origin remote (works for https, ssh and ssh host aliases).
function repoName() {
  const m = /github\.com[^:/]*[:/]([^/]+)\/([^/]+?)(?:\.git)?\/?$/.exec(git("remote", "get-url", "origin"));
  return m ? `${m[1]}/${m[2]}` : DEFAULT_REPO;
}

// A read token from GITHUB_TOKEN or the GitHub CLI, or null.
function githubToken() {
  if (process.env.GITHUB_TOKEN) return { token: process.env.GITHUB_TOKEN, from: "GITHUB_TOKEN" };
  const r = spawnSync("gh", ["auth", "token"], { encoding: "utf8", timeout: 5000, windowsHide: true });
  const token = r.status === 0 ? r.stdout.trim() : "";
  return token ? { token, from: "gh" } : null;
}

// ---------------------------------------------------------------- build

function createBuilder({ env, log }) {
  let running = null;
  let again = false;
  let lastData = null; // graph.json without generated_at, to skip no-op reloads
  let lastError = null;

  function graphData() {
    try {
      const g = JSON.parse(fs.readFileSync(GRAPH, "utf8"));
      delete g.generated_at;
      return JSON.stringify(g);
    } catch {
      return null;
    }
  }

  async function once(reason) {
    const started = Date.now();
    const { code, output } = await runPython(["scripts/wiki/build_graph.py"], { env, quiet: true });
    const text = output.trim();
    if (code !== 0) {
      lastError = text || `build_graph.py stopped with exit code ${code}.`;
      log(`Rebuild failed (${reason}):\n${indent(lastError)}`);
      return { ok: false, error: lastError };
    }
    for (const line of text.split("\n")) {
      if (line.includes("build_graph:")) log(line.trim()); // warnings, e.g. GitHub unreachable
    }
    const data = graphData();
    const changed = data !== lastData;
    const recovered = lastError !== null;
    lastData = data;
    lastError = null;
    if (reason !== "start") log(`Rebuilt in ${Date.now() - started} ms (${reason})${changed ? "" : ", nothing new"}.`);
    return { ok: true, changed, recovered, summary: text.split("\n").pop() };
  }

  // One build at a time; a change during a build queues exactly one more.
  function build(reason) {
    if (running) {
      again = true;
      return running;
    }
    running = (async () => {
      let result;
      try {
        do {
          again = false;
          result = await once(reason);
        } while (again);
      } finally {
        running = null;
      }
      return result;
    })();
    return running;
  }

  return { build, error: () => lastError };
}

function indent(s) {
  return s.split("\n").map((l) => "    " + l).join("\n");
}

// ---------------------------------------------------------------- watch

// What can change the wiki: README.md, docs/team.yml and docs/wiki/**.
function watchedFiles() {
  const files = [path.join(ROOT, "README.md"), path.join(ROOT, "docs", "team.yml")];
  (function walk(dir) {
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else files.push(p);
    }
  })(path.join(ROOT, "docs", "wiki"));
  return files;
}

function signature() {
  return watchedFiles()
    .map((f) => {
      try {
        const s = fs.statSync(f);
        return `${f}:${s.mtimeMs}:${s.size}`;
      } catch {
        return `${f}:missing`;
      }
    })
    .join("|");
}

// Calls onChange (debounced) when a watched file is added, edited or removed.
// fs.watch on the folders gives instant events (folders survive editors that
// save by replacing the file); a slow poll covers file systems where it is silent.
function watch(onChange) {
  let sig = signature();
  let timer = null;
  const check = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const now = signature();
      if (now !== sig) {
        sig = now;
        onChange();
      }
    }, DEBOUNCE_MS);
  };
  const watchers = [];
  const dirs = [ROOT, path.join(ROOT, "docs"), path.join(ROOT, "docs", "wiki")];
  for (const dir of dirs) {
    try {
      watchers.push(fs.watch(dir, check));
    } catch {
      // folder missing or watching unsupported: the poll still covers it
    }
  }
  const poll = setInterval(check, POLL_MS);
  return () => {
    clearTimeout(timer);
    clearInterval(poll);
    watchers.forEach((w) => w.close());
  };
}

// ---------------------------------------------------------------- serve

function createServer() {
  const clients = new Set();

  function send(event, data = {}) {
    const msg = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    for (const res of clients) res.write(msg);
  }

  const server = http.createServer((req, res) => {
    let url;
    try {
      url = new URL(req.url, "http://localhost");
    } catch {
      res.writeHead(400).end();
      return;
    }
    if (url.pathname === "/__oak/events") {
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-store",
        Connection: "keep-alive",
      });
      res.write(": connected\n\n");
      clients.add(res);
      req.on("close", () => clients.delete(res));
      return;
    }
    if (url.pathname === "/__oak/reload.js") {
      res.writeHead(200, { "Content-Type": TYPES[".js"], "Cache-Control": "no-store" });
      res.end(RELOAD_CLIENT);
      return;
    }
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { Allow: "GET, HEAD" }).end();
      return;
    }
    let rel;
    try {
      rel = decodeURIComponent(url.pathname);
    } catch {
      res.writeHead(400).end();
      return;
    }
    if (rel.endsWith("/")) rel += "index.html";
    const file = path.resolve(SITE, "." + rel);
    if (file !== SITE && !file.startsWith(SITE + path.sep)) {
      res.writeHead(403).end();
      return;
    }
    fs.readFile(file, (err, body) => {
      if (err) {
        res.writeHead(404, { "Content-Type": TYPES[".txt"] }).end("Not found");
        return;
      }
      const ext = path.extname(file).toLowerCase();
      if (file === path.join(SITE, "index.html")) {
        const tag = '<script src="/__oak/reload.js"></script>';
        const html = body.toString("utf8");
        body = Buffer.from(html.includes("</body>") ? html.replace("</body>", `${tag}\n</body>`) : html + tag);
      }
      res.writeHead(200, {
        "Content-Type": TYPES[ext] || "application/octet-stream",
        "Content-Length": body.length,
        "Cache-Control": "no-store",
      });
      res.end(req.method === "HEAD" ? undefined : body);
    });
  });

  // Keeps idle connections alive through proxies and sleeping laptops.
  const ping = setInterval(() => {
    for (const res of clients) res.write(": ping\n\n");
  }, 25000);
  server.on("close", () => clearInterval(ping));

  return { server, send, clients };
}

function listen(server, port) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      server.off("error", reject);
      resolve(server.address().port);
    });
  });
}

// ---------------------------------------------------------------- browser

function isWsl() {
  if (process.platform !== "linux") return false;
  if (process.env.WSL_DISTRO_NAME) return true;
  try {
    return /microsoft/i.test(fs.readFileSync("/proc/version", "utf8"));
  } catch {
    return false;
  }
}

function openBrowser(url) {
  let cmd, args;
  const extra = {};
  if (process.platform === "win32") {
    // `start` takes the first quoted argument as a window title, hence "".
    [cmd, args] = ["cmd", ["/c", "start", '""', url]];
    extra.windowsVerbatimArguments = true;
  } else if (isWsl()) {
    [cmd, args] = ["cmd.exe", ["/c", "start", url]];
    // cmd.exe warns about Linux folders as its working folder; give it a Windows one.
    if (fs.existsSync("/mnt/c")) extra.cwd = "/mnt/c";
  } else if (process.platform === "darwin") [cmd, args] = ["open", [url]];
  else [cmd, args] = ["xdg-open", [url]];
  try {
    const child = spawn(cmd, args, { stdio: "ignore", detached: true, windowsHide: true, ...extra });
    child.on("error", () => {}); // no browser opener: the banner still shows the address
    child.unref();
  } catch {
    // same as above
  }
}

// ---------------------------------------------------------------- main

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (err) {
    console.error(err.message);
    process.exit(2);
  }
  if (opts.help) {
    console.log("npm run wiki [-- --port <number>] [-- --no-open]");
    return;
  }

  const py = findPython();
  if (!py) {
    console.error(noPythonMessage());
    process.exit(1);
  }

  const log = (msg) => console.log(`  ${time()}  ${msg}`);
  const gh = githubToken();
  const env = gh ? { GITHUB_TOKEN: gh.token, GITHUB_REPOSITORY: process.env.GITHUB_REPOSITORY || repoName() } : {};

  console.log("\n  Building the Oak wiki...");
  const builder = createBuilder({ env, log });
  const first = await builder.build("start");
  if (!first.ok) {
    console.error("\n  The wiki pages have a problem, so there is nothing to show yet:\n");
    console.error(indent(builder.error()));
    console.error("\n  Fix it and run `npm run wiki` again.\n");
    process.exit(1);
  }

  const { server, send } = createServer();
  let port;
  try {
    port = await listen(server, opts.port);
  } catch (err) {
    if (err.code === "EADDRINUSE") {
      console.error(`\n  Port ${opts.port} is already in use. Is the wiki already open in another terminal?`);
      console.error(`  Use another port: npm run wiki -- --port ${opts.port + 1}\n`);
    } else console.error(`\n  Could not start the server: ${err.message}\n`);
    process.exit(1);
  }
  const url = `http://localhost:${port}/`;

  console.log(`
  Oak wiki is running   ${url}

  ${first.summary}
  Live     edits to README.md, docs/wiki/ and docs/team.yml reload the page
  GitHub   ${gh ? `on (token from ${gh.from}), refreshed every 5 minutes` : 'off: run "gh auth login" to see who is working on what'}
  Python   ${[py.cmd, ...py.pre].join(" ")} (${py.version})
  Stop     Ctrl+C
`);

  async function rebuild(reason) {
    const r = await builder.build(reason);
    if (!r.ok) send("error-note", { message: r.error });
    else if (r.changed) send("reload");
    else if (r.recovered) send("ok");
  }

  const stopWatching = watch(() => rebuild("a page changed"));
  const refresh = setInterval(() => rebuild("5 minute refresh"), REFRESH_MS);
  if (opts.open) openBrowser(url);

  const stop = () => {
    console.log("\n  Stopped the Oak wiki. Bye!\n");
    stopWatching();
    clearInterval(refresh);
    server.close();
    process.exit(0);
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}

function time() {
  return new Date().toTimeString().slice(0, 8);
}

module.exports = { parseArgs, createServer, repoName, RELOAD_CLIENT };

if (require.main === module) main();
