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
  refresh_max_age: 86400,
  default_tenant_id: "00000000-0000-4000-8000-000000000001",
  enforce_tenant_data: false,
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

/** POSTs to /oauth2/token answer with this (null -> 400); each call's form is recorded. */
let tokenReply = null;
const tokenCalls = [];

function loadHandler(config = CONFIG) {
  const tpl = fs.readFileSync(path.join(__dirname, "index.js.tftpl"), "utf8");
  const src = tpl.replace("${config_json}", () => JSON.stringify(config)).replace(/\$\$\{/g, "${");
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
    request(opts, cb) {
      const req = new EventEmitter();
      let body = "";
      req.write = (b) => (body += b);
      req.end = () =>
        setImmediate(() => {
          tokenCalls.push(Object.fromEntries(new URLSearchParams(body)));
          const res = new EventEmitter();
          res.statusCode = tokenReply ? 200 : 400;
          cb(res);
          res.emit("data", JSON.stringify(tokenReply ?? { error: "invalid_grant" }));
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

function event(uri, { cookie, host = CONFIG.site_domain, querystring = "" } = {}) {
  const headers = { host: [{ key: "Host", value: host }] };
  if (cookie) headers.cookie = [{ key: "Cookie", value: cookie }];
  return { Records: [{ cf: { request: { uri, querystring, headers } } }] };
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

const expired = () => `${CONFIG.cookie_name}=${makeToken({ exp: Math.floor(Date.now() / 1000) - 60 })}`;
const rt = `${CONFIG.cookie_name}_rt=refresh-abc`;

test("expired session + refresh cookie -> 307 back to the same URL with a new session", async () => {
  tokenReply = { id_token: makeToken() };
  tokenCalls.length = 0;
  const res = await loadHandler()(event("/data/cashflow.json", { cookie: `${expired()}; ${rt}`, querystring: "v=1" }));
  assert.equal(res.status, "307");
  assert.equal(res.headers.location[0].value, "/data/cashflow.json?v=1");
  assert.match(res.headers["set-cookie"][0].value, /^plangram_session=ey.*HttpOnly; Secure; SameSite=Lax; Max-Age=\d+$/);
  assert.deepEqual(tokenCalls[0], { grant_type: "refresh_token", client_id: CONFIG.client_id, refresh_token: "refresh-abc" });
});

test("/api with an expired session renews too (307 keeps the method)", async () => {
  tokenReply = { id_token: makeToken() };
  const res = await loadHandler()(event("/api/sync/events", { cookie: `${expired()}; ${rt}` }));
  assert.equal(res.status, "307");
});

test("refresh rejected -> login redirect / 401 as before", async () => {
  tokenReply = null;
  const handler = loadHandler();
  assert.equal((await handler(event("/syncs", { cookie: `${expired()}; ${rt}` }))).status, "302");
  assert.equal((await handler(event("/api/health", { cookie: rt }))).status, "401");
});

test("a refreshed token that fails verification is not accepted", async () => {
  tokenReply = { id_token: makeToken({ aud: "someone-else" }) };
  const res = await loadHandler()(event("/syncs", { cookie: `${expired()}; ${rt}` }));
  assert.equal(res.status, "302");
});

test("/_logout clears both cookies", async () => {
  const res = await loadHandler()(event("/_logout", { cookie: `${session()}; ${rt}` }));
  const set = res.headers["set-cookie"].map((c) => c.value);
  assert.ok(set.some((v) => v.startsWith("plangram_session=;") && v.endsWith("Max-Age=0")));
  assert.ok(set.some((v) => v.startsWith("plangram_session_rt=;") && v.endsWith("Max-Age=0")));
});

// --- tenant data ------------------------------------------------------------------

const TENANT_A = "aaaaaaaa-0000-4000-8000-00000000000a";
const TENANT_B = "bbbbbbbb-0000-4000-8000-00000000000b";
const asMember = (...ids) => `${CONFIG.cookie_name}=${makeToken({ "cognito:groups": ids.map((i) => `tenant-${i}`) })}`;

test("a tenant's data needs that tenant's group", async () => {
  const h = loadHandler();
  const own = await h(event(`/data/t/${TENANT_A}/transactions.json`, { cookie: asMember(TENANT_A) }));
  assert.equal(own.status, undefined);
  assert.equal(own.uri, `/data/t/${TENANT_A}/transactions.json`);
  const other = await h(event(`/data/t/${TENANT_B}/transactions.json`, { cookie: asMember(TENANT_A) }));
  assert.equal(other.status, "403");
  const none = await h(event(`/data/t/${TENANT_A}/snapshot.json`, { cookie: session() }));
  assert.equal(none.status, "403");
});

test("a member of two tenants reads both", async () => {
  const h = loadHandler();
  for (const t of [TENANT_A, TENANT_B]) {
    const r = await h(event(`/data/t/${t}/cashflow.json`, { cookie: asMember(TENANT_A, TENANT_B) }));
    assert.equal(r.status, undefined);
  }
});

test("path tricks do not reach another tenant's files", async () => {
  const h = loadHandler();
  for (const uri of [`/data/t/${TENANT_B.toUpperCase()}/x.json`, `/data/t/${TENANT_A}/../${TENANT_B}/x.json`,
                     `/data/t/${TENANT_A}x/x.json`, `/data/t//x.json`]) {
    const r = await h(event(uri, { cookie: asMember(TENANT_A) }));
    assert.equal(r.status, "403", uri);
  }
});

test("master tenant data is open to any session until enforcement is on, then needs its group", async () => {
  const open = await loadHandler()(event("/data/snapshot.json", { cookie: session() }));
  assert.equal(open.status, undefined);
  const h = loadHandler({ ...CONFIG, enforce_tenant_data: true });
  assert.equal((await h(event("/data/snapshot.json", { cookie: asMember(TENANT_A) }))).status, "403");
  const ok = await h(event("/data/snapshot.json", { cookie: asMember(CONFIG.default_tenant_id) }));
  assert.equal(ok.status, undefined);
});
