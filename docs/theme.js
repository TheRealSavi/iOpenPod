(() => {
  const storageKey = "iopenpod-theme";
  const root = document.documentElement;
  const toggle = document.querySelector("[data-theme-toggle]");

  if (!toggle) {
    return;
  }

  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let savedTheme = null;

  const readStoredTheme = () => {
    try {
      const value = localStorage.getItem(storageKey);
      if (value === "light" || value === "dark") {
        return value;
      }
    } catch (error) {
      void error;
    }

    return null;
  };

  const writeStoredTheme = (theme) => {
    try {
      if (theme) {
        localStorage.setItem(storageKey, theme);
      } else {
        localStorage.removeItem(storageKey);
      }
    } catch (error) {
      void error;
    }
  };

  const systemTheme = () => (media.matches ? "dark" : "light");

  const activeTheme = () => savedTheme || systemTheme();

  const updateToggle = () => {
    const currentTheme = activeTheme();
    const nextTheme = currentTheme === "dark" ? "light" : "dark";

    toggle.textContent = nextTheme === "dark" ? "☾" : "☀";
    toggle.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
    toggle.setAttribute("aria-pressed", currentTheme === "dark" ? "true" : "false");
    toggle.dataset.themeCurrent = currentTheme;

    if (!savedTheme) {
      root.removeAttribute("data-theme");
    }
  };

  const applyTheme = (theme, persist = true) => {
    if (theme === "light" || theme === "dark") {
      savedTheme = theme;
      root.dataset.theme = theme;
      if (persist) {
        writeStoredTheme(theme);
      }
    } else {
      savedTheme = null;
      root.removeAttribute("data-theme");
      if (persist) {
        writeStoredTheme(null);
      }
    }

    updateToggle();
  };

  savedTheme = readStoredTheme();
  if (savedTheme) {
    root.dataset.theme = savedTheme;
  } else {
    root.removeAttribute("data-theme");
  }

  updateToggle();

  toggle.addEventListener("click", () => {
    applyTheme(activeTheme() === "dark" ? "light" : "dark");
  });

  media.addEventListener("change", () => {
    if (!savedTheme) {
      updateToggle();
    }
  });
})();
