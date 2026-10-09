import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppBar } from "../../src/features/shell/AppBar";
import { stubMatchMedia } from "./media";
import { choose } from "./menus";

beforeEach(() => {
  stubMatchMedia();
  document.cookie = "dsj-theme=; max-age=0; path=/";
  delete document.documentElement.dataset.theme;
});
afterEach(cleanup);

describe("the app bar", () => {
  it("carries the wordmark home on the library, and a way back on any other page", () => {
    const { rerender } = render(<AppBar />);
    expect(screen.getByRole("link", { name: "dsj" }).getAttribute("href")).toBe("/");
    rerender(<AppBar back />);
    expect(screen.getByRole("link", { name: "Library" }).getAttribute("href")).toBe("/");
  });

  it("is a banner on the blue field", () => {
    render(<AppBar>tools</AppBar>);
    expect(screen.getByRole("banner").className).toContain("bg-field");
  });

  it("keeps the colours choice in its settings menu, and keeps it in the cookie", async () => {
    render(<AppBar />);
    act(() => fireEvent.click(screen.getByRole("button", { name: "Settings" })));
    choose(await screen.findByRole("menuitemradio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.cookie).toContain("dsj-theme=dark");
  });
});
