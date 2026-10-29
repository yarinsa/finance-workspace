// Run: node --test scrapers/tenant.test.mjs   (needs scrapers/discount/node_modules for dotenv)
import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { MASTER, dataDir, tenantId } from './tenant.mjs';

const A = 'aaaaaaaa-0000-4000-8000-00000000000a';

test('the master tenant keeps data/<source>/raw', () => {
  assert.equal(tenantId({}), MASTER);
  assert.equal(dataDir('/repo', 'cal/raw', {}), '/repo/data/cal/raw');
});

test('another tenant writes under data/tenants/<id>', () => {
  assert.equal(dataDir('/repo', 'cal/raw', { FINANCE_TENANT_ID: A }), `/repo/data/tenants/${A}/cal/raw`);
});

test('a tenant id that is not a uuid is refused (it becomes a path)', () => {
  assert.throws(() => tenantId({ FINANCE_TENANT_ID: '../../etc' }));
  assert.throws(() => dataDir('/repo', 'cal/raw', { FINANCE_TENANT_ID: 'A/../B' }));
});

import { loadEnv } from './tenant.mjs';

function fakeDotenv(calls) {
  return { config: (o) => { calls.push(o); return {}; } };
}

test('the master tenant loads <repo>/.env as before', () => {
  const calls = [];
  loadEnv('/repo', fakeDotenv(calls), {});
  assert.deepEqual(calls, [{ path: '/repo/.env', quiet: true }]);
});

test('another tenant never loads the repo .env and needs its own 0600 file', () => {
  const calls = [];
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'tenant-'));
  const prev = process.env.HOME; process.env.HOME = home;
  try {
    const env = { FINANCE_TENANT_ID: A };
    assert.throws(() => loadEnv('/repo', fakeDotenv(calls), env), /no credentials file/);
    const dir = path.join(home, '.finance-tenants'); fs.mkdirSync(dir);
    const file = path.join(dir, `${A}.env`); fs.writeFileSync(file, 'CAL_USERNAME=x\n', { mode: 0o644 }); fs.chmodSync(file, 0o644);
    assert.throws(() => loadEnv('/repo', fakeDotenv(calls), env), /must not be readable/);
    fs.chmodSync(file, 0o600);
    loadEnv('/repo', fakeDotenv(calls), env);
    assert.deepEqual(calls, [{ path: file, quiet: true, override: true }]);
    assert.ok(!calls.some((c) => c.path === '/repo/.env'));
  } finally { process.env.HOME = prev; }
});
