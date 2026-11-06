// ESLint over the unit tests only (#289). The one thing it holds today is that
// every vitest test asserts something: a test with no `expect` passes whatever
// the code does, which is the covered-but-unasserted failure the gate exists
// to remove. tsc holds the types; ruff's counterpart rules for the Python side
// are in pyproject.toml. Widen the scope deliberately, one rule at a time.
import { defineConfig } from "eslint/config";
import vitest from "@vitest/eslint-plugin";
import tseslint from "typescript-eslint";

export default defineConfig([
  {
    files: ["tests/unit/**/*.{ts,tsx}"],
    plugins: { vitest },
    languageOptions: {
      parser: tseslint.parser,
      globals: vitest.environments.env.globals,
    },
    rules: {
      "vitest/expect-expect": [
        "error",
        // Playwright-style and testing-library helpers that assert by throwing.
        // `check` in splice.test.ts asserts inside; the others assert by throwing.
        { assertFunctionNames: ["expect", "expectTypeOf", "assert*", "check", "screen.getBy*", "screen.findBy*"] },
      ],
      "vitest/no-disabled-tests": "warn",
      "vitest/no-focused-tests": "error",
      "vitest/no-identical-title": "error",
      "vitest/valid-expect": "error",
    },
  },
]);
