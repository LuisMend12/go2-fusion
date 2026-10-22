// Finds a Python 3.8+ on this computer and runs the wiki scripts with it.
// Used by `npm run wiki`, `npm run wiki:check` and `npm test`.
"use strict";

const { spawn, spawnSync } = require("child_process");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const MIN = [3, 8];

// Each candidate is [command, ...leading args]. `py -3` is the Windows launcher.
const CANDIDATES = [["python3"], ["python"]];
if (process.platform === "win32") CANDIDATES.push(["py", "-3"]);

let found;

function findPython() {
  if (found !== undefined) return found;
  found = null;
  for (const [cmd, ...pre] of CANDIDATES) {
    const r = spawnSync(cmd, [...pre, "--version"], { encoding: "utf8", windowsHide: true });
    if (r.error || r.status !== 0) continue;
    const m = /Python (\d+)\.(\d+)/.exec(`${r.stdout} ${r.stderr}`);
    if (!m) continue;
    const [major, minor] = [Number(m[1]), Number(m[2])];
    if (major > MIN[0] || (major === MIN[0] && minor >= MIN[1])) {
      found = { cmd, pre, version: `${major}.${minor}` };
      break;
    }
  }
  return found;
}

function noPythonMessage() {
  return [
    "Could not find Python 3.8 or newer. The wiki needs it to read the pages.",
    "Tried: " + CANDIDATES.map((c) => c.join(" ")).join(", ") + ".",
    "Install it from https://www.python.org/downloads/ (on Windows, tick \"Add python.exe to PATH\"),",
    "or on Ubuntu/WSL: sudo apt install python3. Then run the command again.",
  ].join("\n");
}

// Runs Python with args from the repo root. Resolves to { code, output }.
// With `quiet`, output is captured instead of shown.
function runPython(args, { env, quiet = false } = {}) {
  const py = findPython();
  if (!py) return Promise.reject(new Error(noPythonMessage()));
  return new Promise((resolve, reject) => {
    const child = spawn(py.cmd, [...py.pre, ...args], {
      cwd: ROOT,
      env: { ...process.env, PYTHONIOENCODING: "utf-8", ...env },
      stdio: quiet ? ["ignore", "pipe", "pipe"] : "inherit",
      windowsHide: true,
    });
    let output = "";
    if (quiet) {
      child.stdout.on("data", (d) => (output += d));
      child.stderr.on("data", (d) => (output += d));
    }
    child.on("error", reject);
    child.on("close", (code) => resolve({ code: code === null ? 1 : code, output }));
  });
}

module.exports = { ROOT, findPython, noPythonMessage, runPython };

// `node tools/oak-wiki/python.js <args>` runs Python with those args
// (npm run wiki:check and npm test use this).
if (require.main === module) {
  runPython(process.argv.slice(2)).then(
    ({ code }) => process.exit(code),
    (err) => {
      console.error(err.message);
      process.exit(1);
    }
  );
}
