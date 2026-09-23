const assert = require("node:assert/strict");
const http = require("node:http");
const { EventEmitter } = require("node:events");
const test = require("node:test");
const { availablePort, waitForBackend } = require("../src/backend-process");

async function serverFor(t, instance) {
  const server = http.createServer((req, res) => {
    assert.equal(req.url, "/api/runtime");
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ instance_id: instance }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return server.address().port;
}

function child() { return Object.assign(new EventEmitter(), { exitCode: null, signalCode: null }); }

test("elige otro puerto si el habitual está ocupado", async (t) => {
  const occupied = await serverFor(t, "old");
  assert.notEqual(await availablePort(occupied), occupied);
});

test("rechaza un backend antiguo aunque responda correctamente", async (t) => {
  const port = await serverFor(t, "old");
  await assert.rejects(waitForBackend(child(), `http://127.0.0.1:${port}`, "new", 200), /no respondió/);
});

test("acepta solamente el backend de esta instancia", async (t) => {
  const port = await serverFor(t, "new");
  await waitForBackend(child(), `http://127.0.0.1:${port}`, "new", 1000);
});

test("no acepta un proceso que ya terminó", async () => {
  const process = child();
  process.exitCode = 1;
  await assert.rejects(waitForBackend(process, "http://127.0.0.1:1", "new", 1000), /no está ejecutándose/);
});
