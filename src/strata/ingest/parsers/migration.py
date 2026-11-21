"""Exports from Rayyan, Covidence and EPPI-Reviewer: their records, and the screening decisions
they carry (openspec:literature-import#migration-imports-from-incumbent-tools).

`strata import --format rayyan|covidence|eppi-json` reads the records; `strata screen --from`
reads the decisions in the same file and records them, attributed to the actor named by `--by`
and marked `imported: true`, because their independence cannot be verified.

**Written from each tool's published export format, not from a real export.** The fixtures in
`tests/fixtures/migration/` are hand-written to the same description; a real export from each
tool is still to be checked against them (`add-distribution-and-adoption` tasks 2.1-2.3).

- **Rayyan**, the CSV export (`articles.csv`): one row per article with `title`, `authors`
  (`Family, Given and Family, Given`), `journal`, `year`, `month`, `day`, `volume`, `issue`,
  `pages`, `doi`, `abstract`, `url`, `issn`, `publisher`, `language` and `notes`. Rayyan keeps
  each reviewer's decision in `notes`, as
  `RAYYAN-INCLUSION: {"Ada"=>"Included", "Sam"=>"Excluded"} | RAYYAN-EXCLUSION-REASONS: wrong
  population`; `Maybe` is a third decision.
- **Covidence**, the CSV export of one list (Irrelevant, Excluded or Included): `Title`,
  `Authors` (`Family, Given; Family, Given`), `Abstract`, `Published Year`, `Published Month`,
  `Journal`, `Volume`, `Issue`, `Pages`, `DOI`, `Covidence #`, and on the Excluded list an
  exclusion reason. The decision is the list's, which the person names with `--list`.
- **EPPI-Reviewer**, the JSON export: `References`, each with `ItemId`, `Title`, `Authors`
  (`Family, Given; ...`), `Year`, `ParentTitle`, `Volume`, `Issue`, `Pages`, `DOI`, `Abstract`
  and the `Codes` applied to it; `CodeSets` give each code's `AttributeType` (`Include` or
  `Exclude`), and an exclude code's name is the reason.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from strata.ingest.parsers import ParseResult, RejectedRow, has_title

#: The tools, by the `--format` / `--from` name.
TOOLS = ("rayyan", "covidence", "eppi-json")
#: Covidence's lists, each of which is a decision at each stage.
COVIDENCE_LISTS = ("irrelevant", "excluded", "included")


@dataclass(frozen=True)
class ToolDecision:
    """One decision as the tool exported it."""

    decision: str  # include | exclude | maybe
    reviewer: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass
class MigrationParse:
    """The records, and for each record (by position in `records.records`) its decisions."""

    records: ParseResult
    decisions: list[list[ToolDecision]] = field(default_factory=list)


class MigrationFormatError(ValueError):
    """The file is not an export of the tool it was said to be."""


def _name(raw: str) -> dict[str, str]:
    raw = raw.strip()
    if "," in raw:
        family, given = (p.strip() for p in raw.split(",", 1))
        return {"family": family, "given": given} if given else {"family": family}
    parts = raw.split()
    if len(parts) >= 2 and all(len(p.rstrip(".")) <= 2 for p in parts[1:]):
        return {"family": parts[0], "given": " ".join(parts[1:])}  # EPPI's "Cepeda N J"
    return {"literal": raw} if raw else {}


def _authors(raw: str, *, separators: tuple[str, ...]) -> list[dict[str, str]]:
    parts = [raw]
    for sep in separators:
        parts = [piece for part in parts for piece in part.split(sep)]
    return [n for n in (_name(p) for p in parts if p.strip()) if n]


def _year(raw: str) -> int | None:
    match = re.search(r"\b(1[5-9]\d\d|20\d\d|21\d\d)\b", raw or "")
    return int(match.group(1)) if match else None


_MONTHS = {
    m: i
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
         ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
         ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
         ("dec", "december")],
        start=1,
    )
    for m in names
}  # fmt: skip


def _month(raw: str) -> int | None:
    raw = (raw or "").strip().lower()
    if raw.isdigit() and 1 <= int(raw) <= 12:
        return int(raw)
    return _MONTHS.get(raw[:3]) if raw else None


def _record(
    *,
    title: str,
    authors: list[dict[str, str]],
    year: int | None,
    month: int | None = None,
    **fields: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {"type": "article-journal", "title": title.strip()}
    if authors:
        record["author"] = authors
    if year is not None:
        record["issued"] = {"date-parts": [[year, month] if month else [year]]}
    for name, value in fields.items():
        if value and value.strip():
            record[name] = value.strip()
    return record


def _rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in reader.fieldnames or []]
    rows = [{(k or "").strip().lower(): (v or "") for k, v in row.items()} for row in reader]
    return header, rows


# ------------------------------------------------------------------------------------- Rayyan

_RAYYAN_INCLUSION_RE = re.compile(r"RAYYAN-INCLUSION:\s*\{(?P<body>[^}]*)\}")
_RAYYAN_PAIR_RE = re.compile(r'"(?P<who>[^"]+)"\s*=>\s*"(?P<what>[^"]+)"')
_RAYYAN_REASONS_RE = re.compile(r"RAYYAN-EXCLUSION-REASONS:\s*(?P<reasons>[^|]*)")
_RAYYAN_DECISIONS = {"included": "include", "excluded": "exclude", "maybe": "maybe"}


def _rayyan_decisions(notes: str) -> list[ToolDecision]:
    reasons_match = _RAYYAN_REASONS_RE.search(notes)
    reasons = (
        tuple(r.strip() for r in reasons_match.group("reasons").split(",") if r.strip())
        if reasons_match
        else ()
    )
    match = _RAYYAN_INCLUSION_RE.search(notes)
    if match is None:
        return []
    found = []
    for pair in _RAYYAN_PAIR_RE.finditer(match.group("body")):
        decision = _RAYYAN_DECISIONS.get(pair.group("what").strip().lower())
        if decision is not None:
            found.append(
                ToolDecision(
                    decision,
                    pair.group("who").strip(),
                    reasons if decision == "exclude" else (),
                )
            )
    return found


def parse_rayyan(text: str) -> MigrationParse:
    header, rows = _rows(text)
    lowered = {h.lower() for h in header}
    if "title" not in lowered or "notes" not in lowered or "covidence #" in lowered:
        raise MigrationFormatError(
            "this is not a Rayyan CSV export: it needs a 'title' and a 'notes' column"
        )
    result = MigrationParse(ParseResult())
    for number, row in enumerate(rows, start=2):
        record = _record(
            title=row.get("title", ""),
            authors=_authors(row.get("authors", ""), separators=(" and ", ";")),
            year=_year(row.get("year", "")),
            month=_month(row.get("month", "")),
            **{
                "container-title": row.get("journal", ""),
                "volume": row.get("volume", ""),
                "issue": row.get("issue", ""),
                "page": row.get("pages", ""),
                "DOI": row.get("doi", ""),
                "abstract": row.get("abstract", ""),
                "URL": row.get("url", ""),
                "ISSN": row.get("issn", ""),
                "publisher": row.get("publisher", ""),
                "language": row.get("language", ""),
            },
        )
        if not has_title(record):
            result.records.rejected.append(RejectedRow(number, json.dumps(row), "no title"))
            continue
        result.records.records.append(record)
        result.decisions.append(_rayyan_decisions(row.get("notes", "")))
    return result


# ---------------------------------------------------------------------------------- Covidence


def covidence_decision(listed: str, stage: str) -> str | None:
    """What being on a Covidence list means at a stage; `None` when the list says nothing about
    it (an irrelevant record was never screened at full text)."""
    if listed == "irrelevant":
        return "exclude" if stage == "title-abstract" else None
    if listed == "excluded":
        return "include" if stage == "title-abstract" else "exclude"
    if listed == "included":
        return "include"
    raise MigrationFormatError(f"--list must be one of {', '.join(COVIDENCE_LISTS)}")


def parse_covidence(text: str) -> MigrationParse:
    header, rows = _rows(text)
    lowered = {h.lower() for h in header}
    if "title" not in lowered or "covidence #" not in lowered:
        raise MigrationFormatError(
            "this is not a Covidence CSV export: it needs a 'Title' and a 'Covidence #' column"
        )
    reason_column = next((h for h in lowered if "exclusion reason" in h), None)
    result = MigrationParse(ParseResult())
    for number, row in enumerate(rows, start=2):
        record = _record(
            title=row.get("title", ""),
            authors=_authors(row.get("authors", ""), separators=(";",)),
            year=_year(row.get("published year", "")),
            month=_month(row.get("published month", "")),
            **{
                "container-title": row.get("journal", ""),
                "volume": row.get("volume", ""),
                "issue": row.get("issue", ""),
                "page": row.get("pages", ""),
                "DOI": row.get("doi", ""),
                "abstract": row.get("abstract", ""),
            },
        )
        if not has_title(record):
            result.records.rejected.append(RejectedRow(number, json.dumps(row), "no title"))
            continue
        reasons = tuple(
            r.strip()
            for r in (row.get(reason_column, "") if reason_column else "").split(";")
            if r.strip()
        )
        result.records.records.append(record)
        # The decision is the list's (`covidence_decision`); only the reason is per row.
        result.decisions.append([ToolDecision("list", None, reasons)])
    return result


# ------------------------------------------------------------------------------ EPPI-Reviewer


def _eppi_attribute_types(document: Mapping[str, Any]) -> dict[Any, tuple[str, str]]:
    """AttributeId -> (type, name), from every code set."""
    found: dict[Any, tuple[str, str]] = {}

    def walk(attributes: Any) -> None:
        listed = attributes.get("AttributesList", []) if isinstance(attributes, dict) else []
        for attribute in listed if isinstance(listed, list) else []:
            if not isinstance(attribute, dict):
                continue
            key = attribute.get("AttributeId")
            if not isinstance(key, (int, str)):
                continue
            found[key] = (
                str(attribute.get("AttributeType") or ""),
                str(attribute.get("AttributeName") or ""),
            )
            walk(attribute.get("Attributes"))

    code_sets = document.get("CodeSets")
    for code_set in code_sets if isinstance(code_sets, list) else []:
        if isinstance(code_set, dict):
            walk(code_set.get("Attributes"))
    return found


def _eppi_decisions(
    reference: Mapping[str, Any], types: Mapping[Any, tuple[str, str]]
) -> list[ToolDecision]:
    includes, excludes = [], []
    codes = reference.get("Codes")
    for code in codes if isinstance(codes, list) else []:
        if not isinstance(code, dict):
            continue
        key = code.get("AttributeId")
        kind, name = types.get(key, ("", "")) if isinstance(key, (int, str)) else ("", "")
        name = str(code.get("AttributeName") or name)
        kind = kind or ("Include" if name.lower().startswith("include") else
                        "Exclude" if name.lower().startswith("exclude") else "")  # fmt: skip
        if kind.lower().startswith("include"):
            includes.append(name)
        elif kind.lower().startswith("exclude"):
            excludes.append(name)
    if excludes and not includes:
        return [ToolDecision("exclude", None, tuple(excludes))]
    if includes and not excludes:
        return [ToolDecision("include")]
    if includes and excludes:
        return [ToolDecision("maybe")]  # coded both ways: left for a person, never guessed
    return []


def parse_eppi_json(text: str) -> MigrationParse:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MigrationFormatError(f"this is not an EPPI-Reviewer JSON export: {exc}") from None
    if not isinstance(document, dict) or not isinstance(document.get("References"), list):
        raise MigrationFormatError(
            "this is not an EPPI-Reviewer JSON export: it has no 'References' list"
        )
    types = _eppi_attribute_types(document)
    result = MigrationParse(ParseResult())
    for index, reference in enumerate(document["References"]):
        if not isinstance(reference, dict):
            result.records.rejected.append(
                RejectedRow(index, json.dumps(reference), "not an object")
            )
            continue
        record = _record(
            title=str(reference.get("Title") or ""),
            authors=_authors(str(reference.get("Authors") or ""), separators=(";",)),
            year=_year(str(reference.get("Year") or "")),
            month=_month(str(reference.get("Month") or "")),
            **{
                "container-title": str(reference.get("ParentTitle") or ""),
                "volume": str(reference.get("Volume") or ""),
                "issue": str(reference.get("Issue") or ""),
                "page": str(reference.get("Pages") or ""),
                "DOI": str(reference.get("DOI") or ""),
                "abstract": str(reference.get("Abstract") or ""),
                "URL": str(reference.get("URL") or ""),
            },
        )
        if not has_title(record):
            result.records.rejected.append(RejectedRow(index, json.dumps(reference), "no title"))
            continue
        result.records.records.append(record)
        result.decisions.append(_eppi_decisions(reference, types))
    return result


PARSERS: dict[str, Callable[[str], MigrationParse]] = {
    "rayyan": parse_rayyan,
    "covidence": parse_covidence,
    "eppi-json": parse_eppi_json,
}


def records_only(tool: str) -> Callable[[str], ParseResult]:
    """The tool's parser as `strata import` uses it: the records, the decisions left out.
    `MigrationFormatError` when the file is not that tool's export."""

    def parse(text: str) -> ParseResult:
        return PARSERS[tool](text).records

    return parse
