// Stub build: fails if any source file contains "BUILD-BREAK".
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

let broken = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (readFileSync(p, "utf8").includes("BUILD-BREAK")) broken.push(p);
  }
})("src");
if (broken.length) { console.error("build failed: " + broken.join(", ")); process.exit(1); }
console.log("build ok");
