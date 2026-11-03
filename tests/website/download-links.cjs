// Run against a real Jekyll build. All API and binary requests are intercepted.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const preview = process.argv[2] || "http://127.0.0.1:8876/";
const api = "https://api.github.com/repos/TheRealSavi/iOpenPod/releases/latest";
const fallback = "https://github.com/TheRealSavi/iOpenPod/releases/latest";
const assetBase = "https://github.com/TheRealSavi/iOpenPod/releases/download/v99.0.0/";
const suffixes = ["Windows-x86_64.zip", "macOS-arm64.dmg", "macOS-x86_64.dmg", "Linux-x86_64.tar.gz"];
const asset = (suffix) => ({ name: `iOpenPod-99.0.0-${suffix}`, state: "uploaded", size: 1024,
  browser_download_url: `${assetBase}iOpenPod-99.0.0-${suffix}` });
const release = (assets = suffixes.map(asset)) => ({ draft: false, prerelease: false, assets });

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    for (const scenario of [
      { name: "platform files", body: release([...suffixes.map(asset), asset("sparkle-update-macOS-arm64.zip")]), resolved: suffixes },
      { name: "partial release", body: release([asset(suffixes[0])]), resolved: [suffixes[0]] },
      { name: "duplicate platform", body: release([asset(suffixes[0]), asset(suffixes[0])]), resolved: [] },
      { name: "foreign download URL", body: release([{ ...asset(suffixes[0]), browser_download_url: "https://example.com/iOpenPod.zip" }]), resolved: [] },
      { name: "wrong repository", body: release([{ ...asset(suffixes[0]), browser_download_url: asset(suffixes[0]).browser_download_url.replace("TheRealSavi", "other") }]), resolved: [] },
      { name: "wrong filename URL", body: release([{ ...asset(suffixes[0]), browser_download_url: `${assetBase}something-else.zip` }]), resolved: [] },
      { name: "malformed URL", body: release([{ ...asset(suffixes[0]), browser_download_url: "not a URL" }]), resolved: [] },
      { name: "unfinished asset", body: release([{ ...asset(suffixes[0]), state: "new" }]), resolved: [] },
      { name: "empty asset", body: release([{ ...asset(suffixes[0]), size: 0 }]), resolved: [] },
      { name: "prerelease", body: { ...release(), prerelease: true }, resolved: [] },
      { name: "draft", body: { ...release(), draft: true }, resolved: [] },
      { name: "missing assets", body: { draft: false, prerelease: false }, resolved: [] },
      { name: "null asset", body: release([null]), resolved: [] },
      { name: "rate limited", status: 403, body: { message: "rate limit exceeded" }, resolved: [] },
      { name: "not found", status: 404, body: {}, resolved: [] },
      { name: "malformed JSON", raw: "{", resolved: [] },
      { name: "offline", offline: true, resolved: [] },
      { name: "request timeout", timeout: true, resolved: [] },
    ]) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
      let requests = 0;
      let attemptedDownloads = 0;
      await context.route(api, async (route) => {
        requests++;
        if (scenario.timeout) return;
        if (scenario.offline) await route.abort();
        else await route.fulfill({ status: scenario.status || 200, contentType: "application/json", body: scenario.raw || JSON.stringify(scenario.body) });
      });
      await context.route("https://github.com/**/releases/download/**", async (route) => { attemptedDownloads++; await route.abort(); });
      const page = await context.newPage();
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));
      const response = await page.goto(preview);
      assert.equal(response.status(), 200);
      const links = page.locator("a[data-release-asset-suffix]");
      assert.equal(await links.count(), 4);
      assert.equal(requests, 0, "Loading the top of the page should not request release data");
      const store = await page.locator("#microsoft-store a").getAttribute("href");
      const pypi = await page.locator("#pypi a").getAttribute("href");
      const apiRequest = page.waitForRequest(api, { timeout: 10000 });
      await page.locator("#install").scrollIntoViewIfNeeded();
      await apiRequest;
      if (scenario.timeout) await page.waitForTimeout(5400);
      if (scenario.resolved.length) {
        await page.waitForFunction((suffix) => document.querySelector(`[data-release-asset-suffix="${suffix}"]`).href.includes("/releases/download/"), scenario.resolved[0]);
      } else await page.waitForTimeout(100);
      for (const suffix of suffixes) {
        const link = page.locator(`[data-release-asset-suffix="${suffix}"]`);
        const expected = scenario.resolved.includes(suffix) ? asset(suffix).browser_download_url : fallback;
        assert.equal(await link.getAttribute("href"), expected, `${scenario.name}: ${suffix}`);
        if (scenario.resolved.includes(suffix)) assert.equal(await link.innerText(), await link.getAttribute("data-direct-label"));
      }
      assert.equal(await page.locator("#microsoft-store a").getAttribute("href"), store);
      assert.equal(await page.locator("#pypi a").getAttribute("href"), pypi);
      await page.locator("h1").scrollIntoViewIfNeeded();
      await page.locator("#install").scrollIntoViewIfNeeded();
      assert.equal(requests, 1, "Revisiting downloads must not issue another API request");
      assert.equal(attemptedDownloads, 0, "No binary request without a user's click");
      assert.deepEqual(pageErrors, []);
      if (scenario.name === "platform files") {
        for (const width of [320, 375, 414, 768, 1280]) {
          await page.setViewportSize({ width, height: 900 });
          assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Resolved links overflow at ${width}`);
        }
        await page.locator(`[data-release-asset-suffix="${suffixes[0]}"]`).click();
        assert.equal(attemptedDownloads, 1, "A click uses the resolved native file");
      }
      await context.close();
      console.log(`PASS: ${scenario.name}`);
    }
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto(preview);
    assert.deepEqual(await page.locator("a[data-release-asset-suffix]").evaluateAll((links) => links.map((a) => a.href)), Array(4).fill(fallback));
    assert(await page.getByRole("link", { name: "Games setup guide", exact: true }).isVisible());
    await context.close();
    console.log("PASS: JavaScript-disabled downloads and guide discovery");
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
