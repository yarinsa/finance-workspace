// Per-tenant credentials and output for every headless scraper (docs/tenancy.md).
//
// The master tenant (FINANCE_TENANT_ID unset or the default id) behaves exactly as before:
// <repo>/.env and <repo>/data/<source>/raw. Any other tenant reads ONLY its own secrets file,
// ~/.finance-tenants/<tenant_id>.env (outside the repo, mode 0600 required), and writes to
// <repo>/data/tenants/<tenant_id>/<source>/raw. It never loads the repo .env: a missing
// credential must stop the run, not silently log in as another household.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const MASTER = '00000000-0000-4000-8000-000000000001';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function tenantId(env = process.env) {
  const id = env.FINANCE_TENANT_ID || MASTER;
  if (!UUID.test(id)) throw new Error('FINANCE_TENANT_ID must be a lower-case uuid');
  return id;
}

/** Load the credentials for this run's tenant into process.env. `dotenv` is the caller's module
 * (each scraper has its own node_modules; this shared file has none). */
export function loadEnv(repo, dotenv, env = process.env) {
  const id = tenantId(env);
  // The sync worker fetched this tenant's secrets from the vault into the environment already
  // (finance/vault.py). Another tenant then has no file to read and nothing to fall back to. The master
  // tenant still loads <repo>/.env, which never overrides what the vault supplied, so a partly
  // migrated household keeps working.
  if (env.FINANCE_VAULT_LOADED === '1' && id !== MASTER) return id;
  if (id === MASTER) {
    dotenv.config({ path: path.join(repo, '.env'), quiet: true });
    return id;
  }
  const file = path.join(os.homedir(), '.finance-tenants', `${id}.env`);
  if (!fs.existsSync(file)) throw new Error(`no credentials file for tenant ${id}: ${file}`);
  if ((fs.statSync(file).mode & 0o077) !== 0) throw new Error(`${file} must not be readable by others (chmod 600)`);
  dotenv.config({ path: file, quiet: true, override: true });
  return id;
}

/** `<source>/raw`, e.g. dataDir(repo, 'cal/raw'), in this tenant's tree. */
export function dataDir(repo, rel, env = process.env) {
  const id = tenantId(env);
  const base = env.FINANCE_DATA_DIR || path.join(repo, 'data');
  return id === MASTER ? path.join(base, rel) : path.join(base, 'tenants', id, rel);
}
