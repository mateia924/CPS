// Block 8.2.1: `next lint` was removed in Next 16, so `npm run lint` had
// never run (it read "lint" as a project directory). This is the flat
// config create-next-app 16 generates, with Next's own ignores.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "e2e/test-results/**", "test-results/**"]),
]);
