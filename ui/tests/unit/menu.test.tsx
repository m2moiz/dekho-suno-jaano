import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MoreMenu } from "../../src/features/transcript/MoreMenu";
import { stubMatchMedia } from "./media";
import { choose } from "./menus";

beforeEach(() => stubMatchMedia());
afterEach(cleanup);

describe("the reader's menu", () => {
  it("badges Bleep only when the word lists found something", async () => {
    const { rerender } = render(<MoreMenu matchCount={0} onBleep={() => undefined} timingWord={null} onTiming={() => undefined} />);
    act(() => fireEvent.click(screen.getByRole("button", { name: "More" })));
    expect((await screen.findByRole("menuitem", { name: /^Bleep/ })).textContent).toBe("Bleep");
    rerender(<MoreMenu matchCount={3} onBleep={() => undefined} timingWord={null} onTiming={() => undefined} />);
    expect(screen.getByRole("menuitem", { name: /^Bleep/ }).textContent).toContain("3");
  });

  it("offers Timing only for one selected word, and opens the drawer on Bleep", async () => {
    const opened: string[] = [];
    render(<MoreMenu matchCount={0} onBleep={() => opened.push("bleep")} timingWord={4} onTiming={(w) => opened.push(`timing ${w}`)} />);
    act(() => fireEvent.click(screen.getByRole("button", { name: "More" })));
    choose(await screen.findByRole("menuitem", { name: /^Timing/ }));
    act(() => fireEvent.click(screen.getByRole("button", { name: "More" })));
    choose(await screen.findByRole("menuitem", { name: /^Bleep/ }));
    expect(opened).toEqual(["timing 4", "bleep"]);
  });
});
