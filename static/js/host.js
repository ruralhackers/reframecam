/* Host form — light client-side polish:
   - strip whitespace from the email field as it's typed or pasted
   - validate email format on blur, surfacing an inline error
   - clear the inline error as soon as the user resumes editing
   The server-side validator in app/main.py is still the source of truth. */

(function () {
  const emailInput = document.getElementById("host-email");
  if (!emailInput) return;
  const errorEl = document.getElementById("host-email-error");
  const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

  function setInvalid(invalid) {
    emailInput.classList.toggle("host-form__input--invalid", invalid);
    if (errorEl) errorEl.hidden = !invalid;
  }

  // Block the spacebar before it ever lands in the field. Covers the
  // common typed-by-mistake case so the user never sees a space flash in.
  emailInput.addEventListener("keydown", (e) => {
    if (e.key === " ") {
      e.preventDefault();
    }
  });

  // Backstop for paste / drag-drop / mobile autocorrect / IME insertion —
  // anything that bypasses keydown still gets stripped here.
  emailInput.addEventListener("input", () => {
    const stripped = emailInput.value.replace(/\s+/g, "");
    if (stripped !== emailInput.value) {
      emailInput.value = stripped;
    }
    setInvalid(false);
  });

  emailInput.addEventListener("blur", () => {
    const value = emailInput.value.trim();
    if (!value) {
      setInvalid(false);
      return;
    }
    setInvalid(!EMAIL_RE.test(value));
  });
})();
