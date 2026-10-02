import { describe, expect, it } from "vitest";

import { columns } from "../../src/features/player/Waveform";

function peaks(...pairs: [number, number][]): Int8Array {
  return Int8Array.from(pairs.flat());
}

describe("columns", () => {
  it("gives each column the lowest min and highest max of the buckets in it", () => {
    const { lo, hi } = columns(peaks([-1, 1], [-5, 2], [-2, 9], [0, 0]), 2);
    expect(Array.from(lo)).toEqual([-5, -2]);
    expect(Array.from(hi)).toEqual([2, 9]);
  });

  it("stretches a short recording so every column has a bucket", () => {
    const { lo, hi } = columns(peaks([-3, 3], [-7, 7]), 4);
    expect(Array.from(lo)).toEqual([-3, -3, -7, -7]);
    expect(Array.from(hi)).toEqual([3, 3, 7, 7]);
  });

  it("keeps a loud moment that falls between column edges", () => {
    // 1,000 quiet buckets with one loud one, drawn into 7 columns.
    const pairs: [number, number][] = Array.from({ length: 1000 }, () => [-1, 1]);
    pairs[571] = [-120, 120];
    const { hi } = columns(peaks(...pairs), 7);
    expect(Math.max(...hi)).toBe(120);
  });

  it("draws nothing for an empty envelope", () => {
    expect(Array.from(columns(new Int8Array(0), 3).hi)).toEqual([0, 0, 0]);
  });
});
