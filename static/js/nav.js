/* nav.js — sticky-nav slide behaviour.
 *
 * The fixed site header hides on scroll-down past its own height and slides
 * back into view on scroll-up. Loaded on every page; the hero parallax in
 * home.js is homepage-only.
 *
 * Gated on `prefers-reduced-motion: no-preference` — users who opted out of
 * motion see a fully visible, non-animating header.
 */

(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }

  var reducedMotion = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  if (reducedMotion.matches) {
    return;
  }

  var header = document.querySelector("[data-site-header]");
  if (!header) {
    return;
  }

  var lastY = window.scrollY || 0;
  var ticking = false;
  var headerHeight = header.offsetHeight;

  function onResize() {
    headerHeight = header.offsetHeight;
  }

  window.addEventListener("resize", onResize, { passive: true });

  function update() {
    ticking = false;
    var currentY = window.scrollY || 0;

    // Past the header height, hide on scroll-down and show on scroll-up.
    // Near the very top, always show — avoids a flash on rebound scrolls.
    if (currentY > headerHeight && currentY > lastY) {
      header.classList.add("site-header--hidden");
    } else if (currentY < lastY || currentY <= headerHeight) {
      header.classList.remove("site-header--hidden");
    }

    lastY = currentY;
  }

  function onScroll() {
    if (!ticking) {
      window.requestAnimationFrame(update);
      ticking = true;
    }
  }

  window.addEventListener("scroll", onScroll, { passive: true });
})();
