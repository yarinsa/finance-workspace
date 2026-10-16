"use strict";
// Run: node --test infra/edge-auth/edge-auth.test.js  (Node >= 20, no dependencies)
//
// Renders index.js.tftpl the way Terraform's templatefile() does (substitute
// ${config_json}, unescape $${), loads it with a stubbed `https` serving a
// generated JWKS, and drives the handler.

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const Module = require("module");
const { EventEmitter } = require("events");

const CONFIG = {
  region: "us-east-1",
  user_pool_id: "us-east-1_TEST",
  client_id: "client123",
  client_secret: "secret",
  hosted_domain: "auth.example.test",
  site_domain: "app.example.test",
  cookie_name: "plangram_session",
};
const ISSUER = `https://cognito-idp.${CONFIG.region}.amazonaws.com/${CONFIG.user_pool_id}`;

const { publicKey, privateKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "k1", alg: "RS256", use: "sig" };

const b64u = (b) => Buffer.from(b).toString("base64url");
function makeToken(claims = {}) {
  const head = b64u(JSON.stringify({ alg: "RS256", kid: "k1" }));
  const body = b64u(
    JSON.stringify({
      iss: ISSUER,
      aud: CONFIG.client_id,
      token_use: "id",
      exp: Math.floor(Date.now() / 1000) + 600,
      ...claims,
    })
  );
  const sig = crypto.sign("RSA-SHA256", Buffer.from(`${head}.${body}`), privateKey);
  return `${head}.${body}.${b64u(sig)}`;
}

function loadHandler() {
  const tpl = fs.readFileSync(path.join(__dirname, "index.js.tftpl"), "utf8");
  const src = tpl.replace("${config_json}", () => JSON.stringify(CONFIG)).replace(/\$\$\{/g, "${");
  const fakeHttps = {
    get(url, cb) {
      assert.ok(url.endsWith("/.well-known/jwks.json"), `unexpected GET ${url}`);
      const res = new EventEmitter();
      res.statusCode = 200;
      const req = new EventEmitter();
      setImmediate(() => {
        cb(res);
        res.emit("data", JSON.stringify({ keys: [jwk] }));
        res.emit("end");
      });
      return req;
    },
  };
  const m = { exports: {} };
  const realRequire = (id) => (id === "https" ? fakeHttps : require(id));
  new Function("exports", "require", "module", src)(m.exports, realRequire, m);
  return m.exports.handler;
}

function event(uri, { cookie, host = CONFIG.site_domain } = {}) {
  const headers = { host: [{ key: "Host", value: host }] };
  if (cookie) headers.cookie = [{ key: "Cookie", value: cookie }];
  return { Records: [{ cf: { request: { uri, querystring: "", headers } } }] };
}
const session = () => `${CONFIG.cookie_name}=${makeToken()}`;

test("template renders to valid JS", () => {
  assert.equal(typeof loadHandler(), "function");
});

test("/api without a session -> 401 JSON, not a login redirect", async () => {
  const r = await loadHandler()(event("/api/transactions"));
  assert.equal(r.status, "401");
  assert.equal(r.headers["content-type"][0].value, "application/json");
  assert.deepEqual(JSON.parse(r.body), { error: "unauthenticated" });
  assert.equal(r.headers.location, undefined);
});

test("/api with an invalid session -> 401 JSON", async () => {
  const expired = makeToken({ exp: 1 });
  const r = await loadHandler()(event("/api/health", { cookie: `${CONFIG.cookie_name}=${expired}` }));
  assert.equal(r.status, "401");
  assert.deepEqual(JSON.parse(r.body), { error: "unauthenticated" });
  const garbage = await loadHandler()(event("/api/health", { cookie: `${CONFIG.cookie_name}=nope` }));
  assert.equal(garbage.status, "401");
});

test("/api with a valid session passes through unchanged", async () => {
  const r = await loadHandler()(event("/api/transactions", { cookie: session() }));
  assert.equal(r.uri, "/api/transactions");
  assert.equal(r.status, undefined);
});

test("non-API without a session still redirects to login", async () => {
  const r = await loadHandler()(event("/spending"));
  assert.equal(r.status, "302");
  assert.match(r.headers.location[0].value, /^https:\/\/auth\.example\.test\/login\?/);
});

test("SPA rewrite: extension-less routes -> /index.html", async () => {
  for (const uri of ["/", "/spending", "/runway/details", "/a.b/route"]) {
    const r = await loadHandler()(event(uri, { cookie: session() }));
    assert.equal(r.uri, "/index.html", uri);
  }
});

test("SPA rewrite leaves files with an extension alone", async () => {
  for (const uri of ["/data/cashflow.json", "/assets/app-abc123.js", "/index.html", "/favicon.svg"]) {
    const r = await loadHandler()(event(uri, { cookie: session() }));
    assert.equal(r.uri, uri);
  }
});

test("/_logout and /_passkey keep their own behavior", async () => {
  const out = await loadHandler()(event("/_logout"));
  assert.equal(out.status, "302");
  assert.match(out.headers["set-cookie"][0].value, /Max-Age=0/);
  const pk = await loadHandler()(event("/_passkey", { cookie: session() }));
  assert.equal(pk.status, "302");
  assert.match(pk.headers.location[0].value, /\/passkeys\/add\?/);
  const pkAnon = await loadHandler()(event("/_passkey"));
  assert.match(pkAnon.headers.location[0].value, /\/login\?/);
});
