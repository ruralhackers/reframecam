// Upload state machine (spec §6) — vanilla JS, no framework, no build step.
//
// Drives all six §6.2 states (picker / preview / uploading / validating /
// success / failure) on a single station page. Reads its config from a
// `<script type="application/json">` block emitted by templates/partials/
// upload.html so the module is route-free.
//
// Compression: load file into <img>, apply EXIF orientation while drawing
// to canvas, resize so the long edge ≤ 2400 px, re-encode at JPEG q0.85.
// HEIC files that the browser can't decode bypass compression — the server
// transcodes them (§6.4). The compressed result is canonical.
//
// Transport: XMLHttpRequest with upload.onprogress (fetch progress is
// desktop-only on mobile at the time of writing). UUIDv4 client token sent
// as `X-Client-Token`, retained across retries. Stall ≥ 30 s = network
// failure (§6.6). Backgrounding the tab swaps the pill to "paused".

(function () {
  "use strict";

  // Hold the validating state for at least this long before transitioning to
  // success/failure. Server fast-paths can return in a few hundred ms; without
  // a floor the "Checking…" overlay flashes past and the user has no
  // reassurance any check happened. Network/abort failures don't pass through
  // validating, so this only affects post-XHR transitions.
  var MIN_VALIDATING_MS = 1500;

  function prefersReducedMotion() {
    return !!(
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
      return;
    }
    document.addEventListener("DOMContentLoaded", fn);
  }

  // RFC 4122 v4 — crypto.randomUUID is widely supported but `crypto.getRandomValues`
  // works on every browser we care about, so synthesise from there as a fallback.
  function uuidv4() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    var hex = [];
    for (var i = 0; i < 16; i++) {
      hex.push((bytes[i] + 0x100).toString(16).slice(1));
    }
    return (
      hex.slice(0, 4).join("") +
      "-" +
      hex.slice(4, 6).join("") +
      "-" +
      hex.slice(6, 8).join("") +
      "-" +
      hex.slice(8, 10).join("") +
      "-" +
      hex.slice(10, 16).join("")
    );
  }

  // ── EXIF orientation parser ─────────────────────────────────────────────
  //
  // Walk the JPEG markers looking for APP1 ("Exif\0\0"), then the TIFF
  // header, then IFD0's Orientation tag (0x0112). Returns 1..8 or 1 if not
  // found / not a JPEG. Reads only the head of the file so it's cheap.

  function readOrientation(buffer) {
    var view = new DataView(buffer);
    if (view.byteLength < 4 || view.getUint16(0) !== 0xffd8) {
      return 1; // Not a JPEG → assume no rotation.
    }
    var offset = 2;
    while (offset < view.byteLength) {
      var marker = view.getUint16(offset);
      offset += 2;
      if (marker === 0xffe1) {
        // APP1
        if (
          view.getUint32(offset + 2) !== 0x45786966 || // "Exif"
          view.getUint16(offset + 6) !== 0x0000
        ) {
          return 1;
        }
        var tiff = offset + 8;
        var little = view.getUint16(tiff) === 0x4949;
        var get16 = function (o) {
          return view.getUint16(o, little);
        };
        var get32 = function (o) {
          return view.getUint32(o, little);
        };
        if (get16(tiff + 2) !== 0x002a) {
          return 1;
        }
        var ifd0 = tiff + get32(tiff + 4);
        var entries = get16(ifd0);
        for (var i = 0; i < entries; i++) {
          var entry = ifd0 + 2 + i * 12;
          if (get16(entry) === 0x0112) {
            return get16(entry + 8) || 1;
          }
        }
        return 1;
      }
      // Skip non-APP1 segments. Stand-alone markers (0xFF01, 0xFFD0–0xFFD7)
      // have no payload; everything else carries a 16-bit length.
      if (marker === 0xffda || (marker & 0xff00) !== 0xff00) {
        return 1;
      }
      var len = view.getUint16(offset);
      offset += len;
    }
    return 1;
  }

  // Apply orientation 1..8 to a canvas context. The caller has already sized
  // the canvas to the post-rotation dimensions.
  function applyOrientation(ctx, orient, w, h) {
    switch (orient) {
      case 2:
        ctx.translate(w, 0);
        ctx.scale(-1, 1);
        break;
      case 3:
        ctx.translate(w, h);
        ctx.rotate(Math.PI);
        break;
      case 4:
        ctx.translate(0, h);
        ctx.scale(1, -1);
        break;
      case 5:
        ctx.rotate(0.5 * Math.PI);
        ctx.scale(1, -1);
        break;
      case 6:
        ctx.rotate(0.5 * Math.PI);
        ctx.translate(0, -h);
        break;
      case 7:
        ctx.rotate(0.5 * Math.PI);
        ctx.translate(w, -h);
        ctx.scale(-1, 1);
        break;
      case 8:
        ctx.rotate(-0.5 * Math.PI);
        ctx.translate(-w, 0);
        break;
      default:
        break; // 1 → identity.
    }
  }

  function loadImage(blob) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(blob);
      var img = new Image();
      img.onload = function () {
        resolve({ img: img, url: url });
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("decode failed"));
      };
      img.src = url;
    });
  }

  function readArrayBuffer(blob, byteCount) {
    return new Promise(function (resolve, reject) {
      var slice = byteCount ? blob.slice(0, byteCount) : blob;
      var reader = new FileReader();
      reader.onload = function () {
        resolve(reader.result);
      };
      reader.onerror = function () {
        reject(reader.error || new Error("read failed"));
      };
      reader.readAsArrayBuffer(slice);
    });
  }

  // Compress a JPEG/PNG/HEIC file. Returns either {blob, dataUrl} (the
  // canonical compressed JPEG) or null when the browser can't decode the
  // file (HEIC fallback path — caller uploads the raw file).
  async function compressFile(file, maxLongEdge, quality) {
    var orient = 1;
    if (/^image\/jpe?g$/i.test(file.type) || /\.jpe?g$/i.test(file.name)) {
      try {
        var head = await readArrayBuffer(file, 65536);
        orient = readOrientation(head);
      } catch (e) {
        orient = 1;
      }
    }
    var loaded;
    try {
      loaded = await loadImage(file);
    } catch (e) {
      return null;
    }
    var img = loaded.img;
    if (!img.naturalWidth || !img.naturalHeight) {
      URL.revokeObjectURL(loaded.url);
      return null; // HEIC fallback: tell caller to upload raw.
    }
    var sw = img.naturalWidth;
    var sh = img.naturalHeight;
    var rotated = orient >= 5 && orient <= 8;
    var dispW = rotated ? sh : sw;
    var dispH = rotated ? sw : sh;
    var scale = Math.min(1, maxLongEdge / Math.max(dispW, dispH));
    var outW = Math.round(dispW * scale);
    var outH = Math.round(dispH * scale);

    var canvas = document.createElement("canvas");
    canvas.width = outW;
    canvas.height = outH;
    var ctx = canvas.getContext("2d");
    // Pre-rotation dimensions for the orientation transform; the source draw
    // size is the un-rotated image.
    applyOrientation(ctx, orient, rotated ? outH : outW, rotated ? outW : outH);
    ctx.drawImage(img, 0, 0, rotated ? outH : outW, rotated ? outW : outH);
    URL.revokeObjectURL(loaded.url);

    return new Promise(function (resolve) {
      canvas.toBlob(
        function (blob) {
          // iOS WebKit (incl. Brave/iOS) occasionally hands back a null or
          // truncated blob from toBlob — treat anything below 1 KB as a
          // failed compression so the caller can fall back to the original
          // file rather than shipping bytes the server can't decode.
          if (!blob || blob.size < 1024) {
            resolve(null);
            return;
          }
          resolve({ blob: blob, dataUrl: canvas.toDataURL("image/jpeg", quality) });
        },
        "image/jpeg",
        quality,
      );
    });
  }

  // ── Date formatting (success state) ─────────────────────────────────────

  function formatSuccessDate(iso, payload) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) {
      return "";
    }
    var month = (payload.monthNames || [])[d.getUTCMonth()] || "";
    return (payload.dateTemplate || "{day} {month} {year}")
      .replace("{day}", String(d.getUTCDate()))
      .replace("{month}", month)
      .replace("{year}", String(d.getUTCFullYear()));
  }

  // ── Init ────────────────────────────────────────────────────────────────

  function initUpload(root) {
    var payloadEl = root.querySelector("[data-upload-payload]");
    if (!payloadEl) {
      return;
    }
    var payload;
    try {
      payload = JSON.parse(payloadEl.textContent);
    } catch (err) {
      return;
    }

    var states = {
      picker: root.querySelector("[data-upload-state-picker]"),
      preview: root.querySelector("[data-upload-state-preview]"),
      uploading: root.querySelector("[data-upload-state-uploading]"),
      validating: root.querySelector("[data-upload-state-validating]"),
      success: root.querySelector("[data-upload-state-success]"),
      failure: root.querySelector("[data-upload-state-failure]"),
    };
    var inputs = root.querySelectorAll("[data-upload-input]");
    // The gallery input (no `capture`) is the canonical re-entry point: the
    // `reset()` and `Change` paths re-click it regardless of which input the
    // user originally opened. The camera input (with `capture="environment"`)
    // is a one-shot affordance — once a photo is taken the user is in preview
    // and any subsequent "change my mind" reverts to the gallery picker.
    var input = inputs[0] || null;

    // The "Take a photo" CTA only makes sense on Android: iOS already shows
    // a Photo Library / Take Photo / Choose Files sheet on a plain file
    // input, and desktop browsers don't have a useful camera-capture path.
    // Default-hide the camera button via CSS; add `is-android` when we
    // positively detect Android so CSS reveals it. UA sniff is the only
    // practical signal; failure mode is graceful (worst case the user sees
    // only the gallery button, which still works).
    var ua = navigator.userAgent || "";
    var isAndroid = /Android/i.test(ua);
    if (isAndroid) {
      root.classList.add("is-android");
    }

    var pickLabel = root.querySelector("[data-upload-pick-label]");
    var ackToggle = root.querySelector("[data-upload-ack-toggle]");
    var ackPanel = root.querySelector("[data-upload-ack-panel]");
    var ackClose = root.querySelector("[data-upload-ack-close]");
    var previewImg = root.querySelector("[data-upload-preview-image]");
    var uploadingImg = root.querySelector("[data-upload-uploading-image]");
    var validatingImg = root.querySelector("[data-upload-validating-image]");
    var previewFrames = root.querySelectorAll("[data-upload-preview-frame]");
    var noPreviewLabels = root.querySelectorAll("[data-upload-preview-no-preview]");
    var confirmBtn = root.querySelector("[data-upload-confirm]");
    var changeBtn = root.querySelector("[data-upload-change]");
    var progressEl = root.querySelector("[data-upload-progress]");
    var progressFill = root.querySelector("[data-upload-progress-fill]");
    var pill = root.querySelector("[data-upload-pill]");
    var successHeading = root.querySelector("[data-upload-success-heading]");
    var successDate = root.querySelector("[data-upload-success-date]");
    var successBody = root.querySelector("[data-upload-success-body]");
    var successViewBtn = root.querySelector("[data-upload-success-view]");
    var failureBody = root.querySelector("[data-upload-failure-body]");
    var failureCta = root.querySelector("[data-upload-failure-cta]");

    // Per-attempt state. `clientToken` is generated when the user taps confirm
    // and is reused across retries (§6.6). `currentBlob` is the post-
    // compression payload; we keep `currentDataUrl` so we can render the
    // photo in success without keeping the original around.
    var clientToken = null;
    var currentFile = null;
    var currentBlob = null;
    var currentDataUrl = null;
    var currentXhr = null;
    var stallTimer = null;
    var responseTimer = null;
    var lastProgressTs = 0;
    var pausedByVisibility = false;
    var validatingStartedAt = 0;

    // Toggle the "cannot show preview" placeholder across all three frames
    // (preview / uploading / validating). Triggered when the browser can't
    // decode the picked file — most commonly HEIC outside Safari, where the
    // canvas pipeline returns null and we end up shipping the raw bytes for
    // the server to transcode. Without this the <img> tags would just render
    // a broken icon.
    function setNoPreview(noPreview) {
      for (var i = 0; i < previewFrames.length; i++) {
        if (noPreview) {
          previewFrames[i].setAttribute("data-upload-no-preview", "");
        } else {
          previewFrames[i].removeAttribute("data-upload-no-preview");
        }
      }
      for (var j = 0; j < noPreviewLabels.length; j++) {
        if (noPreview) {
          noPreviewLabels[j].removeAttribute("hidden");
        } else {
          noPreviewLabels[j].setAttribute("hidden", "");
        }
      }
    }

    function show(name) {
      Object.keys(states).forEach(function (key) {
        var el = states[key];
        if (!el) {
          return;
        }
        if (key === name) {
          el.removeAttribute("hidden");
        } else {
          el.setAttribute("hidden", "");
        }
      });
      root.setAttribute("data-upload-state", name);
      // Outcome states (success / failure) can land off-screen on tall
      // phones — pull the user back to the upload section so the result is
      // visible without manual scrolling. Defer to next frame so the
      // freshly-shown shell has settled into layout first.
      if (name === "success" || name === "failure") {
        var behavior = prefersReducedMotion() ? "auto" : "smooth";
        window.requestAnimationFrame(function () {
          root.scrollIntoView({ behavior: behavior, block: "center" });
        });
      }
    }

    function reset() {
      clientToken = null;
      currentFile = null;
      currentBlob = null;
      currentDataUrl = null;
      for (var i = 0; i < inputs.length; i++) {
        inputs[i].value = "";
      }
      if (confirmBtn) {
        confirmBtn.disabled = false;
      }
      if (progressFill) {
        progressFill.style.width = "0%";
      }
      if (progressEl) {
        progressEl.setAttribute("aria-valuenow", "0");
      }
      setNoPreview(false);
      show("picker");
    }

    function showFailure(code) {
      var f = (payload.failures || {})[code] ||
        (payload.failures || {}).server_error || {
          body: "",
          cta: "",
        };
      // server_error microcopy carries an inline link; the others are plain.
      if (code === "server_error") {
        failureBody.textContent = "";
        failureBody.appendChild(document.createTextNode(f.body_prefix || ""));
        var a = document.createElement("a");
        a.href = "https://ruralhackers.com/contact/";
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = f.body_link || "";
        failureBody.appendChild(a);
        failureBody.appendChild(document.createTextNode(f.body_suffix || ""));
      } else {
        failureBody.textContent = f.body || "";
      }
      failureCta.textContent = f.cta || "";
      failureCta.dataset.failureCode = code;
      show("failure");
    }

    // ── Acknowledgement panel ─────────────────────────────────────────────

    if (ackToggle && ackPanel) {
      ackToggle.addEventListener("click", function () {
        var open = ackPanel.hasAttribute("hidden") ? false : true;
        if (open) {
          ackPanel.setAttribute("hidden", "");
          ackToggle.setAttribute("aria-expanded", "false");
        } else {
          ackPanel.removeAttribute("hidden");
          ackToggle.setAttribute("aria-expanded", "true");
        }
      });
    }
    if (ackClose && ackPanel) {
      ackClose.addEventListener("click", function () {
        ackPanel.setAttribute("hidden", "");
        if (ackToggle) {
          ackToggle.setAttribute("aria-expanded", "false");
          ackToggle.focus();
        }
      });
    }

    // ── Picker → preview ─────────────────────────────────────────────────

    async function handleFileSelection(file) {
      if (!file) {
        return;
      }
      // §6.4 client-side checks: type via accept (a hint), size hard-cap,
      // decode-success (compressFile returns null when the browser can't).
      // An oversized file is a size problem, not a file-type problem — surface
      // the size-specific message so the user knows to pick a smaller photo.
      if (file.size > payload.maxSizeBytes) {
        showFailure("too_large");
        return;
      }
      currentFile = file;
      var compressed;
      try {
        compressed = await compressFile(
          file,
          payload.maxLongEdge,
          payload.jpegQuality,
        );
      } catch (e) {
        compressed = null;
      }
      if (compressed) {
        currentBlob = compressed.blob;
        currentDataUrl = compressed.dataUrl;
      } else if (
        /^image\//i.test(file.type) ||
        /\.(jpe?g|png|heic|heif)$/i.test(file.name)
      ) {
        // §6.4 HEIC fallback widened: any image the canvas pipeline can't
        // produce a usable JPEG for (HEIC on non-WebKit; iOS WebKit's
        // occasional null/truncated toBlob output) is shipped raw. The
        // server accepts JPEG/PNG/HEIC and re-encodes on success.
        currentBlob = file;
        currentDataUrl = null;
      } else {
        showFailure("wrong_file_type");
        return;
      }
      if (currentDataUrl) {
        setNoPreview(false);
        if (previewImg) {
          previewImg.src = currentDataUrl;
        }
      } else {
        // Browser can't decode the file (HEIC outside Safari is the common
        // case) — surface a "cannot show preview" placeholder rather than a
        // broken <img>. The raw bytes still ship; the server transcodes.
        setNoPreview(true);
        if (previewImg) {
          previewImg.removeAttribute("src");
        }
      }
      show("preview");
    }

    inputs.forEach(function (el) {
      el.addEventListener("change", function () {
        var file = el.files && el.files[0];
        handleFileSelection(file);
      });
    });

    if (changeBtn) {
      // §6.4: stay on the preview state until a new file actually arrives. On
      // iOS the native picker sheet hangs around while the rest of the page
      // is interactive; clearing the preview before the user has picked (or
      // cancelled) loses their pending photo for no benefit. Clear the input
      // value so re-selecting the same file still fires `change`.
      changeBtn.addEventListener("click", function () {
        if (input) {
          input.value = "";
          input.click();
        }
      });
    }

    // ── Confirm → upload ─────────────────────────────────────────────────

    function setProgress(percent) {
      var rounded = Math.max(0, Math.min(100, Math.round(percent)));
      if (progressFill) {
        progressFill.style.width = rounded + "%";
      }
      if (progressEl) {
        progressEl.setAttribute("aria-valuenow", String(rounded));
      }
      if (pill && !pausedByVisibility) {
        pill.textContent = (payload.uploadingStatusTemplate || "{percent}%").replace(
          "{percent}",
          String(rounded),
        );
      }
    }

    function onPause() {
      pausedByVisibility = true;
      if (pill) {
        pill.textContent = payload.uploadingPaused || "";
      }
    }

    function onResume() {
      pausedByVisibility = false;
      // Re-emit the last known percentage so the pill regains the live label.
      var p = parseFloat(progressEl ? progressEl.getAttribute("aria-valuenow") : "0");
      setProgress(isNaN(p) ? 0 : p);
    }

    document.addEventListener("visibilitychange", function () {
      if (root.getAttribute("data-upload-state") !== "uploading") {
        return;
      }
      if (document.visibilityState === "hidden") {
        onPause();
      } else {
        onResume();
      }
    });

    function startStallWatch() {
      lastProgressTs = Date.now();
      stallTimer = window.setInterval(function () {
        if (Date.now() - lastProgressTs > (payload.stallTimeoutMs || 30000)) {
          if (currentXhr) {
            currentXhr.abort();
          }
        }
      }, 1000);
    }

    function clearStallWatch() {
      if (stallTimer !== null) {
        window.clearInterval(stallTimer);
        stallTimer = null;
      }
    }

    // Once the bytes are out we're waiting on the server's validation response.
    // The stall watchdog (which only watches upload progress) has been cleared
    // by then, so without this a server-side hang strands the user on
    // "Checking…" forever. Abort after responseTimeoutMs → network failure.
    function startResponseWatch() {
      clearResponseWatch();
      responseTimer = window.setTimeout(function () {
        if (currentXhr) {
          currentXhr.abort();
        }
      }, payload.responseTimeoutMs || 60000);
    }

    function clearResponseWatch() {
      if (responseTimer !== null) {
        window.clearTimeout(responseTimer);
        responseTimer = null;
      }
    }

    // Hold the validating state for at least MIN_VALIDATING_MS before
    // transitioning to success/failure. Fast server responses would
    // otherwise blink past the overlay; the floor gives the user a moment
    // to register that a check happened.
    function transitionFromValidating(fn) {
      var elapsed = Date.now() - validatingStartedAt;
      var remaining = Math.max(0, MIN_VALIDATING_MS - elapsed);
      if (remaining === 0) {
        fn();
      } else {
        window.setTimeout(fn, remaining);
      }
    }

    function startUpload() {
      if (!currentBlob) {
        return;
      }
      if (!clientToken) {
        clientToken = uuidv4();
      }
      // Double-tap protection (§6.6): disable on first tap. The token
      // protects server-side too.
      if (confirmBtn) {
        confirmBtn.disabled = true;
      }
      pausedByVisibility = false;
      setProgress(0);
      if (uploadingImg && currentDataUrl) {
        uploadingImg.src = currentDataUrl;
      }
      show("uploading");

      var form = new FormData();
      var name = currentFile && currentFile.name ? currentFile.name : "upload.jpg";
      form.append("file", currentBlob, name);
      form.append("station_slug", payload.stationSlug || "");

      var xhr = new XMLHttpRequest();
      currentXhr = xhr;
      xhr.open("POST", payload.endpoint || "/api/upload");
      xhr.setRequestHeader("X-Client-Token", clientToken);
      xhr.upload.addEventListener("progress", function (ev) {
        lastProgressTs = Date.now();
        if (ev.lengthComputable) {
          setProgress((ev.loaded / ev.total) * 100);
        }
      });
      xhr.upload.addEventListener("load", function () {
        // Bytes are out; we're now waiting on the server.
        clearStallWatch();
        startResponseWatch();
        setProgress(100);
        if (validatingImg && currentDataUrl) {
          validatingImg.src = currentDataUrl;
        }
        validatingStartedAt = Date.now();
        show("validating");
      });
      xhr.addEventListener("load", function () {
        clearStallWatch();
        clearResponseWatch();
        currentXhr = null;
        var data = null;
        try {
          data = JSON.parse(xhr.responseText);
        } catch (e) {
          data = null;
        }
        transitionFromValidating(function () {
          if (xhr.status >= 200 && xhr.status < 300 && data && data.ok) {
            handleSuccess(data);
          } else if (data && data.error) {
            showFailure(data.error);
          } else if (xhr.status === 413) {
            // Reverse-proxy body-size cap (below our 30 MB limit) — no JSON
            // body, but it's a size problem, not a generic server error.
            showFailure("too_large");
          } else {
            showFailure("server_error");
          }
        });
      });
      xhr.addEventListener("error", function () {
        clearStallWatch();
        clearResponseWatch();
        currentXhr = null;
        showFailure("network");
      });
      xhr.addEventListener("abort", function () {
        clearStallWatch();
        clearResponseWatch();
        currentXhr = null;
        showFailure("network");
      });
      startStallWatch();
      xhr.send(form);
    }

    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        if (confirmBtn.disabled) {
          return;
        }
        startUpload();
      });
    }

    // ── Success ───────────────────────────────────────────────────────────

    function handleSuccess(data) {
      if (successHeading) {
        successHeading.textContent = payload.successHeading || "";
      }
      if (successDate) {
        successDate.textContent = formatSuccessDate(data.captured_at, payload);
      }
      if (successBody) {
        successBody.textContent = payload.successBody || "";
      }
      if (successViewBtn) {
        successViewBtn.textContent = payload.viewCta || "";
      }
      // §6.7: refresh the viewer above to include the new frame, parked at
      // it. The viewer module exposes `window.ReFrameViewer.append(frame)`;
      // skip if absent (no viewer when this was the first photo — the
      // success CTA handles that case by reloading to #viewer).
      if (window.ReFrameViewer && typeof window.ReFrameViewer.append === "function") {
        window.ReFrameViewer.append({
          captured_at: data.captured_at,
          viewer_url: data.viewer_url,
          thumb_url: data.thumb_url,
        });
      }
      // Increment the "N contributions since {month} {year}" stats line
      // in the about section so the count updates live.
      bumpStatsLine();
      show("success");
    }

    function bumpStatsLine() {
      var el = document.querySelector("[data-station-stats]");
      if (!el) {
        return;
      }
      var template = el.getAttribute("data-stats-template");
      if (!template) {
        return;
      }
      var count = parseInt(el.getAttribute("data-stats-count") || "0", 10) + 1;
      var month = el.getAttribute("data-stats-month") || "";
      var year = el.getAttribute("data-stats-year") || "";
      el.setAttribute("data-stats-count", String(count));
      el.textContent = template
        .replace("{count}", String(count))
        .replace("{month}", month)
        .replace("{year}", String(year));
    }

    if (successViewBtn) {
      successViewBtn.addEventListener("click", function () {
        // The viewer is the page hero — scroll to the top of the page
        // rather than #viewer, otherwise the fixed nav bar hides the top
        // of the viewer. The viewer module always exposes append() now
        // (a single-mode page initialises just like a full-mode one), so
        // we don't need a reload fallback.
        window.scrollTo({
          top: 0,
          behavior: prefersReducedMotion() ? "auto" : "smooth",
        });
      });
    }

    // ── Failure recovery ──────────────────────────────────────────────────

    if (failureCta) {
      failureCta.addEventListener("click", function () {
        var code = failureCta.dataset.failureCode;
        if (code === "network" || code === "server_error") {
          // §6.5: retry uses the same idempotency token (§6.6).
          startUpload();
        } else if (code === "not_ready") {
          // The station isn't accepting photos — re-opening the picker would
          // just fail again. Return to the picker quietly ("OK").
          reset();
        } else {
          // wrong_file_type / too_large / too_small / doesnt_match / too_blurry
          // → back to picker with a fresh token next time.
          reset();
          if (input) {
            input.click();
          }
        }
      });
    }

    // ── QR fragment arrival (§3.4) ───────────────────────────────────────
    //
    // If the page loads with `#subir` or `#upload`, scroll the upload section
    // into view (scroll-margin handles the offset) and pulse the picker CTA
    // briefly. The fragment-arrival check is anchor-id-aware so we don't
    // pulse on any other in-page navigation.

    function maybePulseFromFragment() {
      var hash = (window.location.hash || "").replace(/^#/, "");
      if (hash !== payload.anchorId && hash !== "subir" && hash !== "upload") {
        return;
      }
      // The browser handles the initial scroll; we just emphasise the CTA.
      if (pickLabel) {
        pickLabel.classList.add("upload__cta--pulse");
        window.setTimeout(function () {
          pickLabel.classList.remove("upload__cta--pulse");
        }, 1800);
      }
    }
    maybePulseFromFragment();
    window.addEventListener("hashchange", maybePulseFromFragment);
  }

  ready(function () {
    var roots = document.querySelectorAll("[data-upload-root]");
    for (var i = 0; i < roots.length; i++) {
      initUpload(roots[i]);
    }
  });
})();
