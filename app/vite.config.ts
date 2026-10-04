import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

// The app renders the pipeline's digested JSON. We alias `@digested` to the
// repo's data/digested so re-running `python3 data/digest.py` is picked up on
// the next dev reload — no copy step.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@digested": resolve(__dirname, "../data/digested"),
      "@": resolve(__dirname, "src"),
    },
  },
  server: {
    fs: {
      // allow importing JSON from the parent data/ dir
      allow: [resolve(__dirname, ".."), resolve(__dirname)],
    },
  },
});
