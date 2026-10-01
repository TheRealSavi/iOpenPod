(() => {
  const viewer = document.querySelector("#screenshot-viewer");
  if (!viewer) {
    return;
  }

  const image = viewer.querySelector(".screenshot-viewer-image");
  const caption = viewer.querySelector(".screenshot-viewer-caption");
  const stage = viewer.querySelector(".screenshot-viewer-stage");
  const zoom = viewer.querySelector("[data-screenshot-zoom]");
  const close = viewer.querySelector("[data-screenshot-close]");
  let opener = null;
  let backdropPressed = false;

  const setZoom = (zoomed) => {
    viewer.dataset.zoomed = String(zoomed);
    zoom.setAttribute("aria-pressed", String(zoomed));
    zoom.textContent = zoomed ? "Fit to window" : "Actual size";
    stage.scrollTo(0, 0);
  };

  document.querySelectorAll("[data-screenshot-trigger]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const source = trigger.querySelector("img");
      opener = trigger;
      image.src = source.currentSrc || source.src;
      image.alt = source.alt;
      caption.textContent = trigger.closest("figure").querySelector("figcaption").textContent;
      setZoom(false);
      viewer.showModal();
      document.documentElement.classList.add("screenshot-viewer-open");
    });
  });

  zoom.addEventListener("click", () => setZoom(viewer.dataset.zoomed !== "true"));
  close.addEventListener("click", () => viewer.close());

  const outsideViewer = (event) => {
    const bounds = viewer.getBoundingClientRect();
    return event.target === viewer && (
      event.clientX < bounds.left || event.clientX > bounds.right ||
      event.clientY < bounds.top || event.clientY > bounds.bottom
    );
  };

  viewer.addEventListener("pointerdown", (event) => {
    backdropPressed = outsideViewer(event);
  });
  viewer.addEventListener("click", (event) => {
    if (backdropPressed && outsideViewer(event)) {
      viewer.close();
    }
    backdropPressed = false;
  });

  // Native dialog supplies Escape dismissal, focus containment, and inert content.
  viewer.addEventListener("close", () => {
    document.documentElement.classList.remove("screenshot-viewer-open");
    image.removeAttribute("src");
    opener?.focus({ preventScroll: true });
    opener = null;
  });
})();
