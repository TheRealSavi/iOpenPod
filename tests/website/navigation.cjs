// Run against a built Jekyll preview with Playwright available to Node.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const preview = process.argv[2] || "http://127.0.0.1:8876/iOpenPod/";

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    for (const colorScheme of ["light", "dark"]) {
      const context = await browser.newContext({ colorScheme, reducedMotion: "reduce" });
      const page = await context.newPage();
      for (const route of ["", "install-help/"]) {
        for (const width of [320, 375, 414, 768, 1280, 1920]) {
          await page.setViewportSize({ width, height: 900 });
          await page.goto(new URL(route, preview).href);
          await page.evaluate(() => document.fonts.ready);
          const nav = page.getByRole("navigation", { name: "Primary navigation" });
          assert.equal(await nav.getByRole("link", { name: "Help", exact: true }).getAttribute("href"), new URL("install-help/", preview).pathname);
          assert.equal(await nav.getByRole("link", { name: "Source", exact: true }).getAttribute("href"), await page.getByRole("link", { name: "Source on GitHub" }).getAttribute("href"));
          assert.equal(await nav.getByRole("link", { name: "Discord", exact: true }).getAttribute("href"), "https://discord.gg/9Yy499Tf5d");
          assert(await nav.locator("a, button").evaluateAll((controls) => {
            const boxes = controls.map((control) => control.getBoundingClientRect());
            return boxes.every((box, index) => box.x >= 0 && box.right <= innerWidth && box.height >= 44 &&
              boxes.slice(index + 1).every((other) => box.right <= other.x || other.right <= box.x || box.bottom <= other.y || other.bottom <= box.y));
          }), "Header controls must have usable targets without overlapping or overflowing");
          assert(await page.locator("img").evaluateAll((images) => images.every((image) => parseFloat(getComputedStyle(image).borderTopLeftRadius) > 0)), "All images should have rounded corners");
          if (!route) {
            assert(await page.locator(".intro-visual").evaluate((hero) => hero.nextElementSibling.id === "tour" && hero.nextElementSibling.querySelector("#sync-heading")), "The hero should lead directly to Sync");
            await page.getByRole("link", { name: "Explore the app" }).click();
            assert.equal(new URL(page.url()).hash, "#tour");
          }
          console.log(`PASS: ${route || "home"}, ${colorScheme}, ${width}px`);
        }

        const toggles = page.locator("[data-theme-toggle]");
        assert.equal(await toggles.count(), 2);
        const opposite = colorScheme === "light" ? "dark" : "light";
        await page.emulateMedia({ colorScheme: opposite });
        await page.waitForFunction((theme) => [...document.querySelectorAll("[data-theme-toggle]")].every((toggle) => toggle.dataset.themeCurrent === theme), opposite);
        // Keyboard activation in the header must update the footer too.
        await toggles.first().focus();
        await page.keyboard.press("Enter");
        assert.equal(await page.locator("html").getAttribute("data-theme"), colorScheme);
        assert(await toggles.evaluateAll((buttons) => buttons.every((button) => button.dataset.themeCurrent === document.documentElement.dataset.theme && button.getAttribute("aria-pressed") === String(document.documentElement.dataset.theme === "dark"))));
        await page.reload();
        assert.equal(await page.locator("html").getAttribute("data-theme"), colorScheme, "Theme preference should survive reload");
        await toggles.last().click();
        assert.equal(await toggles.first().getAttribute("aria-label"), `Switch to ${colorScheme} mode`);
        assert.equal(await page.locator("html").getAttribute("data-theme"), opposite);
        // Start the next route with the system preference again.
        await page.evaluate(() => localStorage.clear());
        await page.emulateMedia({ colorScheme });
      }
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
