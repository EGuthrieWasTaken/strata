"""PRISMA 2020 counts and their reconciliation identities.

Implements openspec:prisma-reporting#counts-and-reconciliation-identities and
openspec:derived-views#prisma-counts-view. Every number is derived from the import manifests, the
records, the screening, adjudication and retrieval events and the study grouping; none is typed.
`compute` asserts each identity and reports the ones that fail; `require_reconciled` turns a
failure into `E_COUNT_RECONCILE` naming the identity.

How the funnel is partitioned. A row of an import is *identified* by the search it came from (a
database, or a trial register) or by the `via` method it was imported with. Each canonical record
has one origin: `searches` if any of its sources is a search, otherwise the `via` of its first
source. Duplicates removed from an origin are its identified rows less its canonical records, so a
via-found row that duplicates a database record is a duplicate in the other-methods column, as the
PRISMA 2020 two-column diagram counts it. The total of duplicates removed is also derived a second,
independent way (rows imported onto an existing id plus records merged away), and the two must
agree; that is what catches a records file that no import accounts for.

A review in progress still closes: records not yet resolved at a stage are counted as `awaiting_*`
and the identities carry those terms, which are zero for a finished review. `complete` is true only
when nothing is awaiting and no decision is stale; the diagram is a DRAFT until then.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from strata.core import records as records_mod
from strata.core.canon import canonical_json
from strata.core.fold import (
    NOT_RETRIEVED,
    RETRIEVAL_RETRIEVED,
    ScreeningState,
)
from strata.core.ids import report_id
from strata.core.repo import Repo
from strata.ingest import pipeline as import_pipeline
from strata.protocol import criteria as criteria_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod
from strata.protocol import searches as searches_mod
from strata.protocol import studies as studies_mod

SEARCHES = "searches"
NO_REASON = "no-reason-recorded"
VERSION = 1

# Searches of these are counted as registers rather than databases in the identification box.
REGISTERS = frozenset(
    {
        "clinicaltrials.gov",
        "clinicaltrials",
        "ictrp",
        "who ictrp",
        "isrctn",
        "anzctr",
        "euctr",
        "eu clinical trials register",
        "cochrane central",
        "central",
    }
)


class CountReconcileError(ValueError):
    """`E_COUNT_RECONCILE`: the counts do not close; the message names the identities."""

    code = "E_COUNT_RECONCILE"

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__("; ".join(failures))


@dataclass
class Funnel:
    """One origin's (or the whole review's) path from identification to inclusion."""

    identified: int = 0
    duplicates_removed: int = 0
    marked_ineligible_by_automation: int = 0
    removed_other: int = 0
    records_screened: int = 0
    records_excluded_tiab: int = 0
    awaiting_tiab: int = 0
    reports_sought: int = 0
    reports_retrieved: int = 0
    reports_not_retrieved: int = 0
    awaiting_retrieval: int = 0
    reports_assessed: int = 0
    reports_excluded_ft: int = 0
    awaiting_ft: int = 0
    reports_included: int = 0

    @property
    def removed_before_screening(self) -> int:
        return self.duplicates_removed + self.marked_ineligible_by_automation + self.removed_other

    def add(self, other: Funnel) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def to_dict(self) -> dict[str, int]:
        out = asdict(self)
        out["removed_before_screening"] = self.removed_before_screening
        return dict(sorted(out.items()))


@dataclass
class Reason:
    id: str
    label: str
    count: int


@dataclass
class Counts:
    identification: dict[str, Any]
    totals: Funnel
    by_origin: dict[str, Funnel]
    exclusion_reasons: list[Reason]
    not_retrieved_reasons: dict[str, int]
    studies_included: int
    reports_of_included_studies: int
    stale_decisions: int
    assertions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def awaiting(self) -> int:
        t = self.totals
        return t.awaiting_tiab + t.awaiting_retrieval + t.awaiting_ft

    @property
    def complete(self) -> bool:
        return self.awaiting == 0 and self.stale_decisions == 0

    @property
    def reconciled(self) -> bool:
        return all(a["holds"] for a in self.assertions)

    @property
    def failures(self) -> list[str]:
        return [a["identity"] for a in self.assertions if not a["holds"]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "complete": self.complete,
            "reconciled": self.reconciled,
            "stale_decisions": self.stale_decisions,
            "identification": self.identification,
            "totals": self.totals.to_dict(),
            "by_origin": {name: f.to_dict() for name, f in sorted(self.by_origin.items())},
            "exclusion_reasons": [asdict(r) for r in self.exclusion_reasons],
            "not_retrieved_reasons": dict(sorted(self.not_retrieved_reasons.items())),
            "studies_included": self.studies_included,
            "reports_of_included_studies": self.reports_of_included_studies,
            "assertions": self.assertions,
        }

    @property
    def other_methods(self) -> Funnel:
        """Every origin except the database and register searches, summed."""
        total = Funnel()
        for name, funnel in self.by_origin.items():
            if name != SEARCHES:
                total.add(funnel)
        return total


# --- identification -------------------------------------------------------------------------


def _is_register(database: str) -> bool:
    return database.strip().lower() in REGISTERS


def _identification(repo: Repo) -> tuple[dict[str, Any], Counter[str], Counter[str], int]:
    """The identification box, rows identified per origin, rows imported onto an existing id per
    origin, and the total of the latter."""
    searches = {s["id"]: s for s in searches_mod.list_searches(repo)}
    databases: Counter[str] = Counter()
    registers: Counter[str] = Counter()
    other: Counter[str] = Counter()
    identified: Counter[str] = Counter()
    appended: Counter[str] = Counter()
    for manifest in import_pipeline.list_import_manifests(repo):
        parsed = int(manifest.get("rows_read", 0)) - int(manifest.get("rows_rejected", 0))
        again = int(manifest.get("existing_ids_appended", 0))
        via = manifest.get("via")
        if via:
            other[str(via)] += parsed
            identified[str(via)] += parsed
            appended[str(via)] += again
            continue
        search_id = str(manifest.get("search"))
        database = str(searches.get(search_id, {}).get("database", ""))
        (registers if _is_register(database) else databases)[search_id] += parsed
        identified[SEARCHES] += parsed
        appended[SEARCHES] += again
    box = {
        "databases": {
            "total": sum(databases.values()),
            "by_search": dict(sorted(databases.items())),
        },
        "registers": {
            "total": sum(registers.values()),
            "by_search": dict(sorted(registers.items())),
        },
        "other_methods": {"total": sum(other.values()), "by_via": dict(sorted(other.items()))},
        "identified_total": sum(identified.values()),
    }
    return box, identified, appended, sum(appended.values())


def origin_of(record: dict[str, Any]) -> str:
    """`searches` if any source is a search, else the `via` of the first source."""
    sources = record.get("strata", {}).get("sources", [])
    if not sources or any(not s.get("via") for s in sources):
        return SEARCHES
    return str(sources[0]["via"])


# --- screening ------------------------------------------------------------------------------


def _primary_reason(state: ScreeningState) -> str:
    """One reason per excluded report: the first criterion the adjudicator cited, else the first
    criterion cited by an excluding reviewer (reviewers in handle order)."""
    if state.adjudication is not None:
        cited = sorted(state.adjudication["body"].get("criteria") or [])
        return cited[0] if cited else NO_REASON
    for actor in sorted(state.opinions):
        body = state.opinions[actor]["body"]
        if body.get("decision") == "exclude" and body.get("criteria"):
            return str(sorted(body["criteria"])[0])
    return NO_REASON


def _reason_label(repo: Repo, reason_id: str) -> str:
    if reason_id == NO_REASON:
        return "No reason recorded"
    criterion = criteria_mod.get_criterion(repo, reason_id)
    return str(criterion["label"]) if criterion else reason_id


def compute(repo: Repo) -> Counts:
    box, identified, appended, appended_total = _identification(repo)
    records = records_mod.read_records(repo)
    canonical = [r for r in records if r.get("strata", {}).get("canonical", True)]
    merged_away = len(records) - len(canonical)
    canonical_ids = sorted(r["id"] for r in canonical)
    origins = {r["id"]: origin_of(r) for r in canonical}

    stages = screening_mod.configured_stages(repo)
    tiab_states = screening_mod.stage_states(repo, stages[0], canonical_ids)
    sought_ids: list[str] = []
    excluded_tiab: Counter[str] = Counter()
    awaiting_tiab: Counter[str] = Counter()
    for record_id in canonical_ids:
        status = tiab_states[record_id].status if record_id in tiab_states else "unscreened"
        if status == "include":
            sought_ids.append(record_id)
        elif status == "exclude":
            excluded_tiab[origins[record_id]] += 1
        else:
            awaiting_tiab[origins[record_id]] += 1

    retrieved_ids: list[str] = []
    not_retrieved: Counter[str] = Counter()
    awaiting_retrieval: Counter[str] = Counter()
    not_retrieved_reasons: Counter[str] = Counter()
    has_full_text = len(stages) > 1
    if has_full_text:
        states = retrieval_mod.retrieval_states(repo)
        for record_id in sought_ids:
            report = report_id(record_id)
            status = retrieval_mod.status_of(states, report)
            if status == RETRIEVAL_RETRIEVED:
                retrieved_ids.append(record_id)
            elif status == NOT_RETRIEVED:
                not_retrieved[origins[record_id]] += 1
                not_retrieved_reasons[states[report].event["body"].get("reason", "other")] += 1
            else:
                awaiting_retrieval[origins[record_id]] += 1
    else:
        retrieved_ids = list(sought_ids)

    included_ids: list[str] = []
    excluded_ft: Counter[str] = Counter()
    awaiting_ft: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    if has_full_text:
        ft_states = screening_mod.stage_states(repo, stages[1], retrieved_ids)
        for record_id in retrieved_ids:
            state = ft_states[record_id]
            if state.status == "include":
                included_ids.append(record_id)
            elif state.status == "exclude":
                excluded_ft[origins[record_id]] += 1
                reasons[_primary_reason(state)] += 1
            else:
                awaiting_ft[origins[record_id]] += 1
    else:
        included_ids = list(retrieved_ids)

    canonical_by_origin = Counter(origins.values())
    sought_by_origin = Counter(origins[r] for r in sought_ids)
    retrieved_by_origin = Counter(origins[r] for r in retrieved_ids)
    included_by_origin = Counter(origins[r] for r in included_ids)

    by_origin: dict[str, Funnel] = {}
    for name in sorted(set(identified) | set(canonical_by_origin) | {SEARCHES}):
        by_origin[name] = Funnel(
            identified=identified[name],
            duplicates_removed=identified[name] - canonical_by_origin[name],
            records_screened=canonical_by_origin[name],
            records_excluded_tiab=excluded_tiab[name],
            awaiting_tiab=awaiting_tiab[name],
            reports_sought=sought_by_origin[name],
            reports_retrieved=retrieved_by_origin[name],
            reports_not_retrieved=not_retrieved[name],
            awaiting_retrieval=awaiting_retrieval[name],
            reports_assessed=retrieved_by_origin[name],
            reports_excluded_ft=excluded_ft[name],
            awaiting_ft=awaiting_ft[name],
            reports_included=included_by_origin[name],
        )
    totals = Funnel()
    for funnel in by_origin.values():
        totals.add(funnel)

    included_reports = [report_id(r) for r in included_ids]
    study_members = studies_mod.study_map(repo, reports=included_reports).members
    reasons_list = [
        Reason(reason_id, _reason_label(repo, reason_id), count)
        for reason_id, count in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    counts = Counts(
        identification=box,
        totals=totals,
        by_origin=by_origin,
        exclusion_reasons=reasons_list,
        not_retrieved_reasons=dict(not_retrieved_reasons),
        studies_included=len(study_members),
        reports_of_included_studies=sum(len(v) for v in study_members.values()),
        stale_decisions=len(rescreen_mod.compute_stale_records(repo)),
    )
    counts.assertions = _assertions(counts, appended_total, merged_away)
    return counts


# --- identities -----------------------------------------------------------------------------


def _check(identity: str, lhs: int, rhs: int, where: str = "") -> dict[str, Any]:
    return {"identity": identity + where, "lhs": lhs, "rhs": rhs, "holds": lhs == rhs}


def _funnel_assertions(f: Funnel, where: str) -> list[dict[str, Any]]:
    return [
        _check(
            "removed_before_screening = duplicates_removed + marked_ineligible_by_automation"
            " + removed_other",
            f.removed_before_screening,
            f.duplicates_removed + f.marked_ineligible_by_automation + f.removed_other,
            where,
        ),
        _check(
            "records_screened = identified_total - removed_before_screening",
            f.records_screened,
            f.identified - f.removed_before_screening,
            where,
        ),
        _check(
            "records_screened = records_excluded_tiab + reports_sought (+ awaiting_tiab)",
            f.records_screened,
            f.records_excluded_tiab + f.reports_sought + f.awaiting_tiab,
            where,
        ),
        _check(
            "reports_sought = reports_retrieved + reports_not_retrieved (+ awaiting_retrieval)",
            f.reports_sought,
            f.reports_retrieved + f.reports_not_retrieved + f.awaiting_retrieval,
            where,
        ),
        _check(
            "reports_retrieved = reports_assessed", f.reports_retrieved, f.reports_assessed, where
        ),
        _check(
            "reports_assessed = reports_excluded_ft + reports_included (+ awaiting_ft)",
            f.reports_assessed,
            f.reports_excluded_ft + f.reports_included + f.awaiting_ft,
            where,
        ),
    ]


def _assertions(counts: Counts, appended_total: int, merged_away: int) -> list[dict[str, Any]]:
    t = counts.totals
    ident = counts.identification
    found = [
        _check(
            "identified_total = sum over searches of records identified + records identified via"
            " other methods",
            ident["identified_total"],
            ident["databases"]["total"]
            + ident["registers"]["total"]
            + ident["other_methods"]["total"],
        ),
        _check(
            "identified_total = sum over origins of records identified",
            ident["identified_total"],
            t.identified,
        ),
        _check(
            "duplicates_removed = rows imported onto an existing id + records merged away",
            t.duplicates_removed,
            appended_total + merged_away,
        ),
    ]
    found += _funnel_assertions(t, "")
    for name, funnel in sorted(counts.by_origin.items()):
        found += _funnel_assertions(funnel, f" [{name}]")
        found.append(
            _check(
                "duplicates_removed is not negative",
                max(funnel.duplicates_removed, 0),
                funnel.duplicates_removed,
                f" [{name}]",
            )
        )
    found += [
        _check(
            "reports_excluded_ft = sum over exclusion reasons of count_per_reason",
            t.reports_excluded_ft,
            sum(r.count for r in counts.exclusion_reasons),
        ),
        _check(
            "reports_not_retrieved = sum over not-retrieved reasons",
            t.reports_not_retrieved,
            sum(counts.not_retrieved_reasons.values()),
        ),
        _check(
            "studies_included <= reports_included",
            min(counts.studies_included, t.reports_included),
            counts.studies_included,
        ),
        _check(
            "reports_of_included_studies = reports_included",
            counts.reports_of_included_studies,
            t.reports_included,
        ),
    ]
    return found


def require_reconciled(counts: Counts) -> None:
    """Raise `E_COUNT_RECONCILE` naming every identity that does not hold."""
    if not counts.reconciled:
        raise CountReconcileError(counts.failures)


# --- derived/counts.json --------------------------------------------------------------------


def regenerate_counts_json(repo: Repo) -> str:
    """Regenerate `derived/counts.json`. The file records the assertions whether or not they hold;
    `strata verify` and `strata prisma` are what fail on a broken one."""
    text = canonical_json(compute(repo).to_dict()) + "\n"
    path = repo.path("derived", "counts.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
