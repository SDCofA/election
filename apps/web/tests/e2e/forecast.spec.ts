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

test("forecast page meets automated WCAG AA and interaction gates", async ({ page }, testInfo) => {
  await page.goto("/elections/de-next-bundestag");
  await expect(page.getByRole("heading", { name: /Germany/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("WIN PROBABILITY")).toBeVisible();
  await expect(page.getByText("DRIVER SENSITIVITY MATRIX")).toBeVisible();
  await expect(page.getByRole("table", { name: "Driver sensitivity matrix" })).toBeVisible();
  await expect(page.locator(".parliament-hemicycle circle")).toHaveCount(630);
  await expect(page.getByRole("heading", { name: "IMMUTABLE FORECAST HISTORY" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "SOURCE LEDGER" })).toBeVisible();

  const violations = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(violations.violations).toEqual([]);

  const coalitionButton = page.getByRole("group", { name: "Select coalition members" }).getByRole("button").first();
  const before = await coalitionButton.getAttribute("aria-pressed");
  await coalitionButton.focus();
  await coalitionButton.press("Enter");
  await expect(coalitionButton).toHaveAttribute("aria-pressed", before === "true" ? "false" : "true");

  if (testInfo.project.name === "chromium") {
    await page.waitForTimeout(250);
    const lcp = await page.evaluate(() => (window as typeof window & { __elexionLcp: { value: number } }).__elexionLcp.value);
    expect(lcp).toBeGreaterThan(0);
    expect(lcp).toBeLessThan(2_500);
  }
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

test("parliament layout matches visual regression baseline", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "desktop visual contract");
  await page.goto("/elections/de-next-bundestag");
  const parliament = page.locator(".parliament-hemicycle");
  await parliament.evaluate((element) => {
    element.style.width = "320px";
    element.style.height = "160px";
  });
  await expect(parliament).toHaveScreenshot(
    "germany-parliament.png",
    { animations: "disabled", maxDiffPixelRatio: 0.025 }
  );
});

test("Brazil publishes an exploratory forecast and a possible candidate field", async ({ page }) => {
  await page.goto("/elections/br-2026-president");
  await expect(page.getByText("WIN PROBABILITY")).toBeVisible();
  await expect(page.getByText("POSSIBLE FIELD")).toBeVisible();
  await expect(page.locator(".possible-field-grid strong").filter({ hasText: "Luiz Inácio Lula da Silva" })).toBeVisible();
});

test("directory lists only G20 members and forecasts every sourced record", async ({ page }) => {
  await page.goto("/calendar");
  await expect(page.getByRole("heading", { name: "G20 countries only." })).toBeVisible();
  await expect(page.locator(".calendar-directory-grid > *")).toHaveCount(19);
  await expect(page.getByText("Egypt", { exact: true })).toHaveCount(0);
  await expect(page.getByText("European Union", { exact: true })).toHaveCount(0);
  await expect(page.getByText("African Union", { exact: true })).toHaveCount(0);
  await page.getByRole("searchbox", { name: "SEARCH G20 COUNTRIES" }).fill("Argentina");
  const argentina = page.getByRole("link", { name: /Argentina/ });
  await expect(argentina).toContainText("2029");
  await argentina.click();
  await expect(page.getByText("WIN PROBABILITY")).toBeVisible();
  await expect(page.getByText("POSSIBLE FIELD")).toBeVisible();
  await expect(page.locator(".possible-field-grid strong").filter({ hasText: "Leading opposition camp / nominee" }).first()).toBeVisible();
  const violations = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(violations.violations).toEqual([]);
});

test("Türkiye exposes a million-run exploratory forecast and named possibilities", async ({ page }) => {
  await page.goto("/elections/tr-next-president");
  await expect(page.locator(".breaking b")).toHaveText("1,000,000 RUNS");
  await expect(page.getByText("WIN PROBABILITY")).toBeVisible();
  await expect(page.getByText("POSSIBLE FIELD")).toBeVisible();
  await expect(page.getByText("Recep Tayyip Erdoğan", { exact: true })).toBeVisible();
  await expect(page.getByText("Mansur Yavaş", { exact: true })).toBeVisible();
  await expect(page.getByText("Özgür Özel", { exact: true })).toBeVisible();
  await expect(page.getByText(/0 jurisdiction-specific out-of-sample folds/)).toBeVisible();
  await expect(page.locator(".candidate").filter({ hasText: "Erdoğan" })).toContainText("UNDERDOG · REAL PATH");
});

test("route-specific API outage never substitutes another election", async ({ page }) => {
  await page.route("**/v1/**", (route) => route.abort());
  await page.goto("/elections/de-next-bundestag");
  await expect(page.getByRole("heading", { name: "Forecast unavailable" })).toBeVisible();
  await expect(page.getByText(/No substitute election or probability is shown/)).toBeVisible();
  await expect(page.getByText("United States")).toHaveCount(0);
  await expect(page.getByText("WIN PROBABILITY")).toHaveCount(0);
});
