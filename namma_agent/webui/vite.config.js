import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "/" (absolute) so assets resolve correctly on *nested* client routes too.
// With "./" a hard refresh on /projects/:id requests /projects/assets/… which the
// SPA fallback answers with index.html (not JS) → blank page. The app is always
// served over HTTP by FastAPI (uvicorn), incl. inside the pywebview window, and
// /assets is a StaticFiles mount, so absolute paths are correct everywhere.
export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
