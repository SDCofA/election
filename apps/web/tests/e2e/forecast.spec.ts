import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const state = { value: 0 };
    Object.defineProperty(window, "__elexionLcp", { value: state, configurable: true });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) state.value = Math.max(state.value, entry.startTime);
    }).observe({ type: "largest-contentful-paint", buffered: true });
  });
});

test("withheld forecast page meets automated WCAG AA", async ({ page }) => {
  await page.goto("/elections/de-next-bundestag");
  await expect(page.getByRole("heading", { name: /Germany/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: /forecast withheld/i })).toBeVisible();
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);
  await expect(page.locator(".parliament-hemicycle")).toHaveCount(0);

  const violations = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(violations.violations).toEqual([]);

});

test("mobile layout has no viewport overflow and touch targets meet WCAG 2.2 minimum", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "mobile-only contract");
  await page.goto("/elections/de-next-bundestag");
  const geometry = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width);

  const targets = page.locator("a, button, input, select, textarea");
  for (let index = 0; index < await targets.count(); index += 1) {
    const target = targets.nth(index);
    if (!(await target.isVisible())) continue;
    const box = await target.boundingBox();
    expect(box, `interactive target ${index} has no box`).not.toBeNull();
    const markup = await target.evaluate((element) => element.outerHTML);
    expect(Math.min(box!.width, box!.height), `interactive target ${index} is too small: ${markup}`).toBeGreaterThanOrEqual(24);
  }
});

test("logical layout remains usable in right-to-left locales", async ({ page }) => {
  await page.goto("/elections/de-next-bundestag");
  await page.evaluate(() => {
    document.documentElement.lang = "ar";
    document.documentElement.dir = "rtl";
  });
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  const geometry = await page.evaluate(() => ({
    direction: getComputedStyle(document.body).direction,
    width: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth
  }));
  expect(geometry.direction).toBe("rtl");
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width);
});

test("parliament projection is absent while evidence is grade D", async ({ page }) => {
  await page.goto("/elections/de-next-bundestag");
  await expect(page.locator(".parliament-hemicycle")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /forecast withheld/i })).toBeVisible();
});

test("Brazil withholds grade-D probabilities", async ({ page }) => {
  await page.goto("/elections/br-2026-president");
  await expect(page.getByRole("heading", { name: /Brazil/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: /forecast withheld/i })).toBeVisible();
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);
});

test("directory lists sourced status records for only the 19 G20 countries", async ({ page }) => {
  await page.goto("/calendar");
  await expect(page.getByRole("heading", { name: "G20 countries only." })).toBeVisible();
  await expect(page.locator(".calendar-directory-grid > *")).toHaveCount(19);
  await expect(page.locator(".calendar-directory-grid .flag-icon img")).toHaveCount(19);
  await expect(page.locator(".calendar-directory-grid .flag-emoji")).toHaveCount(0);
  await expect(page.getByText("Egypt", { exact: true })).toHaveCount(0);
  await expect(page.getByText("European Union", { exact: true })).toHaveCount(0);
  await expect(page.getByText("African Union", { exact: true })).toHaveCount(0);
  await page.getByRole("searchbox", { name: "SEARCH G20 COUNTRIES" }).fill("Argentina");
  const argentina = page.getByRole("link", { name: /Argentina/ });
  await expect(argentina).toContainText("2029");
  await argentina.click();
  await expect(page.getByRole("heading", { name: /Argentina/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: /forecast withheld/i })).toBeVisible();
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);
  const violations = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(violations.violations).toEqual([]);
});

test("country-specific grade-D models are withheld while calendar-only systems remain", async ({ page }) => {
  await page.goto("/elections/in-2029-lok-sabha");
  await expect(page.getByRole("heading", { name: /India/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: /forecast withheld/i })).toBeVisible();
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);

  await page.goto("/elections/mx-2030-president");
  await expect(page.getByRole("heading", { name: /Mexico/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: /forecast withheld/i })).toBeVisible();
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);

  await page.goto("/elections/sa-national-election-status");
  await expect(page.getByRole("heading", { name: /Saudi Arabia/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Forecast unavailable" })).toBeVisible();
  await expect(page.getByText(/no scheduled national popular election/i)).toBeVisible();
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);
});

test("Türkiye withholds grade-D probabilities and conditional matchups", async ({ page }) => {
  await page.goto("/elections/tr-next-president");
  await expect(page.getByRole("heading", { name: /Türkiye/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: /forecast withheld/i })).toBeVisible();
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);
  await expect(page.getByText("CONDITIONAL MATCHUPS")).toHaveCount(0);
});

test("U.S. grade-D model is withheld pending source-vintage evidence", async ({ page }) => {
  await page.goto("/elections/us-2028-president");
  await expect(page.getByRole("heading", { name: /United States/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("heading", { name: /forecast withheld/i })).toBeVisible();
  await expect(page.getByText(/source-vintage (feature snapshot|inputs)/)).toBeVisible();
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);
});

test("route-specific API outage never substitutes another election", async ({ page }) => {
  await page.route("**/v1/**", (route) => route.abort());
  await page.goto("/elections/de-next-bundestag");
  await expect(page.getByRole("heading", { name: "Forecast unavailable" })).toBeVisible();
  await expect(page.getByText(/No substitute election or probability is shown/)).toBeVisible();
  await expect(page.getByText("United States")).toHaveCount(0);
  await expect(page.getByText("WIN PROBABILITY", { exact: true })).toHaveCount(0);
});
