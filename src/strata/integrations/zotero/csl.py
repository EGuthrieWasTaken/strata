"""Reading the CSL-JSON Zotero attaches to an item, as running Zoteros really send it.

Implements openspec:zotero-integration#transport-selection (reading). What was seen from a running
Zotero 10 (`tests/fixtures/zotero/captured/10/`, `docs/zotero-real-run.md`) and is handled here:

- The Web API sends `csljson` as an object. The desktop app's local API sends it as a *string*
  holding JSON, and that JSON is a one-element list.
- `issued.date-parts` are numbers for a date Zotero could parse, and strings otherwise: the local
  API sends `[["2008", 11]]`, and a date typed as `11/1984` comes from the Web API as `[["1984"]]`.
- A PMID or PMCID kept in the item's `extra` (`PMID: 123`) is exported as CSL `note`, never as
  `PMID`; only an item type with a native PMID field exports `PMID`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_DATE_FIELDS = ("issued", "accessed", "original-date", "submitted", "event-date")
_NOTE_LINE_RE = re.compile(r"^\s*(PMID|PMCID)\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


def read_csl(value: Any) -> dict[str, Any] | None:
    """The item's CSL-JSON as a dict fit for a record, or `None` if this is not CSL-JSON.

    Accepts an object, a list holding one, or a string holding either; drops Zotero's `id`.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, Mapping):
        return None
    csl = {str(k): v for k, v in value.items() if k != "id"}
    for name in _DATE_FIELDS:
        if name in csl:
            fixed = _date(csl[name])
            if fixed is None:
                del csl[name]
            else:
                csl[name] = fixed
    for label, found in _NOTE_LINE_RE.findall(str(csl.get("note") or "")):
        name = label.upper()
        if not csl.get(name):
            csl[name] = found
    return csl


def _date(value: Any) -> dict[str, Any] | None:
    """A CSL date whose parts are integers; `None` if no usable year is left."""
    if not isinstance(value, Mapping):
        return None
    rows = value.get("date-parts")
    if not isinstance(rows, list):
        return dict(value) if value.get("raw") or value.get("literal") else None
    fixed: list[list[int]] = []
    for row in rows:
        parts: list[int] = []
        for part in row if isinstance(row, list) else []:
            number = _whole(part)
            if number is None:
                break  # what follows a part that is not a number cannot be trusted either
            parts.append(number)
        if parts:
            fixed.append(parts)
    if not fixed:
        return None
    return {**value, "date-parts": fixed}


def _whole(part: Any) -> int | None:
    if isinstance(part, bool):
        return None
    if isinstance(part, int):
        return part
    if isinstance(part, str) and part.strip().isdigit():
        return int(part.strip())
    return None
