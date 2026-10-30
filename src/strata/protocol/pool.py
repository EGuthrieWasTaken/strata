"""Derived views: openspec:derived-views#candidate-pool-view (`pool.tsv`) and
openspec:derived-views#conflicts-view (`conflicts.tsv`).

`derived/stale.tsv` and `derived/irr.json` are computed in
`protocol.rescreen`/`protocol.irr` respectively, since their logic is
tightly coupled to staleness/IRR computation that belongs there.
`regenerate_all` is the one call site that regenerates the screening derived views
(and `counts.json`) together, so a mutating CLI command never has to remember
which subset its change could affect.
"""

from __future__ import annotations

from strata.core import records as records_mod
from strata.core.fold import ScreeningState
from strata.core.repo import Repo
from strata.protocol import irr as irr_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod

_POOL_HEADER = (
    "record_id",
    "tiab",
    "fulltext",
    "stale",
    "year",
    "first_author",
    "title",
    "journal",
    "doi",
)
_CONFLICTS_HEADER = ("record_id", "stage", "opinions", "criteria_cited", "first_seen", "title")

_STAGE_COLUMN = {"title-abstract": "tiab", "full-text": "ft"}


def _write_derived(repo: Repo, name: str, text: str) -> str:
    path = repo.path("derived", name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def _tsv_escape(cell: str) -> str:
    """openspec:canonical-serialisation#tsv-rules: tabs/CR/LF become a single space."""
    return cell.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _canonical_ids(repo: Repo) -> list[str]:
    return sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )


def _stage_states(repo: Repo, stage: str, canonical_ids: list[str]) -> dict[str, ScreeningState]:
    return screening_mod.stage_states(repo, stage, canonical_ids)


def _stale_stages_by_record(repo: Repo) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for stale in rescreen_mod.compute_stale_records(repo):
        result.setdefault(stale.record_id, set()).add(stale.stage)
    return result


def render_pool_tsv(repo: Repo) -> str:
    """The text of `derived/pool.tsv`: one row per canonical record. Writes nothing."""
    records = records_mod.index_by_id(records_mod.read_records(repo))
    canonical_ids = sorted(
        record_id
        for record_id, record in records.items()
        if record.get("strata", {}).get("canonical", True)
    )
    tiab_states = _stage_states(repo, "title-abstract", canonical_ids)
    ft_states = _stage_states(repo, "full-text", canonical_ids)
    stale_stages = _stale_stages_by_record(repo)
    # openspec:full-text-retrieval#not-retrieved-reasons: a report that could not be obtained
    # has the full-text state `not-retrieved` (unless a decision was recorded regardless).
    not_retrieved = retrieval_mod.not_retrieved_record_ids(repo)

    rows = []
    for record_id in canonical_ids:
        record = records[record_id]
        tiab = tiab_states[record_id].status if record_id in tiab_states else "unscreened"
        fulltext = ft_states[record_id].status if record_id in ft_states else "unscreened"
        if fulltext == "unscreened" and record_id in not_retrieved:
            fulltext = "not-retrieved"
        marks = [
            _STAGE_COLUMN[s]
            for s in ("title-abstract", "full-text")
            if s in stale_stages.get(record_id, ())
        ]
        stale_column = ",".join(marks) if marks else "-"

        year = ((record.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        authors = record.get("author") or []
        first_author = ""
        if authors:
            first = authors[0]
            first_author = (first.get("family") or "") if isinstance(first, dict) else str(first)
        title = record.get("title") or ""
        if len(title) > 120:
            title = title[:120] + "…"

        rows.append(
            (
                record_id,
                tiab,
                fulltext,
                stale_column,
                str(year) if year else "",
                first_author,
                title,
                record.get("container-title") or "",
                record.get("DOI") or "",
            )
        )

    lines = ["\t".join(_POOL_HEADER)]
    lines.extend("\t".join(_tsv_escape(cell) for cell in row) for row in rows)
    return "\n".join(lines) + "\n"


def regenerate_pool_tsv(repo: Repo) -> str:
    """Regenerate `derived/pool.tsv`."""
    return _write_derived(repo, "pool.tsv", render_pool_tsv(repo))


def render_conflicts_tsv(repo: Repo) -> str:
    """The text of `derived/conflicts.tsv`: open screening disagreements. Writes nothing."""
    records = records_mod.index_by_id(records_mod.read_records(repo))
    canonical_ids = _canonical_ids(repo)

    rows = []
    for stage in screening_mod.configured_stages(repo):
        states = _stage_states(repo, stage, canonical_ids)
        for record_id in canonical_ids:
            state = states.get(record_id)
            if state is None or state.status != "conflict":
                continue
            opinions_str = ";".join(
                f"{actor}={event['body']['decision']}"
                for actor, event in sorted(state.opinions.items())
            )
            criteria = sorted(
                {
                    c
                    for event in state.opinions.values()
                    for c in event["body"].get("criteria") or []
                }
            )
            first_seen = min(event["ts"] for event in state.opinions.values())
            title = (records[record_id].get("title") or "")[:120]
            rows.append((record_id, stage, opinions_str, ";".join(criteria), first_seen, title))

    rows.sort(key=lambda row: (row[1], row[0]))
    lines = ["\t".join(_CONFLICTS_HEADER)]
    lines.extend("\t".join(_tsv_escape(cell) for cell in row) for row in rows)
    return "\n".join(lines) + "\n"


def regenerate_conflicts_tsv(repo: Repo) -> str:
    """Regenerate `derived/conflicts.tsv`."""
    return _write_derived(repo, "conflicts.tsv", render_conflicts_tsv(repo))


def derived_views(repo: Repo) -> dict[str, str]:
    """Every file under `derived/`, as regenerating it now would write it. Writes nothing.

    The file names are the keys. This is what `strata verify` compares the files on disk with
    (openspec:repository-format: GENERATED files are regenerated and compared, never read as input).
    """
    # Imported here: the counts read modules that import this one.
    from strata.report import counts as counts_mod

    return {
        "pool.tsv": render_pool_tsv(repo),
        "conflicts.tsv": render_conflicts_tsv(repo),
        "stale.tsv": rescreen_mod.render_stale_tsv(repo),
        "irr.json": irr_mod.render_irr_json(repo),
        "counts.json": counts_mod.render_counts_json(repo),
    }


def derived_drift(repo: Repo) -> list[str]:
    """Names of the derived files that exist and differ from what regenerating them would write.

    A file that is missing is not drift: commands regenerate what they need, and a review that has
    not reached screening has none of them yet.
    """
    drifted = []
    for name, expected in derived_views(repo).items():
        path = repo.path("derived", name)
        if path.is_file() and path.read_text(encoding="utf-8") != expected:
            drifted.append(name)
    return drifted


def regenerate_all(repo: Repo) -> None:
    """Regenerate every screening-related derived view in one call."""
    for name, text in derived_views(repo).items():
        _write_derived(repo, name, text)
