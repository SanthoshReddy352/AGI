// Render every diagrams/src/*.mmd to a 4x-scale PNG in public/assets/diagrams,
// using the Vellum-themed mermaid config and a warm baked background (so the
// images stay legible under both the light and dark docs themes).
import { execFileSync } from "node:child_process";
import { readdirSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const base = join(here, "..");
const srcDir = join(base, "diagrams", "src");
const outDir = join(base, "public", "assets", "diagrams");
const cfg = join(base, "diagrams", "mermaid.config.json");
const isWin = process.platform === "win32";
const mmdc = join(base, "node_modules", ".bin", isWin ? "mmdc.cmd" : "mmdc");

mkdirSync(outDir, { recursive: true });
const files = readdirSync(srcDir).filter((f) => f.endsWith(".mmd")).sort();
console.log(`Rendering ${files.length} diagrams at 4x...`);

for (const f of files) {
  const name = f.replace(/\.mmd$/, "");
  process.stdout.write(`  • ${name} ... `);
  execFileSync(
    mmdc,
    ["-i", join(srcDir, f), "-o", join(outDir, `${name}.png`), "-c", cfg, "-b", "#F7F4EF", "-s", "4"],
    { stdio: ["ignore", "ignore", "inherit"], shell: isWin }
  );
  console.log("done");
}
console.log("All diagrams rendered to public/assets/diagrams.");
