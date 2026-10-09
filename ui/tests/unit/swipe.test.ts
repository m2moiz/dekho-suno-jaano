import { describe, expect, it } from "vitest";

import { SWIPE_PX, swipeOf } from "../../src/features/review/swipe";

describe("swipeOf", () => {
  it("is a mostly sideways drag of at least SWIPE_PX, named by its direction", () => {
    expect(swipeOf(-SWIPE_PX, 0)).toBe("left");
    expect(swipeOf(120, 30)).toBe("right");
  });

  it("is nothing for a short drag, a steep one, or a scroll", () => {
    expect(swipeOf(-40, 0)).toBeNull();
    expect(swipeOf(-120, 90)).toBeNull();
    expect(swipeOf(5, 300)).toBeNull();
  });
});
