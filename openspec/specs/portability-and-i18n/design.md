# Design: portability-and-i18n

*Informative.* The requirements are in [spec.md](spec.md).

## Why all three platforms on every commit

Collaborators on a review use whatever machine their institution gave them.
Byte-identity guarantees that hold only on Linux are not guarantees, so CI runs
the full suite on Linux, macOS, and Windows for every pull request, not just at
release.

## Windows specifics

Path length limits, `core.autocrlf` (forced to LF by `.gitattributes`),
case-insensitive filesystems, and reserved names (`CON`, `PRN`, `NUL`, `AUX`)
each break naive tools. Ids restricted to `[a-z0-9_]` and sanitised filenames
avoid all four.

## Unicode is ordinary input

Non-Latin author names, titles, and abstracts are the normal case in evidence
synthesis, and reviewers working in non-English literature are ordinary users.
Nothing may assume Latin script or left-to-right text.

## Internationalisation from day one

Retrofitting i18n is far more expensive than designing for it, so user-facing
strings are externalised even though only English ships first. Generated files
always use `.` as the decimal separator while displayed prose follows the
locale — mixing these is a classic source of corrupted CSV exports in European
locales.
