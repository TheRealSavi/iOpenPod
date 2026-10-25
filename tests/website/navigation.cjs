// Run against a built Jekyll preview with Playwright available to Node.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("playwright");

const preview = process.argv[2] || "http://127.0.0.1:8876/iOpenPod/";
// An optional third argument saves screenshots and a machine-readable QA report.
const evidenceDirectory = process.argv[3] && path.resolve(process.argv[3]);
const results = [];
const screenshots = [];

function relativeTarget(route) {
  const url = new URL(route, preview);
  return url.pathname + url.hash;
}

async function saveReport(error) {
  if (!evidenceDirectory) return;
  await fs.mkdir(evidenceDirectory, { recursive: true });
  await fs.writeFile(path.join(evidenceDirectory, "navigation-results.json"), JSON.stringify({
    preview,
    checkedAt: new Date().toISOString(),
    status: error ? "failed" : "passed",
    cases: results,
    screenshots,
    ...(error ? { error: error.stack || String(error) } : {}),
  }, null, 2) + "\n");
}

(async () => {
  const guides = JSON.parse(await fs.readFile(path.join(__dirname, "../../website/_data/guides.json"), "utf8"));
  assert(Array.isArray(guides) && guides.length > 0, "The guide catalog must contain articles");
  const guideRoutes = guides.map((guide) => {
    assert(typeof guide.url === "string" && guide.url.startsWith("/guides/") && guide.url !== "/guides/" && guide.url.endsWith("/"), "Each catalog entry must link to a guide article");
    return guide.url.slice(1);
  });
  assert.equal(new Set(guideRoutes).size, guideRoutes.length, "Guide catalog URLs must be unique");
  if (evidenceDirectory) await fs.mkdir(evidenceDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    for (const colorScheme of ["light", "dark"]) {
      const context = await browser.newContext({ colorScheme, reducedMotion: "reduce" });
      const page = await context.newPage();
      for (const route of ["", "install-help/", "guides/", ...guideRoutes]) {
        for (const width of [320, 375, 414, 768, 1280, 1920]) {
          await page.setViewportSize({ width, height: 900 });
          const response = await page.goto(new URL(route, preview).href);
          const testCase = `${route || "home"}, ${colorScheme}, ${width}px`;
          assert.equal(response.status(), 200, `${testCase}: page must load successfully`);
          await page.evaluate(() => document.fonts.ready);
          const nav = page.getByRole("navigation", { name: "Primary navigation" });
          assert.equal(await nav.getByRole("link", { name: "Help", exact: true }).getAttribute("href"), new URL("install-help/", preview).pathname);
          assert.equal(await nav.getByRole("link", { name: "Guides", exact: true }).getAttribute("href"), relativeTarget("guides/"));
          assert.equal(await nav.getByRole("link", { name: "Source", exact: true }).getAttribute("href"), await page.getByRole("link", { name: "Source on GitHub" }).getAttribute("href"));
          assert.equal(await nav.getByRole("link", { name: "Discord", exact: true }).getAttribute("href"), "https://discord.gg/9Yy499Tf5d");
          assert.equal(await page.locator("h1").count(), 1, `${testCase}: each page must have one main heading`);
          assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), `${testCase}: document must not overflow horizontally`);
          assert(await nav.locator("a, button").evaluateAll((controls) => {
            const boxes = controls.map((control) => control.getBoundingClientRect());
            return boxes.every((box, index) => box.x >= 0 && box.right <= innerWidth && box.height >= 44 &&
              boxes.slice(index + 1).every((other) => box.right <= other.x || other.right <= box.x || box.bottom <= other.y || other.bottom <= box.y));
          }), "Header controls must have usable targets without overlapping or overflowing");
          assert(await page.locator("img").evaluateAll((images) => images.every((image) => parseFloat(getComputedStyle(image).borderTopLeftRadius) > 0)), "All images should have rounded corners");
          assert(await page.locator(".product-nav a, .product-nav button, .footer-links a, .footer-links button, .channel-link, .intro-actions a, .page-index a").evaluateAll((controls) => controls.every((control) => {
            const walker = document.createTreeWalker(control, NodeFilter.SHOW_TEXT);
            const lines = [];
            while (walker.nextNode()) {
              if (!walker.currentNode.textContent.trim()) continue;
              const range = document.createRange();
              range.selectNodeContents(walker.currentNode);
              lines.push(...[...range.getClientRects()].filter((rect) => rect.height > 0));
            }
            return !lines.length || Math.max(...lines.map((rect) => rect.y)) - Math.min(...lines.map((rect) => rect.y)) < 2;
          })), `${testCase}: short navigation and download labels must stay on one line`);
          if (route.startsWith("guides/")) {
            assert(await page.locator(".guide-header").evaluate((header) => {
              const style = getComputedStyle(header);
              return parseFloat(style.paddingTop) > 0 && parseFloat(style.paddingBottom) > 0;
            }), `${testCase}: guide heading spacing must load with the guide stylesheet`);
            const guideLists = page.locator(".guide-links");
            assert(await guideLists.count() > 0, `${testCase}: guide navigation must be present`);
            assert(await guideLists.evaluateAll((lists) => lists.every((list) => {
              const style = getComputedStyle(list);
              return style.display === "grid" && style.listStyleType === "none";
            })), `${testCase}: guide navigation must use the styled grid without default bullets`);
            const breadcrumbs = page.getByRole("navigation", { name: "Breadcrumb", exact: true });
            const isDirectory = route === "guides/";
            assert.deepEqual(await breadcrumbs.getByRole("link").evaluateAll((links) => links.map((link) => link.getAttribute("href"))),
              isDirectory ? [relativeTarget("")] : [relativeTarget(""), relativeTarget("guides/")],
              `${testCase}: breadcrumbs must return to the site and guide directory`);
            assert.equal(await breadcrumbs.locator('[aria-current="page"]').count(), 1);
            assert((await breadcrumbs.locator('[aria-current="page"]').innerText()).trim());
            const nextSteps = page.locator(".guide-next");
            assert.deepEqual(await nextSteps.getByRole("link").evaluateAll((links) => links.map((link) => link.getAttribute("href"))),
              [relativeTarget("#install"), relativeTarget("install-help/")],
              `${testCase}: guide calls to action must reach downloads and setup`);
            if (isDirectory) {
              const directoryLinks = await page.locator(".guide-directory a").evaluateAll((links) => links.map((link) => link.getAttribute("href")));
              assert.deepEqual(directoryLinks.sort(), guideRoutes.map(relativeTarget).sort(), `${testCase}: directory groups must include every catalog article exactly once`);
            } else {
              const relatedLinks = await page.locator(".guide-related .guide-links a").evaluateAll((links) => links.map((link) => link.getAttribute("href")));
              const articleTargets = guideRoutes.map(relativeTarget);
              assert(relatedLinks.length > 0 && relatedLinks.every((target) => articleTargets.includes(target) && target !== relativeTarget(route)), `${testCase}: related links must lead to other catalog articles`);
              assert.equal(new Set(relatedLinks).size, relatedLinks.length, `${testCase}: related links must not repeat an article`);
              assert(await nextSteps.getByRole("link", { name: "Get iOpenPod", exact: true }).isVisible());
              assert(await nextSteps.getByRole("link", { name: "Installation help", exact: true }).isVisible());
            }
          }
          if (evidenceDirectory && [375, 1280].includes(width) && ["", guideRoutes[0]].includes(route)) {
            await page.locator("img").evaluateAll((images) => Promise.all(images.map((image) => {
              image.loading = "eager";
              return image.decode().catch(() => {});
            })));
            const filename = `${route ? route.split("/").filter(Boolean).at(-1) : "home"}-${colorScheme}-${width}.png`;
            await page.screenshot({ path: path.join(evidenceDirectory, filename), fullPage: true, animations: "disabled" });
            screenshots.push(filename);
          }
          if (!route) {
            assert(await page.locator(".intro [data-screenshot-trigger]").isVisible(), "The introduction must show the app screenshot");
            const pageIndex = page.getByRole("navigation", { name: "On this page" });
            assert.deepEqual(await pageIndex.getByRole("link").evaluateAll((links) => links.map((link) => link.getAttribute("href"))),
              ["#why-iopenpod", "#tour", "#compatibility", "#install", "#migration", "#faq"], "The page index must reach the main product information");
            await pageIndex.getByRole("link", { name: "Features", exact: true }).click();
            assert.equal(new URL(page.url()).hash, "#tour");
          }
          results.push({ route: route || "home", colorScheme, width });
          console.log(`PASS: ${testCase}`);
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
  await saveReport();
})().catch(async (error) => {
  console.error(error);
  await saveReport(error);
  process.exitCode = 1;
});
