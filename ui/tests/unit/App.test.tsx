import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";

import { App } from "@/App";
import { stubMatchMedia } from "./media";

beforeEach(() => stubMatchMedia());
afterEach(cleanup);

it("mounts the app with a banner and a main landmark", () => {
  render(<App />);
  expect(screen.getByRole("banner")).toBeTruthy();
  expect(screen.getByRole("main")).toBeTruthy();
});
