/*
 * A few small progressive enhancements, all optional: every control here
 * also has a plain clickable/tappable target (or, for the screening
 * shortcuts, an `accesskey`), so every page is fully operable with this
 * script disabled (openspec:web-ui#technology's hard requirement) -- this
 * file only makes the common path faster.
 *
 *  1. Single-key shortcuts for the screening surface (openspec:web-ui#screening-surface-requirements S1/S3).
 *  2. Auto-preview a form (post it with intent=preview) when a radio input changes, for the
 *     criteria editor's live impact preview (openspec:web-ui#criteria-editor-impact-preview: "MUST update as the
 *     direction radio changes"). Opt in per form via
 *     `data-auto-submit-on-change="<radio name>"`.
 *
 *  3. The extraction coding form: "@" in a value jumps to its source locator.
 *
 *  4. A table's scroll box is a tab stop only while the table is wider than the box (without this
 *     script it always is one, so it can always be scrolled from the keyboard).
 *
 * No external requests, no build step, no dependency: this is the entire
 * client-side script strata ships (openspec:web-ui#technology's "total shipped JavaScript SHOULD
 * stay under 50 KB uncompressed" budget).
 */
(function () {
  "use strict";

  function isTypingTarget(el) {
    if (!el) return false;
    var tag = el.tagName;
    return tag === "TEXTAREA" || tag === "INPUT" || el.isContentEditable;
  }

  function announce(text) {
    var region = document.getElementById("announcer");
    if (region) region.textContent = text;
  }

  // A message beside the decision buttons (the screening screens have the element).
  function hint(text) {
    var box = document.getElementById("screen-hint");
    if (!box) return;
    box.textContent = text;
    box.hidden = !text;
    if (text) announce(text);
  }

  // 4. Scroll boxes: focusable only when there is something to scroll, so a keyboard user does not
  //    stop at a table that fits. Checked again whenever the box changes size.
  var scrollBoxes = document.querySelectorAll(".table-scroll");
  function fitScrollBox(box) {
    if (box.scrollWidth > box.clientWidth + 1) {
      box.setAttribute("tabindex", "0");
    } else {
      box.removeAttribute("tabindex");
    }
  }
  scrollBoxes.forEach(fitScrollBox);
  if (scrollBoxes.length) {
    if (typeof ResizeObserver === "function") {
      var watcher = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) { fitScrollBox(entry.target); });
      });
      scrollBoxes.forEach(function (box) { watcher.observe(box); });
    } else {
      window.addEventListener("resize", function () { scrollBoxes.forEach(fitScrollBox); });
    }
  }

  // Text that describes what this script adds is shown only when it runs.
  document.querySelectorAll(".js-only-hint").forEach(function (el) { el.hidden = false; });

  document.querySelectorAll("form[data-auto-submit-on-change]").forEach(function (form) {
    var radioName = form.dataset.autoSubmitOnChange;
    var previewButton = form.querySelector('button[name="intent"][value="preview"]');
    form.querySelectorAll('input[type="radio"][name="' + radioName + '"]').forEach(function (radio) {
      radio.addEventListener("change", function () {
        // Submit via the "Preview" button specifically, so the server
        // receives intent=preview and shows the impact instead of saving.
        if (previewButton && typeof form.requestSubmit === "function") {
          form.requestSubmit(previewButton);
        } else if (typeof form.requestSubmit === "function") {
          form.requestSubmit();
        } else {
          form.submit();
        }
      });
    });
  });

  // 3. The extraction coding form: "@" in a value jumps to that value's source locator, so
  //    entering one is a single keystroke (openspec:web-ui, extraction screens).
  document.querySelectorAll("input[data-source-input]").forEach(function (input) {
    input.addEventListener("keydown", function (event) {
      if (event.key !== "@" || event.metaKey || event.ctrlKey || event.altKey) return;
      var target = document.getElementById(input.dataset.sourceInput);
      if (target) {
        event.preventDefault();
        target.focus();
      }
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;

    var form = document.getElementById("screen-form");
    if (!form) return;

    var key = event.key;
    var typing = isTypingTarget(document.activeElement);

    if (key === "," && !typing) {
      var note = document.getElementById("note-field");
      if (note) {
        note.focus();
        event.preventDefault();
      }
      return;
    }

    if (typing) return; // never hijack keys once the reviewer is typing a note

    if (key === "i" || key === "e" || key === "m" || key === "k") {
      var decisionValue = key === "i" ? "include" : key === "e" ? "exclude" :
        key === "m" ? "maybe" : "keep"; // "k"eep previous, /rescreen only
      var button = form.querySelector('button[name="decision"][value="' + decisionValue + '"]');
      if (button) {
        event.preventDefault();
        if (decisionValue === "exclude" && form.dataset.requireExclusionReason === "true" &&
            !form.querySelector('input[name="criteria"]:checked')) {
          // Nothing is sent: say what is missing where the reviewer is looking.
          hint("Tick at least one reason first (keys 1 to 9), then press e to exclude.");
          return;
        }
        announce("recording decision…");
        button.click();
      }
      return;
    }

    if (key >= "1" && key <= "9") {
      // A digit only ticks or unticks a reason. It never records a decision: a stray key must
      // not exclude a record (the exclusion is recorded by `e`).
      var checkbox = form.querySelector('input[data-shortcut-digit="' + key + '"]');
      if (!checkbox) return;
      event.preventDefault();
      checkbox.checked = !checkbox.checked;
      hint("");
      announce(checkbox.value + (checkbox.checked ? " ticked" : " unticked") +
        "; press e to exclude");
      return;
    }

    if (key === "s") {
      var skipLink = document.getElementById("skip-link");
      if (skipLink) {
        event.preventDefault();
        skipLink.click();
      }
      return;
    }

    if (key === "u") {
      var undoLink = document.getElementById("undo-link");
      if (undoLink) {
        event.preventDefault();
        undoLink.click();
      }
    }
  });
})();
