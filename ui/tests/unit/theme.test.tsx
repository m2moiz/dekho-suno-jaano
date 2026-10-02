import { readFileSync } from "node:fs";
import path from "node:path";

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { readTheme, saveTheme } from "../../src/features/theme/theme";
import { ThemeControl } from "../../src/features/theme/ThemeControl";

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

describe("the control", () => {
  it("offers exactly Light, Dark and System, and starts on System", () => {
    render(<ThemeControl />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Light", "Dark", "System"]);
    expect(screen.getByRole("button", { name: "System" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Dark" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("starts on the saved choice", () => {
    document.cookie = "dsj-theme=light; path=/";
    render(<ThemeControl />);
    expect(screen.getByRole("button", { name: "Light" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("saves and paints a choice at once", () => {
    render(<ThemeControl />);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Dark" }));
    });
    expect(readTheme()).toBe("dark");
    expect(root.dataset.theme).toBe("dark");
    expect(root.style.colorScheme).toBe("dark");
    expect(screen.getByRole("button", { name: "Dark" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("keeps the choice when the one already on is pressed again", () => {
    render(<ThemeControl />);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "System" }));
    });
    expect(screen.getByRole("button", { name: "System" }).getAttribute("aria-pressed")).toBe("true");
  });
});
