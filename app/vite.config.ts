import { defineConfig, loadEnv, type Connect, type Plugin, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFile } from "node:fs/promises";
import { basename, resolve } from "node:path";

const DIGESTED = resolve(__dirname, "../data/digested");

// The app fetches the pipeline's digested JSON from /data/*.json at runtime (in
// production that path is the private S3 bucket behind the auth gate). Locally,
// serve it straight from data/digested so re-running `python3 data/digest.py`
// shows up on the next reload — no copy step, and nothing lands in dist/.
function serveDigested(): Plugin {
  const middleware: Connect.NextHandleFunction = async (req, res, next) => {
    const match = req.url?.match(/^\/data\/([^/?]+\.json)(\?.*)?$/);
    if (!match) return next();
    try {
      const body = await readFile(resolve(DIGESTED, basename(match[1])));
      res.setHeader("Content-Type", "application/json; charset=utf-8");
      res.setHeader("Cache-Control", "no-store");
      res.end(body);
    } catch {
      res.statusCode = 404;
      res.end();
    }
  };
  return {
    name: "serve-digested",
    configureServer: (server) => void server.middlewares.use(middleware),
    configurePreviewServer: (server) => void server.middlewares.use(middleware),
  };
}

// Relay: replace each graphql`…` tag with an import of the artifact relay-compiler
// wrote for it (src/__generated__/<Name>.graphql.ts). This is what babel-plugin-relay
// does; @vitejs/plugin-react 6 has no Babel step, so it is done here with a regex over
// the operation or fragment name. relay-compiler itself runs before dev/build/test.
function relayTags(): Plugin {
  const TAG = /graphql`\s*(?:query|mutation|subscription|fragment)\s+([A-Za-z_][\w]*)[\s\S]*?`/g;
  return {
    name: "relay-tags",
    enforce: "pre",
    transform(code, id) {
      if (!/\.tsx?$/.test(id) || id.includes("/__generated__/") || !code.includes("graphql`")) return null;
      const imports: string[] = [];
      const out = code.replace(TAG, (_, name: string) => {
        const local = `__relay_${name}`;
        imports.push(`import ${local} from "@/__generated__/${name}.graphql";`);
        return local;
      });
      return imports.length ? { code: `${imports.join("\n")}\n${out}`, map: null } : null;
    },
  };
}

// Dev/preview forward /api to the local ledger API (docker compose, 127.0.0.1:8787).
// The API demands the origin secret that CloudFront adds in production, so it is
// injected here, server-side, from the repo-root .env. loadEnv(..., "") is only
// called in this Node config: values without a VITE_ prefix never reach
// import.meta.env, so the secret can't end up in the bundle.
function apiProxy(mode: string): Record<string, ProxyOptions> {
  const env = loadEnv(mode, resolve(__dirname, ".."), "");
  const secret = process.env.FINANCE_API_ORIGIN_SECRET ?? env.FINANCE_API_ORIGIN_SECRET;
  return {
    "/api": {
      // FINANCE_API_URL points a worktree's dev server at its own API (default: the compose service).
      target: process.env.FINANCE_API_URL ?? env.FINANCE_API_URL ?? "http://127.0.0.1:8787",
      changeOrigin: true,
      headers: secret ? { "X-Origin-Secret": secret } : {},
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [relayTags(), react(), tailwindcss(), serveDigested()],
  server: { proxy: apiProxy(mode) },
  preview: { proxy: apiProxy(mode) },
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
}));
