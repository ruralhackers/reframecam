/* reveal.js — homepage scroll-reveal + hero on-load cascade.
 *
 * CSS owns the visuals via [data-revealed="true"]; this module just toggles
 * the attribute as elements enter the viewport (or, for the hero cascade, on
 * DOM ready). Stagger containers ([data-reveal-stagger], [data-reveal-on-load])
 * manage their own children — each child gets `--reveal-index` set so the CSS
 * transition-delay produces the cascade.
 *
 * Gated on `prefers-reduced-motion: no-preference`: opted-out users skip JS
 * entirely and the CSS @media block keeps every element at its resting state.
 */

(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }

  var reducedMotion = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

  if (reducedMotion) {
    return;
  }

  function revealGroup(group) {
    var children = group.children;

    for (var i = 0; i < children.length; i++) {
      children[i].style.setProperty("--reveal-index", i);
      children[i].setAttribute("data-revealed", "true");
    }
  }

  function runOnLoadCascades() {
    var groups = document.querySelectorAll("[data-reveal-on-load]");

    groups.forEach(function (group) {
      revealGroup(group);
    });
  }

  function startCascades() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", runOnLoadCascades);
    } else {
      runOnLoadCascades();
    }
  }

  if (!("IntersectionObserver" in window)) {
    document.querySelectorAll("[data-reveal]").forEach(function (el) {
      el.setAttribute("data-revealed", "true");
    });
    document.querySelectorAll("[data-reveal-stagger]").forEach(function (group) {
      revealGroup(group);
    });
    startCascades();

    return;
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) {
          return;
        }

        var el = entry.target;

        if (el.hasAttribute("data-reveal-stagger")) {
          revealGroup(el);
        } else {
          el.setAttribute("data-revealed", "true");
        }

        observer.unobserve(el);
      });
    },
    { threshold: 0.2, rootMargin: "0px 0px -10% 0px" }
  );

  document.querySelectorAll("[data-reveal]").forEach(function (el) {
    observer.observe(el);
  });

  document.querySelectorAll("[data-reveal-stagger]").forEach(function (group) {
    observer.observe(group);
  });

  startCascades();
})();
