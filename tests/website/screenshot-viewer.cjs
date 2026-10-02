// Run against a built Jekyll preview with Playwright available to Node.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const preview = process.argv[2] || "http://127.0.0.1:8876/iOpenPod/";

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const failures = [];
  try {
    for (const colorScheme of ["light", "dark"]) {
      for (const viewport of [
        { width: 320, height: 740 },
        { width: 375, height: 812 },
        { width: 768, height: 360 },
        { width: 1280, height: 900 },
        { width: 1920, height: 1080 },
      ]) {
        const context = await browser.newContext({
          viewport, colorScheme, deviceScaleFactor: 3, reducedMotion: "reduce",
        });
        const page = await context.newPage();
        page.on("pageerror", (error) => failures.push(error.message));
        page.on("download", () => failures.push("Screenshot triggered a download"));
        await page.goto(preview);
        const originalURL = page.url();
        const logo = page.locator(".product-wordmark img");
        await logo.evaluate((image) => image.decode());
        assert(await logo.evaluate((image) =>
          image.naturalWidth >= image.clientWidth * devicePixelRatio
        ), "Logo must have enough pixels for a high-density display");

        const triggers = page.locator("[data-screenshot-trigger]");
        assert.equal(await triggers.count(), 7);
        const dialog = page.getByRole("dialog", { name: "Screenshot", exact: true });
        const close = dialog.getByRole("button", { name: "Close", exact: true });
        const stage = dialog.getByRole("region");
        for (let index = 0; index < await triggers.count(); index += 1) {
          const trigger = triggers.nth(index);
          await trigger.scrollIntoViewIfNeeded();
          const scrollBefore = await page.evaluate(() => scrollY);
          const source = await trigger.locator("img").getAttribute("src");
          const caption = await trigger.locator("..").locator("figcaption").textContent();
          await trigger.focus();
          if (index % 3 === 2) {
            await trigger.locator("img").click();
          } else {
            await page.keyboard.press(index % 3 ? "Space" : "Enter");
          }
          await dialog.waitFor({ state: "visible" });
          const image = dialog.locator("img");
          await image.evaluate((element) => element.decode());
          assert((await image.getAttribute("src")).endsWith(source));
          assert.equal(await dialog.locator(".screenshot-viewer-caption").textContent(), caption);
          assert(await close.evaluate((element) => element === document.activeElement));
          assert(await dialog.evaluate((element) => element.matches(":modal")));
          assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).overflowY), "hidden");
          const bounds = await dialog.boundingBox();
          assert(bounds.x >= 0 && bounds.y >= 0);
          assert(bounds.x + bounds.width <= viewport.width);
          assert(bounds.y + bounds.height <= viewport.height);
          assert(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth));

          if (index === 0) {
            await page.locator(".product-nav .product-wordmark").focus();
            assert(await close.evaluate((element) => element === document.activeElement), "Background controls should be inert");
            for (const key of ["Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab"]) {
              await page.keyboard.press(key);
              // Chrome may move focus to browser chrome between Tab cycles;
              // document.body then represents no focused page control.
              assert(await dialog.evaluate((element) =>
                element.contains(document.activeElement) || document.activeElement === document.body
              ), "Focus reached background content");
            }
          }

          await dialog.getByRole("button", { name: "Actual size", exact: true }).click();
          assert.equal(await image.evaluate((element) => element.clientWidth), 1920);
          assert.equal(await dialog.getByRole("button", { name: "Fit to window" }).getAttribute("aria-pressed"), "true");
          await stage.focus();
          await page.keyboard.press("ArrowRight");
          await page.waitForFunction(() => document.querySelector(".screenshot-viewer-stage").scrollLeft > 0);
          await dialog.getByRole("button", { name: "Fit to window" }).click();
          assert.equal(await stage.evaluate((element) => element.scrollLeft), 0);
          assert(await stage.evaluate((element) => element.scrollWidth <= element.clientWidth));

          if (index % 3 === 0) {
            await page.keyboard.press("Escape");
          } else if (index % 3 === 1) {
            await close.click();
          } else {
            await page.mouse.click(2, 2);
          }
          await dialog.waitFor({ state: "hidden" });
          await page.waitForFunction(() => !document.documentElement.classList.contains("screenshot-viewer-open"));
          assert(await trigger.evaluate((element) => element === document.activeElement));
          assert.equal(await page.evaluate(() => scrollY), scrollBefore);
          assert.equal(page.url(), originalURL, "Opening a screenshot navigated away");
        }
        await context.close();
        console.log(`PASS: ${colorScheme}, ${viewport.width}x${viewport.height}, five screenshots`);
      }
    }
    assert.deepEqual(failures, []);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
