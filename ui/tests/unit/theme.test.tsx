import { readFileSync } from "node:fs";
import path from "node:path";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { readTheme, saveTheme } from "../../src/features/theme/theme";

// The inline script at the top of ui/index.html, run exactly as the page runs it.
const page = readFileSync(path.resolve(import.meta.dirname, "../../index.html"), "utf8");
const headScript = /<script>([\s\S]*?)<\/script>/.exec(page)?.[1] ?? "";

function runHeadScript() {
  new Function(headScript)();
}

function clearCookies() {
  for (const pair of document.cookie.split("; ")) {
    const name = pair.split("=")[0];
    if (name) document.cookie = `${name}=; max-age=0; path=/`;
  }
}

const root = document.documentElement;

beforeEach(() => {
  clearCookies();
  delete root.dataset.theme;
  root.style.colorScheme = "";
});

afterEach(cleanup);

describe("the script in the page's head", () => {
  it("is there, and reads the cookie", () => {
    expect(headScript).toContain("dsj-theme");
    expect(headScript).toContain("document.cookie");
    expect(headScript).not.toContain("localStorage");
  });

  it("with nothing saved, follows the Mac", () => {
    runHeadScript();
    expect(root.dataset.theme).toBe("system");
    expect(root.style.colorScheme).toBe("light dark");
  });

  it.each(["light", "dark"] as const)("with %s saved, pins it", (theme) => {
    document.cookie = `dsj-theme=${theme}; path=/`;
    runHeadScript();
    expect(root.dataset.theme).toBe(theme);
    expect(root.style.colorScheme).toBe(theme);
  });

  it("treats a value it does not know as nothing saved", () => {
    document.cookie = "dsj-theme=sepia; path=/";
    runHeadScript();
    expect(root.dataset.theme).toBe("system");
  });

  it("is not fooled by another cookie whose name ends the same way", () => {
    document.cookie = "not-dsj-theme=dark; path=/";
    runHeadScript();
    expect(root.dataset.theme).toBe("system");
  });
});

describe("saving a choice", () => {
  it("writes the cookie the head script reads on the next launch", () => {
    saveTheme("dark");
    expect(document.cookie).toContain("dsj-theme=dark");
    // A new launch: the page's state is gone, the cookie is not.
    delete root.dataset.theme;
    root.style.colorScheme = "";
    runHeadScript();
    expect(root.dataset.theme).toBe("dark");
    expect(readTheme()).toBe("dark");
  });
});
