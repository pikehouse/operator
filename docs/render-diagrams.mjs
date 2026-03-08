import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { renderMermaid } from "beautiful-mermaid";

const DIAGRAMS_DIR = join(import.meta.dirname, "diagrams");

const files = (await readdir(DIAGRAMS_DIR)).filter((f) => f.endsWith(".mmd"));

for (const file of files) {
  const src = await readFile(join(DIAGRAMS_DIR, file), "utf-8");
  const svg = await renderMermaid(src);
  const out = join(DIAGRAMS_DIR, file.replace(".mmd", ".svg"));
  await writeFile(out, svg);
  console.log(`${file} → ${file.replace(".mmd", ".svg")}`);
}
