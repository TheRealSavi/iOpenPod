// Keep ordinary release links usable while resolving the current platform files.
(() => {
  const links = [...document.querySelectorAll("a[data-release-asset-suffix]")];
  if (!links.length) return;

  function matchesAsset(asset, suffix) {
    if (typeof asset?.name !== "string" || !asset.name.startsWith("iOpenPod-") ||
        !asset.name.endsWith(`-${suffix}`) || asset.state !== "uploaded" ||
        !Number.isFinite(asset.size) || asset.size <= 0) return false;
    try {
      const url = new URL(asset.browser_download_url);
      return url.origin === "https://github.com" && !url.username && !url.password &&
        !url.search && !url.hash &&
        url.pathname.startsWith("/TheRealSavi/iOpenPod/releases/download/") &&
        url.pathname.split("/").length === 7 &&
        decodeURIComponent(url.pathname.split("/").at(-1)) === asset.name;
    } catch {
      return false;
    }
  }

  async function resolveDownloads() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch("https://api.github.com/repos/TheRealSavi/iOpenPod/releases/latest", {
        headers: { Accept: "application/vnd.github+json" },
        credentials: "omit",
        signal: controller.signal,
      });
      if (!response.ok) return;
      const release = await response.json();
      if (release.draft !== false || release.prerelease !== false || !Array.isArray(release.assets)) return;
      for (const link of links) {
        const matches = release.assets.filter((asset) => matchesAsset(asset, link.dataset.releaseAssetSuffix));
        if (matches.length !== 1 || !link.dataset.directLabel) continue;
        link.href = matches[0].browser_download_url;
        link.textContent = link.dataset.directLabel;
      }
    } catch {
      // Offline, rate-limited, malformed, and timed-out responses keep the HTML fallback.
    } finally {
      clearTimeout(timeout);
    }
  }

  // A page view alone should not spend a GitHub API request. Never start a download.
  const section = document.getElementById("install");
  if (section && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      void resolveDownloads();
    });
    observer.observe(section);
  } else {
    void resolveDownloads();
  }
})();
