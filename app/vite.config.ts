import { defineConfig, type Connect, type Plugin } from "vite";
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

export default defineConfig({
  plugins: [react(), tailwindcss(), serveDigested()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
});
