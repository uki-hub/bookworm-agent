// Toy linter: every line containing "LINT-BAD" is an error; "console.log" is an error too.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

let errors = 0;
function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(ts|tsx)$/.test(name)) {
      const lines = readFileSync(p, "utf8").split(/\r?\n/);
      const hits = lines.flatMap((l, i) => (/LINT-BAD|console\.log/.test(l) ? [`  ${i + 1}:1  error  forbidden pattern  no-bad`] : []));
      if (hits.length) { console.log("\n" + p); hits.forEach((h) => console.log(h)); errors += hits.length; }
    }
  }
}
walk("src");
console.log(errors ? `\n✖ ${errors} problems (${errors} errors, 0 warnings)` : "lint ok");
process.exit(errors ? 1 : 0);
