"""Bibliography export by set: openspec:manuscript-generation#bibliography-export.

The sets are the ones a PRISMA report needs listed: the studies included, the reports excluded at
full text (an appendix of exclusions), every record screened, and the reports that could not be
retrieved. Output is deterministic: sorted by record id, no timestamps.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from strata.core import records as records_mod
from strata.core.ids import normalise_year, record_id_for_report
from strata.core.repo import Repo
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod
from strata.protocol import studies as studies_mod

SETS = ("included", "excluded-at-fulltext", "all-screened", "not-retrieved")
FORMATS = ("bibtex", "csl", "ris")


class BibliographyError(ValueError):
    pass


def record_ids(repo: Repo, set_name: str) -> list[str]:
    """The canonical record ids in `set_name`, sorted."""
    if set_name not in SETS:
        raise BibliographyError(f"--set must be one of {', '.join(SETS)}, got {set_name!r}")
    stages = screening_mod.configured_stages(repo)
    if set_name == "included":
        members = studies_mod.study_map(repo).members
        return sorted({record_id_for_report(r) for reports in members.values() for r in reports})
    if set_name == "not-retrieved":
        return sorted(retrieval_mod.not_retrieved_record_ids(repo))
    if set_name == "all-screened":
        states = screening_mod.stage_states(repo, stages[0])
        return sorted(r for r, s in states.items() if s.status != "unscreened")
    if len(stages) < 2:
        return []
    states = screening_mod.stage_states(repo, stages[1])
    return sorted(r for r, s in states.items() if s.status == "exclude")


def records(repo: Repo, set_name: str) -> list[dict[str, Any]]:
    by_id = records_mod.index_by_id(records_mod.read_records(repo))
    return [by_id[i] for i in record_ids(repo, set_name) if i in by_id]


# --- CSL-JSON -------------------------------------------------------------------------------


def to_csl(rows: list[dict[str, Any]]) -> str:
    """CSL-JSON that pandoc reads directly (`--citeproc --bibliography`): the record without
    strata's own namespace, its id as the citation key."""
    items = [{k: v for k, v in sorted(r.items()) if k != "strata"} for r in rows]
    return json.dumps(items, indent=2, ensure_ascii=False) + "\n"


# --- shared pieces --------------------------------------------------------------------------


def _authors(record: dict[str, Any]) -> list[tuple[str, str]]:
    found = []
    for author in record.get("author") or []:
        if isinstance(author, dict):
            family = str(author.get("family") or author.get("literal") or "").strip()
            given = str(author.get("given") or "").strip()
        else:
            family, given = str(author).strip(), ""
        if family:
            found.append((family, given))
    return found


def _page_range(record: dict[str, Any]) -> tuple[str, str]:
    pages = str(record.get("page") or "").strip()
    if not pages:
        return "", ""
    parts = re.split(r"\s*[-\u2013\u2014]+\s*", pages, maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


# --- BibTeX ---------------------------------------------------------------------------------

_BIBTEX_TYPES = {
    "article-journal": "article",
    "article": "article",
    "book": "book",
    "chapter": "incollection",
    "paper-conference": "inproceedings",
    "report": "techreport",
    "thesis": "phdthesis",
}
_TEX_SPECIAL = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}  # fmt: skip


def _tex(text: str) -> str:
    return "".join(_TEX_SPECIAL.get(c, c) for c in text)


def _ascii(text: str) -> str:
    return re.sub(
        r"[^A-Za-z0-9]", "", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    )


def _keys(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Readable, unique citation keys: first author's family name and the year, then a letter."""
    seen: dict[str, int] = {}
    keys = {}
    for record in sorted(rows, key=lambda r: str(r["id"])):
        authors = _authors(record)
        base = (_ascii(authors[0][0]) if authors else "Anon") + str(
            normalise_year(record.get("issued")) or "nd"
        )
        seen[base] = seen.get(base, 0) + 1
        keys[str(record["id"])] = (
            base if seen[base] == 1 else f"{base}{chr(96 + min(seen[base], 26))}"
        )
    return keys


def to_bibtex(rows: list[dict[str, Any]]) -> str:
    keys = _keys(rows)
    entries = []
    for record in sorted(rows, key=lambda r: str(r["id"])):
        kind = _BIBTEX_TYPES.get(str(record.get("type")), "misc")
        fields: list[tuple[str, str]] = []
        authors = _authors(record)
        if authors:
            fields.append(("author", " and ".join(f"{f}, {g}" if g else f for f, g in authors)))
        if record.get("title"):
            fields.append(("title", "{" + _tex(str(record["title"])) + "}"))
        container = record.get("container-title")
        if container:
            fields.append(("journal" if kind == "article" else "booktitle", _tex(str(container))))
        year = normalise_year(record.get("issued"))
        if year:
            fields.append(("year", str(year)))
        for csl, bib in (
            ("volume", "volume"),
            ("issue", "number"),
            ("page", "pages"),
            ("publisher", "publisher"),
            ("DOI", "doi"),
            ("URL", "url"),
            ("PMID", "pmid"),
        ):
            if record.get(csl):
                value = (
                    str(record[csl]).replace("--", "-").replace("-", "--")
                    if csl == "page"
                    else str(record[csl])
                )
                fields.append((bib, value if csl in ("DOI", "URL") else _tex(value)))
        fields.append(("note", "strata record " + str(record["id"])))
        body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
        entries.append(f"@{kind}{{{keys[str(record['id'])]},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


# --- RIS ------------------------------------------------------------------------------------

_RIS_TYPES = {
    "article-journal": "JOUR", "article": "JOUR", "book": "BOOK", "chapter": "CHAP",
    "paper-conference": "CONF", "report": "RPRT", "thesis": "THES",
}  # fmt: skip


def to_ris(rows: list[dict[str, Any]]) -> str:
    out = []
    for record in sorted(rows, key=lambda r: str(r["id"])):
        lines = [f"TY  - {_RIS_TYPES.get(str(record.get('type')), 'GEN')}"]
        lines += [f"AU  - {f}, {g}" if g else f"AU  - {f}" for f, g in _authors(record)]
        if record.get("title"):
            lines.append(f"TI  - {record['title']}")
        if record.get("container-title"):
            lines.append(f"T2  - {record['container-title']}")
        year = normalise_year(record.get("issued"))
        if year:
            lines.append(f"PY  - {year}")
        if record.get("volume"):
            lines.append(f"VL  - {record['volume']}")
        if record.get("issue"):
            lines.append(f"IS  - {record['issue']}")
        first, last = _page_range(record)
        if first:
            lines.append(f"SP  - {first}")
        if last:
            lines.append(f"EP  - {last}")
        for tag, key in (("DO", "DOI"), ("UR", "URL"), ("AN", "PMID"), ("PB", "publisher")):
            if record.get(key):
                lines.append(f"{tag}  - {record[key]}")
        if record.get("abstract"):
            lines.append(f"AB  - {record['abstract']}")
        lines += [f"ID  - {record['id']}", "ER  - "]
        out.append("\n".join(lines))
    return "\n\n".join(out) + ("\n" if out else "")


def render(repo: Repo, *, fmt: str, set_name: str) -> str:
    if fmt not in FORMATS:
        raise BibliographyError(f"--format must be one of {', '.join(FORMATS)}, got {fmt!r}")
    rows = records(repo, set_name)
    return {"csl": to_csl, "bibtex": to_bibtex, "ris": to_ris}[fmt](rows)
