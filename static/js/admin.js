// Admin (§7.5) — soft-delete confirmation + photo-preview lightbox.
// Quitar forms carry `data-remove-form`; we intercept submit and open a shared
// confirmation <dialog> that carries the optional removal-reason field, so the
// reason unambiguously belongs to the delete action. No-JS path still posts the
// form (reason omitted); no-<dialog> browsers fall back to the native confirm.
// Photo thumbnails carry `data-photo-preview`; click opens a shared <dialog>
// with the viewer-size image. Backdrop click + ESC + the X button all close.
(function () {
  "use strict";

  // Script is loaded `defer`, so DOM is already parsed by the time this runs.
  // No DOMContentLoaded gate needed — wiring up directly is more reliable.

  // ── Quitar confirmation ────────────────────────────────────────────────
  // Clicking a card's Quitar button opens a shared <dialog> populated with that
  // photo's context plus the optional reason field; "Sí, quitar" injects the
  // reason as a hidden field and submits the originating form natively.
  var removeDialog = document.getElementById("admin-remove-confirm");
  var removeDialogSupportsModal =
    removeDialog && typeof removeDialog.showModal === "function";
  var pendingRemoveForm = null;

  if (removeDialog) {
    var rReason = removeDialog.querySelector("[data-confirm-reason]");
    var rStation = removeDialog.querySelector("[data-confirm-station]");
    var rDate = removeDialog.querySelector("[data-confirm-date]");
    var rThumb = removeDialog.querySelector("[data-confirm-thumb]");
    var rCancel = removeDialog.querySelector("[data-confirm-cancel]");
    var rSubmit = removeDialog.querySelector("[data-confirm-submit]");

    var closeRemoveDialog = function () {
      pendingRemoveForm = null;
      try {
        removeDialog.close();
      } catch (e) {
        /* not open — ignore */
      }
    };

    rCancel.addEventListener("click", closeRemoveDialog);

    // Backdrop click + native cancel (ESC) + close (the × close-form) clear state.
    removeDialog.addEventListener("click", function (event) {
      if (event.target === removeDialog) {
        closeRemoveDialog();
      }
    });
    removeDialog.addEventListener("cancel", function () {
      pendingRemoveForm = null;
    });
    removeDialog.addEventListener("close", function () {
      pendingRemoveForm = null;
    });

    rSubmit.addEventListener("click", function () {
      if (!pendingRemoveForm) {
        return;
      }
      var form = pendingRemoveForm;
      // Inject the reason as a hidden field, then submit natively —
      // form.submit() bypasses the submit listener so the dialog won't re-open.
      var hidden = form.querySelector('input[name="removal_reason"]');
      if (!hidden) {
        hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "removal_reason";
        form.appendChild(hidden);
      }
      hidden.value = rReason.value;
      pendingRemoveForm = null;
      form.submit();
    });
  }

  document.querySelectorAll("form[data-remove-form]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var message = form.getAttribute("data-confirm-message") || "";

      if (!removeDialog || !removeDialogSupportsModal) {
        // Fallback: native confirm (no reason capture).
        if (!window.confirm(message)) {
          event.preventDefault();
        }
        return;
      }

      event.preventDefault();
      pendingRemoveForm = form;

      var card = form.closest(".admin-photo-card, .admin-rail-photos__item");
      var preview = card && card.querySelector("[data-photo-preview]");
      var thumb = preview && preview.querySelector("img");

      rReason.value = "";
      if (rStation) {
        rStation.textContent = preview
          ? preview.getAttribute("data-station-name") || ""
          : "";
      }
      if (rDate) {
        rDate.textContent = preview
          ? preview.getAttribute("data-captured-at") || ""
          : "";
      }
      if (rThumb && thumb) {
        rThumb.src = thumb.src;
      }

      removeDialog.showModal();
      rReason.focus();
    });
  });

  // ── Generic action confirmation ────────────────────────────────────────
  // Any `form[data-admin-confirm]` (station archive, location delete) opens a
  // shared <dialog> populated from data-confirm-title / -body / -label. "Confirm"
  // submits the form natively; no-<dialog> browsers fall back to native confirm.
  var actionDialog = document.getElementById("admin-action-confirm");
  var actionSupportsModal =
    actionDialog && typeof actionDialog.showModal === "function";
  var pendingActionForm = null;

  if (actionDialog) {
    var aTitle = actionDialog.querySelector("[data-action-title]");
    var aBody = actionDialog.querySelector("[data-action-body]");
    var aCancel = actionDialog.querySelector("[data-action-cancel]");
    var aSubmit = actionDialog.querySelector("[data-action-submit]");

    var closeActionDialog = function () {
      pendingActionForm = null;
      try {
        actionDialog.close();
      } catch (e) {
        /* not open — ignore */
      }
    };

    aCancel.addEventListener("click", closeActionDialog);
    actionDialog.addEventListener("click", function (event) {
      if (event.target === actionDialog) {
        closeActionDialog();
      }
    });
    actionDialog.addEventListener("cancel", function () {
      pendingActionForm = null;
    });
    actionDialog.addEventListener("close", function () {
      pendingActionForm = null;
    });

    aSubmit.addEventListener("click", function () {
      if (!pendingActionForm) {
        return;
      }
      var form = pendingActionForm;
      pendingActionForm = null;
      form.submit();
    });
  }

  document.querySelectorAll("form[data-admin-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var title = form.getAttribute("data-confirm-title") || "¿Continuar?";

      if (!actionDialog || !actionSupportsModal) {
        if (!window.confirm(title)) {
          event.preventDefault();
        }
        return;
      }

      event.preventDefault();
      pendingActionForm = form;

      aTitle.textContent = title;
      aBody.textContent = form.getAttribute("data-confirm-body") || "";
      aSubmit.textContent = form.getAttribute("data-confirm-label") || "Confirmar";

      actionDialog.showModal();
      aSubmit.focus();
    });
  });

  // ── Autoslug: derive slug from a sibling name field as the user types ──
  // The slug input is rendered editable in the HTML (no-JS users get the
  // existing form). On init we mark it readonly, insert an Editar button next
  // to the existing hint, and mirror a slugified name → slug input on every
  // keystroke in the source. Clicking Editar removes readonly and detaches the
  // source→target mirror. While unlocked, the slug is re-slugified on input
  // and space keydown is blocked as a visible affordance.

  function slugify(value) {
    return value
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  // Lenient variant for live-editing in the slug field. Keeps leading/trailing
  // hyphens so the user can type "foo-" and continue with the next word
  // without the partial separator being eaten as they go.
  function cleanSlugLive(value) {
    return value
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/-{2,}/g, "-");
  }

  document
    .querySelectorAll("[data-admin-autoslug]")
    .forEach(function (container) {
      var source = container.querySelector("[data-autoslug-source]");
      var target = container.querySelector("[data-autoslug-target]");
      var targetField = container.querySelector("[data-autoslug-target-field]");
      if (!source || !target || !targetField) {
        return;
      }

      target.setAttribute("readonly", "");

      var editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "admin-form__slug-edit";
      editBtn.setAttribute("data-autoslug-edit", "");
      editBtn.textContent = "Editar";

      // Place the button next to the existing hint when present; otherwise
      // append it to the field label so it sits below the input.
      var hint = targetField.querySelector(".admin-form__hint");
      if (hint) {
        hint.appendChild(document.createTextNode(" · "));
        hint.appendChild(editBtn);
      } else {
        targetField.appendChild(editBtn);
      }

      var detached = false;

      source.addEventListener("input", function () {
        if (detached) {
          return;
        }
        target.value = slugify(source.value);
      });

      editBtn.addEventListener("click", function () {
        detached = true;
        target.removeAttribute("readonly");
        editBtn.hidden = true;
        target.focus();
        target.select();
      });

      // Block space at keydown — visible affordance that slugs can't contain
      // spaces. Covers both "Space" code and " " key (some IMEs / mobiles).
      target.addEventListener("keydown", function (event) {
        if (event.key === " " || event.code === "Space") {
          event.preventDefault();
        }
      });

      // Re-slugify on every input event (covers paste, accents, uppercase,
      // punctuation). Fires only after unlock — readonly inputs don't emit
      // input events. Use the lenient variant so the user can still type a
      // separator hyphen between words; trim leading/trailing hyphens on blur.
      target.addEventListener("input", function () {
        var cleaned = cleanSlugLive(target.value);
        if (cleaned !== target.value) {
          target.value = cleaned;
          var end = cleaned.length;
          try {
            target.setSelectionRange(end, end);
          } catch (e) {
            /* some input types reject setSelectionRange; ignore */
          }
        }
      });

      target.addEventListener("blur", function () {
        var trimmed = target.value.replace(/^-+|-+$/g, "");
        if (trimmed !== target.value) {
          target.value = trimmed;
        }
      });
    });

  // ── Toast ──────────────────────────────────────────────────────────────
  // A `data-admin-toast` element (rendered server-side from a ?notice= param)
  // fades in via CSS, auto-dismisses after a few seconds, and can be closed
  // early with its × button. No-JS users still see it — it just stays put.
  var toast = document.querySelector("[data-admin-toast]");
  if (toast) {
    var hideToast = function () {
      toast.classList.add("admin-toast--out");
      toast.addEventListener(
        "transitionend",
        function () {
          if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
          }
        },
        { once: true }
      );
    };
    var toastTimer = window.setTimeout(hideToast, 4000);
    var toastClose = toast.querySelector(".admin-toast__close");
    if (toastClose) {
      toastClose.addEventListener("click", function () {
        window.clearTimeout(toastTimer);
        hideToast();
      });
    }
  }

  // ── Unsaved-changes guard ──────────────────────────────────────────────
  // A form marked `data-admin-dirty-warn` (the edit-location form) warns the
  // user before they navigate away with unsaved edits. The native beforeunload
  // prompt covers every exit — the back link, tab close, refresh — so it is the
  // single guard (a separate confirm on the back link would double-prompt). The
  // flag clears on submit so saving never warns. Placed before the photo-preview
  // block, which returns early when its dialog is absent (it is on these pages).
  var dirtyForm = document.querySelector("[data-admin-dirty-warn]");
  if (dirtyForm) {
    var isDirty = false;
    // Listen on the document rather than the form node so we also catch
    // form-associated controls that live OUTSIDE the <form> — the station
    // status <select> sits in the right rail and is wired in via
    // `form="station-form"`, so its change events never bubble to the form.
    // `event.target.form` resolves to the associated form for any control,
    // inside or out. `change` covers the <select>; `input` covers typing.
    var markDirty = function (event) {
      if (event.target.form === dirtyForm) {
        isDirty = true;
      }
    };
    document.addEventListener("input", markDirty);
    document.addEventListener("change", markDirty);
    dirtyForm.addEventListener("submit", function () {
      isDirty = false;
    });
    window.addEventListener("beforeunload", function (event) {
      if (isDirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }

  // ── Photo preview lightbox ─────────────────────────────────────────────
  var dialog = document.getElementById("admin-photo-preview");
  if (!dialog) {
    return;
  }

  var dialogImage = dialog.querySelector("[data-dialog-image]");
  var dialogStation = dialog.querySelector("[data-dialog-station]");
  var dialogDate = dialog.querySelector("[data-dialog-date]");

  var supportsModal =
    typeof dialog.showModal === "function" &&
    typeof dialog.close === "function";

  // Event delegation — one click listener on document catches every trigger,
  // including triggers added after page load (not the case here, but cheaper
  // than attaching N listeners and also more resilient).
  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-photo-preview]");
    if (!btn) {
      return;
    }

    var viewerUrl = btn.getAttribute("data-viewer-url") || "";

    if (!supportsModal) {
      window.open(viewerUrl, "_blank", "noopener");
      return;
    }

    var width = btn.getAttribute("data-viewer-width") || "";
    var height = btn.getAttribute("data-viewer-height") || "";
    var stationName = btn.getAttribute("data-station-name") || "";
    var capturedAt = btn.getAttribute("data-captured-at") || "";

    dialogImage.src = viewerUrl;
    if (width) dialogImage.setAttribute("width", width);
    if (height) dialogImage.setAttribute("height", height);
    dialogImage.alt = stationName ? "Foto de " + stationName : "";
    dialogStation.textContent = stationName;
    dialogDate.textContent = capturedAt;

    try {
      dialog.showModal();
    } catch (err) {
      // showModal throws if the dialog is already open. Recover by closing
      // and reopening.
      try {
        dialog.close();
      } catch (e) {
        /* swallow */
      }
      dialog.showModal();
    }
  });

  // Backdrop click closes — when the click lands on the ::backdrop pseudo,
  // the event target is the dialog element itself.
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) {
      dialog.close();
    }
  });
})();
