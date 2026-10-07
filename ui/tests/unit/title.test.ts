// A recording's readable title (Hashiya spec, Library: "default from the
// file's timestamp, e.g. 'Sat 20 Sep, 9:42 am', else the filename").
import { describe, expect, it } from "vitest";

import { displayTitle, stampOf } from "../../src/features/library/title";

// 7 Oct 2025: the same year as most stamps below, so they print without one.
const NOW = new Date(2025, 9, 7, 12, 0);

describe("displayTitle", () => {
  it.each([
    ["Screen Recording 2025-09-20 at 9.42.00 AM.mov", "Sat 20 Sep, 9:42 am"],
    ["Screen Recording 2025-09-20 at 12.10.00 AM.mov", "Sat 20 Sep, 12:10 am"],
    ["20250920_094234.m4a", "Sat 20 Sep, 9:42 am"],
    // The phone recorder the owner's library mostly holds: date and time joined by a hyphen.
    ["recording-20250920-094234.m4a", "Sat 20 Sep, 9:42 am"],
    ["recording-20250920-094234_07m00-17m00.m4a", "Sat 20 Sep, 9:42 am"],
    ["2025-09-20 21.05.10.m4a", "Sat 20 Sep, 9:05 pm"],
    ["Recording 2024-03-05T21-05.wav", "Tue 5 Mar 2024, 9:05 pm"],
    ["standup.wav", "standup.wav"],
  ])("%s reads as %s", (name, title) => {
    expect(displayTitle({ title: null, path: `/Users/me/Recordings/${name}` }, NOW)).toBe(title);
  });

  it("prefers a title a person gave it", () => {
    expect(displayTitle({ title: "Sunday call", path: "/r/20250920_094234.m4a" }, NOW)).toBe("Sunday call");
  });
});

describe("stampOf", () => {
  it.each(["20251340_101010.m4a", "2025-02-30 10.00.m4a", "2025-09-20 at 13.00.00 PM.mov", "notes 2025.txt"])(
    "finds no date in %s",
    (name) => {
      expect(stampOf(name)).toBeNull();
    },
  );
});
