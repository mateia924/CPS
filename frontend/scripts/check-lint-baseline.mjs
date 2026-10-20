// Block 8.2.1: `npm run lint` ran for the first time on 2026-10-20 and found
// 44 errors and 26 warnings (docs/reports/2026-10-20-block-8.2.1.md). The
// owner decides separately whether and when to clear that backlog. Until
// then CI runs eslint and fails on anything above the recorded baseline:
// a new rule, or one more finding of a rule in a file, than lint-baseline.json
// holds. A finding fixed lowers the count; `--update` rewrites the baseline
// (only to record a fix, or with a dated decision for a new finding).
//
// Usage: node scripts/check-lint-baseline.mjs ESLINT_JSON [--update]
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const [jsonPath, flag] = process.argv.slice(2);
const baselinePath = path.join(process.cwd(), "lint-baseline.json");
const results = JSON.parse(readFileSync(jsonPath, "utf8"));

const counts = {};
for (const file of results) {
  const rel = path.relative(process.cwd(), file.filePath);
  for (const m of file.messages) {
    const key = `${rel} ${m.severity === 2 ? "error" : "warn"} ${m.ruleId ?? "(directive)"}`;
    counts[key] = (counts[key] ?? 0) + 1;
  }
}
const total = (sev) => Object.entries(counts).filter(([k]) => k.split(" ")[1] === sev).reduce((s, [, v]) => s + v, 0);
console.log(`eslint: ${total("error")} errors, ${total("warn")} warnings in ${results.length} files`);

if (flag === "--update") {
  const sorted = Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(baselinePath, JSON.stringify(sorted, null, 2) + "\n");
  console.log(`baseline written: ${Object.keys(sorted).length} file/rule entries`);
  process.exit(0);
}

const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
const over = Object.entries(counts).filter(([k, v]) => v > (baseline[k] ?? 0));
for (const [k, v] of over) console.error(`ABOVE BASELINE: ${k} — ${v} (baseline ${baseline[k] ?? 0})`);
if (over.length) {
  console.error(`check-lint-baseline: ${over.length} file/rule count(s) above lint-baseline.json — fix the new finding(s).`);
  process.exit(1);
}
console.log("check-lint-baseline: nothing above the recorded baseline.");
