/*
 * Drag-and-drop for file choosers: a convenience over a real <input type="file">, never a
 * replacement for it (openspec:web-ui#drag-and-drop-is-an-enhancement).
 *
 * Every page that takes files works without this script: the input is an ordinary file chooser, the
 * form posts as usual, and the keyboard reaches all of it. This script only (1) lets files be dropped
 * on the chooser's box, by handing them to that same input, (2) lists the chosen files by name and
 * size, and (3) says what it did in the page's live region and in visible text, so a screen reader
 * and a person who cannot see colour both know.
 *
 * It never submits anything, never reads a file, and makes no request: the form is posted by the
 * browser exactly as it would have been, so every check the server makes is the same one.
 */
(function () {
  "use strict";

  function announce(text) {
    var region = document.getElementById("announcer");
    if (region) region.textContent = text;
  }

  function size(bytes) {
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  function hasFiles(event) {
    var types = event.dataTransfer && event.dataTransfer.types;
    return !!types && Array.prototype.indexOf.call(types, "Files") !== -1;
  }

  // Files only: a dropped folder arrives as a pseudo-file in some browsers, so ask the entry API.
  function filesFrom(dataTransfer) {
    var files = [];
    var folders = 0;
    var items = dataTransfer.items;
    if (items && items.length) {
      for (var i = 0; i < items.length; i++) {
        if (items[i].kind !== "file") continue;
        var entry = items[i].webkitGetAsEntry ? items[i].webkitGetAsEntry() : null;
        if (entry && entry.isDirectory) {
          folders++;
          continue;
        }
        var file = items[i].getAsFile();
        if (file) files.push(file);
      }
    } else {
      for (var j = 0; j < dataTransfer.files.length; j++) files.push(dataTransfer.files[j]);
    }
    return { files: files, folders: folders };
  }

  document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
    var input = zone.querySelector('input[type="file"]');
    var list = zone.querySelector("[data-dropzone-list]");
    var hint = zone.querySelector("[data-dropzone-hint]");
    if (!input || !list || !hint) return;

    var note = document.createElement("span");
    note.className = "dropzone-state";
    note.setAttribute("data-dropzone-state", "");
    hint.parentNode.insertBefore(note, hint.nextSibling);

    var jsOnly = zone.querySelector(".dropzone-js-only");
    if (jsOnly) jsOnly.hidden = false;

    function say(text) {
      note.textContent = text;
    }

    function refresh() {
      while (list.firstChild) list.removeChild(list.firstChild);
      var names = [];
      for (var i = 0; i < input.files.length; i++) {
        var item = document.createElement("li");
        item.textContent = input.files[i].name + " (" + size(input.files[i].size) + ")";
        list.appendChild(item);
        names.push(input.files[i].name);
      }
      if (names.length) {
        var text = names.length + (names.length === 1 ? " file" : " files") + " chosen: " + names.join(", ");
        say(text);
        announce(text);
      } else {
        say("");
      }
    }

    input.addEventListener("change", refresh);

    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        if (!hasFiles(event)) return;
        event.preventDefault();
        zone.classList.add("is-dragging");
        say("Drop to attach these files.");
      });
    });

    zone.addEventListener("dragleave", function (event) {
      if (event.relatedTarget && zone.contains(event.relatedTarget)) return;
      zone.classList.remove("is-dragging");
      refresh();
    });

    zone.addEventListener("drop", function (event) {
      event.preventDefault(); // never let the browser open a dropped file in this tab
      zone.classList.remove("is-dragging");
      if (!event.dataTransfer || !hasFiles(event)) {
        say("Only files can be dropped here. Nothing was attached.");
        announce("Only files can be dropped here. Nothing was attached.");
        return;
      }
      var found = filesFrom(event.dataTransfer);
      if (!found.files.length) {
        var none = "Folders cannot be dropped here; choose the files inside. Nothing was attached.";
        say(none);
        announce(none);
        return;
      }
      var transfer = new DataTransfer();
      found.files.forEach(function (file) {
        transfer.items.add(file);
      });
      input.files = transfer.files;
      refresh();
      if (found.folders) {
        var skipped = " (" + found.folders + (found.folders === 1 ? " folder was" : " folders were") + " ignored.)";
        say(note.textContent + skipped);
        announce(note.textContent);
      }
    });
  });
})();
