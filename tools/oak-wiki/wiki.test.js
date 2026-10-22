// Tests for the local wiki server: `npm test` (or node --test tools/oak-wiki/wiki.test.js).
"use strict";

const assert = require("assert");
const http = require("http");
const test = require("node:test");
const { parseArgs, createServer, repoName } = require("./wiki");

function get(port, path) {
  return new Promise((resolve, reject) => {
    http.get({ host: "127.0.0.1", port, path }, (res) => {
      let body = "";
      res.on("data", (d) => (body += d));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body }));
    }).on("error", reject);
  });
}

function start() {
  const s = createServer();
  return new Promise((resolve) => s.server.listen(0, "127.0.0.1", () => resolve({ ...s, port: s.server.address().port })));
}

test("parseArgs reads --port and --no-open", () => {
  assert.deepStrictEqual(parseArgs([]), { port: 4410, open: true });
  assert.deepStrictEqual(parseArgs(["--port", "4500", "--no-open"]), { port: 4500, open: false });
  assert.strictEqual(parseArgs(["--port=4501"]).port, 4501);
  assert.throws(() => parseArgs(["--port", "abc"]), /--port needs a number/);
  assert.throws(() => parseArgs(["--bogus"]), /Unknown option/);
});

test("repoName is owner/name", () => {
  assert.match(repoName(), /^[^/]+\/[^/]+$/);
});

test("serves index.html with the reload script, and the site files", async () => {
  const s = await start();
  try {
    const index = await get(s.port, "/");
    assert.strictEqual(index.status, 200);
    assert.match(index.body, /<script src="\/__oak\/reload\.js"><\/script>\s*<\/body>/);
    assert.strictEqual(index.headers["cache-control"], "no-store");
    const app = await get(s.port, "/app.js");
    assert.strictEqual(app.status, 200);
    assert.match(app.headers["content-type"], /javascript/);
    const client = await get(s.port, "/__oak/reload.js");
    assert.match(client.body, /EventSource\("\/__oak\/events"\)/);
    assert.strictEqual((await get(s.port, "/nope.txt")).status, 404);
    assert.notStrictEqual((await get(s.port, "/%2e%2e/package.json")).status, 200);
  } finally {
    s.server.close();
  }
});

test("pushes events to open browsers over Server-Sent Events", async () => {
  const s = await start();
  try {
    const got = await new Promise((resolve, reject) => {
      http.get({ host: "127.0.0.1", port: s.port, path: "/__oak/events" }, (res) => {
        assert.match(res.headers["content-type"], /text\/event-stream/);
        let buf = "";
        res.on("data", (d) => {
          buf += d;
          if (buf.includes(": connected")) s.send("reload");
          if (buf.includes("event: reload")) {
            res.destroy();
            resolve(buf);
          }
        });
      }).on("error", reject);
    });
    assert.match(got, /event: reload\ndata: \{\}\n\n/);
  } finally {
    for (const res of s.clients) res.end();
    s.server.close();
  }
});
