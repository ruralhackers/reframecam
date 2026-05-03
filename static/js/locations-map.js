/* /locations map — initialises a Leaflet map from an inline JSON payload.
 *
 * Same pattern as viewer.js: a `<script type="application/json">` blob
 * carries the marker list, the module reads it on DOMContentLoaded. Leaflet
 * itself is self-hosted (static/vendor/leaflet); OpenStreetMap serves tiles.
 * Vanilla JS, IIFE, no build step.
 */
(function () {
  "use strict";

  // SVG pin styled through CSS so colours track the site's deep-green palette.
  // `fill` on each sub-element is set from app.css via class selectors.
  var MARKER_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 40" ' +
    'width="28" height="40" aria-hidden="true" focusable="false">' +
    '<path class="locations-map__marker-pin" d="M14 0C6.27 0 0 6.27 0 14c0 ' +
    "9.5 14 26 14 26s14-16.5 14-26C28 6.27 21.73 0 14 0z\"/>" +
    '<circle class="locations-map__marker-dot" cx="14" cy="14" r="5"/>' +
    "</svg>";

  function buildIcon() {
    return L.divIcon({
      html: MARKER_SVG,
      className: "locations-map__marker",
      iconSize: [28, 40],
      iconAnchor: [14, 40],
      popupAnchor: [0, -36],
    });
  }

  // Popup content is built with the DOM API rather than an HTML string so a
  // station name can never inject markup.
  function buildPopup(marker) {
    var wrap = document.createElement("div");
    wrap.className = "locations-map__popup";

    var link = document.createElement("a");
    link.href = marker.href;
    link.textContent = marker.name;
    wrap.appendChild(link);

    if (marker.place) {
      var place = document.createElement("p");
      place.textContent = marker.place;
      wrap.appendChild(place);
    }

    return wrap;
  }

  // On touch devices, Leaflet's single-finger pan steals page-scroll gestures
  // when the user is trying to scroll past the map. We intercept single-finger
  // touchmove in the capture phase so Leaflet never sees it (the browser then
  // handles the scroll natively via touch-action: pan-y) and surface a hint
  // pill AFTER the gesture finishes — on touchend, if the user dragged with
  // one finger and lifted it still over the map. The post-gesture timing
  // means a quick scroll never sees the pill; only deliberate map-pan
  // attempts (which couldn't pan) do. Two-finger gestures fall through to
  // Leaflet untouched.
  var DRAG_THRESHOLD_PX = 15;
  var HINT_VISIBLE_MS = 1800;

  function wireTouchGate(el) {
    var hint = document.createElement("div");
    hint.className = "locations-map__hint";
    hint.setAttribute("aria-hidden", "true");
    hint.textContent = el.dataset.mapHint || "";
    if (el.parentNode) {
      el.parentNode.appendChild(hint);
    }

    var hideTimer = null;
    var startX = 0;
    var startY = 0;
    var tracking = false;

    function clearHide() {
      if (hideTimer !== null) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
    }

    function showHint() {
      clearHide();
      hint.classList.add("is-visible");
      hideTimer = setTimeout(function () {
        hideTimer = null;
        hint.classList.remove("is-visible");
      }, HINT_VISIBLE_MS);
    }

    function hideHintNow() {
      clearHide();
      hint.classList.remove("is-visible");
    }

    el.addEventListener(
      "touchstart",
      function (e) {
        if (e.touches.length === 1) {
          var t = e.touches[0];
          startX = t.clientX;
          startY = t.clientY;
          tracking = true;
          // A fresh gesture starts; hide any lingering pill from the previous
          // one so the auto-hide timer can't race with a new touch.
          hideHintNow();
        } else {
          // Multi-touch — Leaflet owns this; don't queue a hint.
          tracking = false;
          hideHintNow();
        }
      },
      { capture: true, passive: true }
    );

    el.addEventListener(
      "touchmove",
      function (e) {
        if (e.touches.length === 1) {
          e.stopImmediatePropagation();
        }
      },
      { capture: true, passive: true }
    );

    el.addEventListener(
      "touchend",
      function (e) {
        if (!tracking || e.touches.length !== 0) {
          return;
        }
        tracking = false;

        var t = e.changedTouches[0];
        var dx = t.clientX - startX;
        var dy = t.clientY - startY;
        if (dx * dx + dy * dy < DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX) {
          // A tap (marker click, accidental touch) — no hint.
          return;
        }

        // Only show if the finger lifted while still over the map. If they
        // dragged off (e.g. a long vertical scroll), they got what they
        // wanted and a hint over an unrelated element would be confusing.
        var rect = el.getBoundingClientRect();
        if (
          t.clientX < rect.left ||
          t.clientX > rect.right ||
          t.clientY < rect.top ||
          t.clientY > rect.bottom
        ) {
          return;
        }

        showHint();
      },
      { capture: true, passive: true }
    );
  }

  function init() {
    var el = document.querySelector(".locations-map");
    if (!el || typeof L === "undefined") {
      return;
    }

    var payloadEl = document.querySelector("[data-locations-payload]");
    if (!payloadEl) {
      return;
    }

    var markers;
    try {
      markers = JSON.parse(payloadEl.textContent);
    } catch (err) {
      return;
    }
    if (!markers || !markers.length) {
      return;
    }

    var map = L.map(el, { scrollWheelZoom: false });

    wireTouchGate(el);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">' +
        "OpenStreetMap</a> contributors",
    }).addTo(map);

    var icon = buildIcon();
    var bounds = [];

    markers.forEach(function (marker) {
      var point = [marker.lat, marker.lng];

      L.marker(point, { icon: icon })
        .addTo(map)
        .bindPopup(buildPopup(marker));
      bounds.push(point);
    });

    if (bounds.length === 1) {
      map.setView(bounds[0], 13);
    } else {
      map.fitBounds(bounds, { padding: [40, 40] });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
