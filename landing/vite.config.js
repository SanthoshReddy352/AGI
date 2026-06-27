import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Marketing site for Namma Agent. Multi-page SPA (landing + docs) on the
// Vellum design system. Base is relative so the built bundle can be served
// from any sub-path.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5174 },
  build: { outDir: "dist" },
});
