import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { App } from "@/App";

afterEach(cleanup);

it("mounts the app with a main landmark", () => {
  render(<App />);
  expect(screen.getByRole("main")).toBeTruthy();
});
