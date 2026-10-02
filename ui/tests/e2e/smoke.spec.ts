import { expect, test } from "@playwright/test";

function pageUrl(): string {
  const url = process.env["DSJ_UI_URL"];
  if (url === undefined) {
    throw new Error("DSJ_UI_URL is unset: run through `just ui-e2e`, whose global setup starts dsj ui");
  }
  return url;
}

test("the page dsj ui serves loads and mounts the app", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  const reply = await page.goto(pageUrl());

  expect(reply?.status()).toBe(200);
  await expect(page.getByRole("main")).toBeVisible();
  expect(errors).toEqual([]);
});
