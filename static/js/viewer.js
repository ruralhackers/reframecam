// Timelapse viewer (spec §5.5) — vanilla JS, no framework, no build step.
//
// Reads a JSON payload (`<script type="application/json">`) embedded by
// `templates/partials/viewer.html` and wires up:
//
//   - frame swapping on a single <img> (§5.5.5)
//   - step / play-pause / scrubber / speed controls (§5.5.2)
//   - date-positioned scrubber with month labels (§5.5.4)
//   - date overlay updates (§5.5.6)
//   - aria-live frame announcements (§4.3 / §9.4)
//   - n-1 / n+1 prefetch when parked (§5.5.3)
//   - prefers-reduced-motion: autoplay never offered, tap-play steps once

(function () {
  "use strict";

  // Base interval at 1× speed. 1200ms reads as a deliberate timelapse pace —
  // fast enough to feel like motion, slow enough that the user registers
  // each frame. The speed dropdown divides this (0.5× → 2400ms, 4× → 300ms).
  var BASE_INTERVAL_MS = 1200;

  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
      return;
    }
    document.addEventListener("DOMContentLoaded", fn);
  }

  function clamp(n, lo, hi) {
    if (n < lo) {
      return lo;
    }
    if (n > hi) {
      return hi;
    }
    return n;
  }

  function prefersReducedMotion() {
    return (
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  // ── Viewer ───────────────────────────────────────────────────────────────

  function initViewer(root) {
    var payloadEl = root.querySelector("[data-viewer-payload]");
    if (!payloadEl) {
      return;
    }
    var payload;
    try {
      payload = JSON.parse(payloadEl.textContent);
    } catch (err) {
      return;
    }
    var frames = payload.frames || [];
    if (frames.length === 0) {
      return;
    }

    var imgEl = root.querySelector("[data-viewer-image]");
    var dateEl = root.querySelector("[data-viewer-date]");
    var liveEl = root.querySelector("[data-viewer-live]");
    var prevBtn = root.querySelector("[data-viewer-prev]");
    var nextBtn = root.querySelector("[data-viewer-next]");
    var playBtn = root.querySelector("[data-viewer-play]");
    var playOverlay = root.querySelector("[data-viewer-play-overlay]");
    var indicatorEl = root.querySelector("[data-viewer-indicator]");
    var speedSel = root.querySelector("[data-viewer-speed]");
    var scrubber = root.querySelector("[data-viewer-scrubber]");
    var ticksEl = root.querySelector("[data-viewer-ticks]");
    var monthsEl = root.querySelector("[data-viewer-months]");
    var playhead = root.querySelector("[data-viewer-playhead]");

    // Pre-parse frame timestamps once. The scrubber's tick positions are
    // (captured - first) / (last - first), normalised to 0..1.
    var times = frames.map(function (f) {
      return new Date(f.captured_at).getTime();
    });
    var firstTime = times[0];
    var lastTime = times[times.length - 1];
    var span = Math.max(lastTime - firstTime, 1);
    var positions = times.map(function (t) {
      return (t - firstTime) / span;
    });

    // Park the playhead at the most recent frame on load (§5.5.1).
    var current = frames.length - 1;
    var playing = false;
    var playTimer = null;
    var speed = 1;
    var reduced = prefersReducedMotion();

    var prefetched = {};

    function prefetch(index) {
      if (index < 0 || index >= frames.length) {
        return;
      }
      if (prefetched[index]) {
        return;
      }
      prefetched[index] = true;
      var pre = new Image();
      pre.src = frames[index].viewer_url;
    }

    function setFrame(index) {
      var i = clamp(index, 0, frames.length - 1);
      current = i;
      var frame = frames[i];
      // The visible flash on swap is typically <100ms (§5.5.5), so a single
      // <img> with src swap is enough — no double-buffering for MVP.
      if (imgEl && imgEl.getAttribute("src") !== frame.viewer_url) {
        imgEl.setAttribute("src", frame.viewer_url);
      }
      if (dateEl) {
        dateEl.textContent = frame.date_overlay;
      }
      if (indicatorEl) {
        indicatorEl.textContent = formatFrameOfTotal(i + 1, frames.length);
      }
      if (liveEl) {
        liveEl.textContent =
          frame.sr_label + ". " + formatFrameOfTotal(i + 1, frames.length);
      }
      if (scrubber) {
        scrubber.setAttribute("aria-valuenow", String(i));
      }
      if (playhead) {
        playhead.style.left = (positions[i] * 100).toFixed(3) + "%";
      }
      if (!playing) {
        // Adjacent prefetch only when parked, per §5.5.3. While playing we'd
        // be paying for prefetches we'll never use.
        prefetch(i - 1);
        prefetch(i + 1);
      }
    }

    function formatFrameOfTotal(n, total) {
      var template = payload.frameOfTotalTemplate || "Photo {n} of {total}";
      return template.replace("{n}", n).replace("{total}", total);
    }

    function step(delta) {
      var next = current + delta;
      if (next < 0) {
        next = 0;
      } else if (next >= frames.length) {
        // Loop back to start when playing past the end so playback feels
        // continuous; on a manual step we just clamp.
        next = playing ? 0 : frames.length - 1;
      }
      setFrame(next);
    }

    function tickInterval() {
      return BASE_INTERVAL_MS / speed;
    }

    function startPlay() {
      if (playing) {
        return;
      }
      if (reduced) {
        // §4.3 / §5.5.1: with prefers-reduced-motion on, autoplay is never
        // offered. A tap on play moves the viewer one frame forward and
        // leaves it parked. The play button retains its play icon.
        // DEVIATION: spec offers either step-once or 0.5× with manual pause;
        // we picked step-once for clarity. Documented in CLAUDE.md.
        step(1);
        return;
      }
      playing = true;
      setPlayState(true);
      var loop = function () {
        step(1);
        playTimer = window.setTimeout(loop, tickInterval());
      };
      playTimer = window.setTimeout(loop, tickInterval());
    }

    function stopPlay() {
      playing = false;
      setPlayState(false);
      if (playTimer !== null) {
        window.clearTimeout(playTimer);
        playTimer = null;
      }
      // Re-prefetch adjacent frames now that we're parked.
      prefetch(current - 1);
      prefetch(current + 1);
    }

    function setPlayState(isPlaying) {
      if (!playBtn) {
        return;
      }
      if (isPlaying) {
        playBtn.classList.add("is-playing");
        playBtn.setAttribute(
          "aria-label",
          playBtn.dataset.labelPause || "Pause",
        );
        playBtn.setAttribute("title", playBtn.dataset.labelPause || "Pause");
      } else {
        playBtn.classList.remove("is-playing");
        playBtn.setAttribute(
          "aria-label",
          playBtn.dataset.labelPlay || "Play",
        );
        playBtn.setAttribute("title", playBtn.dataset.labelPlay || "Play");
      }
      if (playOverlay) {
        playOverlay.style.display = isPlaying ? "none" : "";
      }
    }

    function togglePlay() {
      if (playing) {
        stopPlay();
      } else {
        startPlay();
      }
    }

    // ── Scrubber rendering ────────────────────────────────────────────────

    function renderScrubber() {
      if (!ticksEl) {
        return;
      }
      ticksEl.innerHTML = "";
      for (var i = 0; i < frames.length; i++) {
        var tick = document.createElement("span");
        tick.className = "viewer__tick";
        tick.style.left = (positions[i] * 100).toFixed(3) + "%";
        ticksEl.appendChild(tick);
      }
      if (monthsEl) {
        renderMonthLabels();
      }
    }

    function renderMonthLabels() {
      monthsEl.innerHTML = "";
      var abbr = payload.monthAbbr || [];
      var first = new Date(firstTime);
      var last = new Date(lastTime);
      // Iterate by month from the first photo's month to the last photo's
      // month inclusive. A month with no photos still gets a label so empty
      // gaps read as time, not as missing data (§5.5.4).
      var year = first.getUTCFullYear();
      var month = first.getUTCMonth();
      var endYear = last.getUTCFullYear();
      var endMonth = last.getUTCMonth();
      // Cap the iteration so a misconfigured payload can't run forever.
      for (var i = 0; i < 240; i++) {
        var t = Date.UTC(year, month, 1);
        var pos = (t - firstTime) / span;
        // Only render labels that fall inside the [first, last] range.
        if (t >= firstTime && t <= lastTime) {
          var label = document.createElement("span");
          label.className = "viewer__month-label";
          label.style.left = (clamp(pos, 0, 1) * 100).toFixed(3) + "%";
          label.textContent = abbr[month] || "";
          monthsEl.appendChild(label);
        }
        if (year === endYear && month === endMonth) {
          break;
        }
        month += 1;
        if (month > 11) {
          month = 0;
          year += 1;
        }
      }
    }

    function nearestFrameIndexForX(clientX) {
      var rect = scrubber.getBoundingClientRect();
      var rel = (clientX - rect.left) / rect.width;
      rel = clamp(rel, 0, 1);
      var bestIdx = 0;
      var bestDist = Infinity;
      for (var i = 0; i < positions.length; i++) {
        var d = Math.abs(positions[i] - rel);
        if (d < bestDist) {
          bestDist = d;
          bestIdx = i;
        }
      }
      return bestIdx;
    }

    // ── Wiring ────────────────────────────────────────────────────────────

    if (prevBtn) {
      prevBtn.addEventListener("click", function () {
        stopPlay();
        step(-1);
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function () {
        stopPlay();
        step(1);
      });
    }
    if (playBtn) {
      playBtn.addEventListener("click", togglePlay);
    }
    if (playOverlay) {
      playOverlay.addEventListener("click", togglePlay);
    }
    if (speedSel) {
      speedSel.addEventListener("change", function () {
        var v = parseFloat(speedSel.value);
        if (!isNaN(v) && v > 0) {
          speed = v;
        }
      });
    }
    if (scrubber) {
      var dragging = false;
      var onPoint = function (clientX) {
        var idx = nearestFrameIndexForX(clientX);
        setFrame(idx);
      };
      scrubber.addEventListener("pointerdown", function (ev) {
        ev.preventDefault();
        stopPlay();
        dragging = true;
        scrubber.setPointerCapture(ev.pointerId);
        onPoint(ev.clientX);
      });
      scrubber.addEventListener("pointermove", function (ev) {
        if (!dragging) {
          return;
        }
        onPoint(ev.clientX);
      });
      scrubber.addEventListener("pointerup", function (ev) {
        dragging = false;
        try {
          scrubber.releasePointerCapture(ev.pointerId);
        } catch (e) {
          // releasePointerCapture throws if the pointer was never captured;
          // safe to ignore.
        }
      });
      scrubber.addEventListener("keydown", function (ev) {
        if (ev.key === "ArrowLeft") {
          ev.preventDefault();
          stopPlay();
          step(-1);
        } else if (ev.key === "ArrowRight") {
          ev.preventDefault();
          stopPlay();
          step(1);
        } else if (ev.key === "Home") {
          ev.preventDefault();
          stopPlay();
          setFrame(0);
        } else if (ev.key === "End") {
          ev.preventDefault();
          stopPlay();
          setFrame(frames.length - 1);
        }
      });
    }

    renderScrubber();
    setFrame(current);

    // Autoplay from the start on page load (full mode only). Reduced motion
    // skips this — startPlay would step-once which feels jarring on arrival.
    if (payload.mode === "full" && !reduced) {
      setFrame(0);
      startPlay();
    }

    // Expose a single hook so the upload module can park the viewer on the
    // newly-uploaded frame after a successful upload (§6.7). The append takes
    // a minimal frame shape — the viewer synthesises a numeric date overlay
    // since the server-formatted strings aren't round-tripped in the upload
    // response. If multiple viewers were ever rendered on a page, the last
    // one to init wins; we have a single viewer in MVP.
    function appendFrame(frame) {
      if (!frame || !frame.captured_at || !frame.viewer_url) {
        return;
      }
      var d = new Date(frame.captured_at);
      var pad2 = function (n) {
        return (n < 10 ? "0" : "") + n;
      };
      var overlay =
        pad2(d.getUTCDate()) +
        "/" +
        pad2(d.getUTCMonth() + 1) +
        "/" +
        d.getUTCFullYear();
      frames.push({
        index: frames.length,
        captured_at: frame.captured_at,
        viewer_url: frame.viewer_url,
        thumb_url: frame.thumb_url || frame.viewer_url,
        date_overlay: frame.date_overlay || overlay,
        sr_label: frame.sr_label || overlay,
      });
      times.push(d.getTime());
      lastTime = times[times.length - 1];
      span = Math.max(lastTime - firstTime, 1);
      positions = times.map(function (t) {
        return (t - firstTime) / span;
      });
      if (scrubber) {
        scrubber.setAttribute("aria-valuemax", String(frames.length - 1));
      }
      // Dynamic single → full transition. The controls DOM is always
      // rendered server-side when mode != empty; CSS hides it in single
      // mode. Flipping data-mode here reveals the controls without a
      // page refresh.
      if (frames.length === 2 && root.dataset.mode === "single") {
        root.dataset.mode = "full";
        root.classList.remove("viewer--single");
        root.classList.add("viewer--full");
      }
      renderScrubber();
      setFrame(frames.length - 1);
    }
    window.ReFrameViewer = window.ReFrameViewer || {};
    window.ReFrameViewer.append = appendFrame;
  }

  ready(function () {
    var viewers = document.querySelectorAll("[data-mode]");
    for (var i = 0; i < viewers.length; i++) {
      // Scope to viewers (not other [data-mode] consumers) by checking class.
      if (viewers[i].classList.contains("viewer")) {
        initViewer(viewers[i]);
      }
    }
  });
})();
