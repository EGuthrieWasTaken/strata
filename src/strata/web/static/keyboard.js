/*
 * Two small progressive enhancements, both optional: every control here
 * also has a plain clickable/tappable target (or, for the screening
 * shortcuts, an `accesskey`), so every page is fully operable with this
 * script disabled (docs/spec/11-web-ui.md §5's hard requirement) -- this
 * file only makes the common path faster.
 *
 *  1. Single-key shortcuts for the screening surface (§3.1 S1/S3).
 *  2. Auto-resubmit a form as GET when a radio input changes, for the
 *     criteria editor's live impact preview (§4: "MUST update as the
 *     direction radio changes"). Opt in per form via
 *     `data-auto-submit-on-change="<radio name>"`.
 *
 * No external requests, no build step, no dependency: this is the entire
 * client-side script strata ships (§5's "total shipped JavaScript SHOULD
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

  document.querySelectorAll("form[data-auto-submit-on-change]").forEach(function (form) {
    var radioName = form.dataset.autoSubmitOnChange;
    var previewButton = form.querySelector('button[formmethod="get"]');
    form.querySelectorAll('input[type="radio"][name="' + radioName + '"]').forEach(function (radio) {
      radio.addEventListener("change", function () {
        // Submit via the "Preview" button specifically, so its
        // formmethod="get" override (not the form's own default POST) is
        // what actually fires.
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
        announce("recording decision…");
        button.click();
      }
      return;
    }

    if (key >= "1" && key <= "9") {
      var checkbox = form.querySelector('input[data-shortcut-digit="' + key + '"]');
      if (!checkbox) return;
      event.preventDefault();
      checkbox.checked = !checkbox.checked;
      if (form.dataset.requireExclusionReason === "true" && checkbox.checked) {
        var excludeButton = form.querySelector('button[name="decision"][value="exclude"]');
        if (excludeButton) {
          announce("recording decision…");
          excludeButton.click();
        }
      }
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
