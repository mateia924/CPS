#!/usr/bin/env node
// Sprint 6.0.1-A (BRAND.md §5.5): computes WCAG contrast ratios for every
// text/background pair BRAND.md §2.4/§2.5 defines, straight from the
// tokens themselves — no manual re-typing of hex values that could drift
// from tokens.css. Fails (non-zero exit) if any pair drops under AA.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const tokensPath = path.join(__dirname, "..", "src", "styles", "tokens.css");
const css = readFileSync(tokensPath, "utf8");

// Light-mode :root and the :root[data-theme="dark"] override block —
// dark mode has no user-facing toggle yet (item A.8), but tokens.css
// defines it fully, so both palettes are verified against AA.
const [lightBlock, darkOverrideBlock] = css.split(':root[data-theme="dark"]');

function readVars(block) {
  const vars = {};
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
    vars[m[1]] = m[2].trim();
  }
  return vars;
}

const lightVars = readVars(lightBlock);
// Dark mode only overrides a subset of tokens — anything it doesn't
// redefine (e.g. --status-*, --radius-*) falls back to the light value,
// matching how the cascade actually resolves `:root[data-theme="dark"]`
// in the browser (it only overrides what it declares).
const darkVars = { ...lightVars, ...readVars(darkOverrideBlock) };

function resolve(value, vars, seen = new Set()) {
  const varRef = value.match(/^var\(--([a-z0-9-]+)\)$/);
  if (!varRef) return value;
  const name = varRef[1];
  if (seen.has(name)) throw new Error(`circular token reference: ${name}`);
  seen.add(name);
  return resolve(vars[name], vars, seen);
}

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const int = parseInt(full, 16);
  return [(int >> 16) & 255, (int >> 8) & 255, int & 255];
}

function relativeLuminance([r, g, b]) {
  const [rs, gs, bs] = [r, g, b].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

function contrastRatio(hexA, hexB) {
  const lA = relativeLuminance(hexToRgb(hexA));
  const lB = relativeLuminance(hexToRgb(hexB));
  const [lighter, darker] = lA > lB ? [lA, lB] : [lB, lA];
  return (lighter + 0.05) / (darker + 0.05);
}

// [label, foreground token expression, background token expression]
const LIGHT_PAIRS = [
  ["success on success-bg (§2.4)", "var(--success)", "var(--success-bg)"],
  ["warning on warning-bg (§2.4)", "var(--warning)", "var(--warning-bg)"],
  ["danger on danger-bg (§2.4)", "var(--danger)", "var(--danger-bg)"],
  ["info on info-bg (§2.4)", "var(--info)", "var(--info-bg)"],
  ["status-draft (§2.5)", "var(--status-draft)", "var(--status-draft-bg)"],
  ["status-pending (§2.5)", "var(--status-pending)", "var(--status-pending-bg)"],
  ["status-approved (§2.5)", "var(--status-approved)", "var(--status-approved-bg)"],
  ["status-posted (§2.5)", "var(--status-posted)", "var(--status-posted-bg)"],
  ["status-reversed (§2.5)", "var(--status-reversed)", "var(--status-reversed-bg)"],
  ["status-void (§2.5)", "var(--status-void)", "var(--status-void-bg)"],
  ["color-on-primary on color-primary", "var(--color-on-primary)", "var(--color-primary)"],
  ["ink on ground", "var(--ink)", "var(--ground)"],
  ["ink on surface", "var(--ink)", "var(--surface)"],
  ["muted on surface", "var(--muted)", "var(--surface)"],
  ["color-link on surface", "var(--color-link)", "var(--surface)"],
  ["sidebar-text on sidebar-bg", "var(--sidebar-text)", "var(--sidebar-bg)"],
];

// Dark-mode subset — no toggle in the UI yet (item A.8), but the palette
// is fully defined in tokens.css and must hold up to AA on its own.
const DARK_PAIRS = [
  ["[dark] success on success-bg", "var(--success)", "var(--success-bg)"],
  ["[dark] warning on warning-bg", "var(--warning)", "var(--warning-bg)"],
  ["[dark] danger on danger-bg", "var(--danger)", "var(--danger-bg)"],
  ["[dark] info on info-bg", "var(--info)", "var(--info-bg)"],
  ["[dark] ink on ground", "var(--ink)", "var(--ground)"],
  ["[dark] ink on surface", "var(--ink)", "var(--surface)"],
  ["[dark] muted on surface", "var(--muted)", "var(--surface)"],
  ["[dark] color-link on surface", "var(--color-link)", "var(--surface)"],
  ["[dark] sidebar-text on sidebar-bg", "var(--sidebar-text)", "var(--sidebar-bg)"],
];

const MIN_RATIO = 4.5;
let failed = false;

function runChecks(pairs, vars) {
  for (const [label, fg, bg] of pairs) {
    const fgHex = resolve(fg, vars);
    const bgHex = resolve(bg, vars);
    const ratio = contrastRatio(fgHex, bgHex);
    const ok = ratio >= MIN_RATIO;
    if (!ok) failed = true;
    console.log(
      `${ok ? "PASS" : "FAIL"}  ${label}: ${ratio.toFixed(2)}:1 (${fgHex} on ${bgHex}, need >= ${MIN_RATIO}:1)`
    );
  }
}

runChecks(LIGHT_PAIRS, lightVars);
runChecks(DARK_PAIRS, darkVars);

if (failed) {
  console.error("\ncontrast-check: one or more pairs fail WCAG AA.");
  process.exit(1);
}
console.log("\ncontrast-check: all pairs pass WCAG AA.");
