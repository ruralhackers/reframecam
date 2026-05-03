/* home.js — homepage-specific chrome behaviour.
 *
 * Hero parallax: the hero video moves up at half the page-scroll rate to
 * add depth while still keeping the masked top edge in view. The sticky-nav
 * slide lives in nav.js so it runs on every page.
 *
 * Gated on `prefers-reduced-motion: no-preference` — users who opted out of
 * motion see a non-translated video.
 */

(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }

  // Fade the poster in only once it has fully loaded, so slow connections
  // don't show it painting in top-to-bottom (CSS owns the transition). The
  // complete/naturalWidth check covers the image finishing before this
  // deferred script runs, when the "load" event would never fire.
  var poster = document.querySelector("[data-home-hero-poster]");
  if (poster) {
    if (poster.complete && poster.naturalWidth > 0) {
      poster.setAttribute("data-loaded", "true");
    } else {
      poster.addEventListener(
        "load",
        function () {
          poster.setAttribute("data-loaded", "true");
        },
        { once: true }
      );
    }
  }

  var video = document.querySelector("[data-home-hero-video]");
  if (!video) {
    return;
  }

  // If the video fails to load entirely, hide it so the .home-hero__poster
  // <img> behind it shows through cleanly under the overlay.
  video.addEventListener(
    "error",
    function () {
      video.style.display = "none";
    },
    { once: true }
  );

  var reducedMotion = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  if (reducedMotion.matches) {
    return;
  }

  var ticking = false;

  function update() {
    ticking = false;
    var currentY = window.scrollY || 0;
    // 0.5 keeps the video moving slower than the page; transform-origin is
    // pinned to top-center in CSS so the video doesn't pull off the bottom.
    var offset = Math.round(currentY * 0.5);
    video.style.transform = "translate3d(0, " + offset + "px, 0)";
  }

  function onScroll() {
    if (!ticking) {
      window.requestAnimationFrame(update);
      ticking = true;
    }
  }

  window.addEventListener("scroll", onScroll, { passive: true });

  // Initial paint so the parallax offset matches the scroll position on load.
  update();
})();
