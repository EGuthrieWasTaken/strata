"""Risk-of-bias assessment: instruments, per-reviewer assessments, suggestions, overrides.

Implements openspec:risk-of-bias. Structurally this is extraction again (instrument, per-reviewer
assessment, reconciliation, consensus), and it is stored the same way: with `extraction.mode =
"dual"` each reviewer writes `rob/by-reviewer/<handle>/<study>.yaml` and the two are reconciled
into `rob/consensus/<study>.yaml`; otherwise a reviewer writes the consensus directly. Every
domain judgement is a `rob` event.

A domain whose instrument defines an algorithm (RoB 2 does) gets a *suggestion* computed from the
signalling answers. The reviewer's judgement is their own: choosing anything other than the
suggestion needs a recorded justification, and both are kept
(openspec:risk-of-bias#algorithmic-suggestion-with-recorded-override).

The instruments `strata` ships carry their structure, algorithm identifiers and short topic labels
but not the official question wording; see docs/rob-instruments.md for why.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strata.core.canon import dump_yaml_str, load_yaml_str
from strata.core.events import append_new_event
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError, validate, validate_event_body
from strata.extract import records as rec_mod
from strata.extract import rob_algorithms as alg
from strata.extract.schema import plain
from strata.protocol import studies as studies_mod

BUILTIN_IDS = ("rob2", "rob2-adhering", "robins-i", "nos-cohort", "nos-case-control")
OVERALL = "overall"
NO_INFORMATION = "no-information"


class RobError(ValueError):
    pass


# --- instruments -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Instrument:
    doc: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.doc["instrument"])

    @property
    def version(self) -> str:
        return str(self.doc["version"])

    @property
    def domains(self) -> list[dict[str, Any]]:
        return list(self.doc["domains"])

    def domain(self, domain_id: str) -> dict[str, Any] | None:
        return next((d for d in self.doc["domains"] if d["id"] == domain_id), None)

    @property
    def overall_algorithm(self) -> str:
        return str(self.doc["overall"]["algorithm"])

    @property
    def overall_judgements(self) -> list[str]:
        """The overall judgements, mildest first: explicit, else the first domain's list."""
        return list(self.doc["overall"].get("judgements") or self.doc["domains"][0]["judgements"])


def parse_instrument(doc: Any) -> Instrument:
    plain_doc = plain(doc)
    try:
        validate("rob-instrument", plain_doc)
    except SchemaValidationError as exc:
        raise RobError("; ".join(exc.errors)) from None
    ids = [d["id"] for d in plain_doc["domains"]]
    if len(ids) != len(set(ids)) or OVERALL in ids:
        raise RobError(f"domain ids must be unique and not {OVERALL!r}")
    for domain in plain_doc["domains"]:
        algorithm = domain.get("algorithm")
        if algorithm and algorithm not in alg.ALGORITHMS:
            raise RobError(f"domain {domain['id']}: no built-in algorithm {algorithm!r}")
        questions = [q["id"] for q in domain.get("signalling_questions", [])]
        if len(questions) != len(set(questions)):
            raise RobError(f"domain {domain['id']}: duplicate signalling question id")
    if plain_doc["overall"]["algorithm"] == "sum":
        for domain in plain_doc["domains"]:
            if not all(j.lstrip("-").isdigit() for j in domain["judgements"]):
                raise RobError("a 'sum' overall needs numeric domain judgements (e.g. stars)")
    return Instrument(plain_doc)


def builtin_instrument(instrument_id: str) -> Instrument:
    if instrument_id not in BUILTIN_IDS:
        raise RobError(f"no built-in instrument {instrument_id!r}; one of {', '.join(BUILTIN_IDS)}")
    resource = importlib.resources.files("strata.extract").joinpath(
        "instruments", f"{instrument_id}.yaml"
    )
    return parse_instrument(load_yaml_str(resource.read_text(encoding="utf-8")))


def instrument_path(repo: Repo) -> Path:
    return repo.path("rob", "instrument.yaml")


def init_instrument(repo: Repo, instrument_id: str, *, overwrite: bool = False) -> Instrument:
    """Write `rob/instrument.yaml` from a built-in definition, to use or to edit."""
    instrument = builtin_instrument(instrument_id)
    path = instrument_path(repo)
    if path.exists() and not overwrite:
        raise RobError("rob/instrument.yaml already exists; edit it directly")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml_str(instrument.doc), encoding="utf-8")
    return instrument


def load_instrument(repo: Repo) -> Instrument:
    path = instrument_path(repo)
    if not path.exists():
        raise RobError("this review has no rob/instrument.yaml yet; run `strata rob init`")
    return parse_instrument(load_yaml_str(path.read_text(encoding="utf-8")))


# --- assessments -----------------------------------------------------------------------------


def consensus_path(repo: Repo, study: str) -> Path:
    return repo.path("rob", "consensus", f"{study}.yaml")


def reviewer_path(repo: Repo, handle: str, study: str) -> Path:
    return repo.path("rob", "by-reviewer", handle, f"{study}.yaml")


def working_path(repo: Repo, handle: str, study: str) -> Path:
    if rec_mod.extraction_mode(repo) == "dual":
        return reviewer_path(repo, handle, study)
    return consensus_path(repo, study)


def read_assessment(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = plain(load_yaml_str(path.read_text(encoding="utf-8")))
    return data if isinstance(data, dict) else None


def _write(path: Path, assessment: dict[str, Any], instrument: Instrument) -> None:
    order = [d["id"] for d in instrument.domains]
    domains = assessment.get("domains", {})
    ordered = {
        "study": assessment["study"],
        "instrument": assessment["instrument"],
        "instrument_version": assessment["instrument_version"],
        "assessed_by": assessment["assessed_by"],
    }
    if "reconciled_by" in assessment:
        ordered["reconciled_by"] = assessment["reconciled_by"]
    ordered["domains"] = {d: _ordered_block(domains[d]) for d in order if d in domains}
    if OVERALL in assessment:
        ordered[OVERALL] = _ordered_block(assessment[OVERALL])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml_str(ordered), encoding="utf-8")


def _ordered_block(block: dict[str, Any]) -> dict[str, Any]:
    keys = ("answers", "suggested", "judgement", "override_justification", "support", "source")
    return {k: block[k] for k in keys if k in block and block[k] not in (None, "", {})}


def _current_study(repo: Repo, study: str) -> tuple[str, ...]:
    members = studies_mod.study_map(repo).members
    if study not in members:
        raise RobError(f"no included study {study!r}")
    return members[study]


def _load_for_update(
    repo: Repo, instrument: Instrument, handle: str, study: str
) -> tuple[Path, dict[str, Any]]:
    _current_study(repo, study)
    path = working_path(repo, handle, study)
    assessment = read_assessment(path) or {
        "study": study,
        "instrument": instrument.doc.get("id") or instrument.name,
        "instrument_version": instrument.version,
        "assessed_by": [handle],
        "domains": {},
    }
    assessment.setdefault("domains", {})
    if handle not in assessment["assessed_by"]:
        assessment["assessed_by"] = sorted({*assessment["assessed_by"], handle})
    return path, assessment


@dataclass(frozen=True)
class DomainState:
    domain: str
    answers: dict[str, str]
    suggested: str | None
    needed: str | None  # the next signalling question to answer, if the algorithm needs one
    judgement: str | None


def domain_state(
    instrument: Instrument, assessment: dict[str, Any] | None, domain_id: str
) -> DomainState:
    domain = instrument.domain(domain_id)
    if domain is None:
        raise RobError(f"the instrument has no domain {domain_id!r}")
    block = ((assessment or {}).get("domains") or {}).get(domain_id) or {}
    answers = dict(block.get("answers") or {})
    algorithm = domain.get("algorithm")
    suggested = alg.suggest(algorithm, answers) if algorithm else None
    needed = alg.needed(algorithm, answers) if algorithm else None
    return DomainState(domain_id, answers, suggested, needed, block.get("judgement"))


def answer_question(
    repo: Repo, *, study: str, handle: str, domain: str, question: str, answer: str
) -> DomainState:
    """Record one signalling answer (no event: the judgement, not the answer, is the decision).
    The suggestion is recomputed and returned."""
    instrument = load_instrument(repo)
    spec = instrument.domain(domain)
    if spec is None:
        raise RobError(f"the instrument has no domain {domain!r}")
    q = next((q for q in spec.get("signalling_questions", []) if q["id"] == question), None)
    if q is None:
        raise RobError(f"domain {domain} has no signalling question {question!r}")
    if answer not in q["options"]:
        raise RobError(f"{question}: answer must be one of {', '.join(q['options'])}")
    path, assessment = _load_for_update(repo, instrument, handle, study)
    block = assessment["domains"].setdefault(domain, {})
    block.setdefault("answers", {})[question] = answer
    _write(path, assessment, instrument)
    return domain_state(instrument, assessment, domain)


def overall_suggestion(instrument: Instrument, assessment: dict[str, Any] | None) -> str | None:
    """Suggest the overall judgement once every domain has been judged."""
    domains = (assessment or {}).get("domains") or {}
    judged = [domains.get(d["id"], {}).get("judgement") for d in instrument.domains]
    if any(j is None for j in judged):
        return None
    algorithm = instrument.overall_algorithm
    if algorithm == "sum":
        return str(sum(int(j) for j in judged))
    if algorithm != "worst-domain":
        return None
    order = instrument.overall_judgements
    rated = [j for j in judged if j in order]
    worst = max(rated, key=order.index) if rated else None
    if NO_INFORMATION in judged and (worst is None or order.index(worst) < len(order) - 2):
        return NO_INFORMATION  # missing information, and nothing already serious or critical
    return worst


def record_judgement(
    repo: Repo,
    *,
    study: str,
    handle: str,
    domain: str,
    judgement: str,
    support: str = "",
    source: str | None = None,
    override_justification: str | None = None,
) -> dict[str, Any]:
    """Record a domain (or the `overall`) judgement as a `rob` event, with support and a locator.

    Choosing anything other than the algorithm's suggestion needs `override_justification`; the
    suggestion is kept beside the judgement either way.
    """
    instrument = load_instrument(repo)
    is_overall = domain == OVERALL
    allowed = instrument.overall_judgements if is_overall else None
    spec = None if is_overall else instrument.domain(domain)
    if not is_overall and spec is None:
        raise RobError(f"the instrument has no domain {domain!r}")
    if allowed is None:
        assert spec is not None
        allowed = list(spec["judgements"])
    if is_overall and instrument.overall_algorithm == "sum":
        allowed = None
    if allowed is not None and judgement not in allowed:
        raise RobError(f"{domain}: judgement must be one of {', '.join(allowed)}")
    if allowed is None and not judgement.lstrip("-").isdigit():
        raise RobError(f"{domain}: judgement must be a number")

    path, assessment = _load_for_update(repo, instrument, handle, study)
    if is_overall:
        suggested = overall_suggestion(instrument, assessment)
        block = assessment.setdefault(OVERALL, {})
        answers: dict[str, str] = {}
    else:
        state = domain_state(instrument, assessment, domain)
        suggested = state.suggested
        block = assessment["domains"].setdefault(domain, {})
        answers = state.answers
    if (
        suggested is not None
        and judgement != suggested
        and not (override_justification or "").strip()
    ):
        raise RobError(
            f"{domain}: the algorithm suggests {suggested!r}; choosing {judgement!r} needs a "
            "justification for the override"
        )

    block["judgement"] = judgement
    block["suggested"] = suggested
    if override_justification and suggested is not None and judgement != suggested:
        block["override_justification"] = override_justification.strip()
    else:
        block.pop("override_justification", None)
    block["support"] = support
    if source:
        block["source"] = source
    body: dict[str, Any] = {
        "study": study,
        "domain": domain,
        "judgement": judgement,
        "support": support,
        "instrument": str(instrument.doc.get("id") or instrument.name),
        "scope": "consensus" if path == consensus_path(repo, study) else "reviewer",
    }
    if answers:
        body["signalling"] = answers
    if suggested is not None:
        body["suggested"] = suggested
    if block.get("override_justification"):
        body["override_justification"] = block["override_justification"]
    if source:
        body["source"] = source
    validate_event_body("rob", body)
    _write(path, assessment, instrument)
    return append_new_event(
        repo.path("events", "rob", f"{handle}.ndjson"), ev="rob", actor=handle, body=body
    )


# --- moderators ------------------------------------------------------------------------------


def moderators(repo: Repo) -> dict[str, dict[str, Any]]:
    """Study-level RoB moderators for analysis and filters: `rob_overall` and `rob.<domain>`.

    Only the consensus judgements count, and only for currently included studies.
    """
    if not instrument_path(repo).exists():
        return {}
    instrument = load_instrument(repo)
    members = studies_mod.study_map(repo).members
    found: dict[str, dict[str, Any]] = {}
    directory = repo.path("rob", "consensus")
    if not directory.exists():
        return found
    for path in sorted(directory.glob("*.yaml")):
        assessment = read_assessment(path)
        if not assessment or assessment.get("study") not in members:
            continue
        values: dict[str, Any] = {}
        overall = (assessment.get(OVERALL) or {}).get("judgement")
        values["rob_overall"] = overall
        for domain in instrument.domains:
            values[f"rob.{domain['id']}"] = (
                (assessment.get("domains") or {}).get(domain["id"]) or {}
            ).get("judgement")
        found[assessment["study"]] = values
    return found


# --- validation (strata verify) --------------------------------------------------------------


def validate_assessment(instrument: Instrument, assessment: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    blocks = {**(assessment.get("domains") or {})}
    for domain_id, block in blocks.items():
        spec = instrument.domain(domain_id)
        if spec is None:
            problems.append(f"domain {domain_id!r} is not in the instrument")
            continue
        for question, answer in (block.get("answers") or {}).items():
            q = next((q for q in spec.get("signalling_questions", []) if q["id"] == question), None)
            if q is None or answer not in q["options"]:
                problems.append(f"{domain_id} {question}: {answer!r} is not a valid answer")
        judgement = block.get("judgement")
        if judgement is not None and judgement not in spec["judgements"]:
            problems.append(f"{domain_id}: {judgement!r} is not a judgement of this instrument")
        suggested = block.get("suggested")
        if (
            judgement is not None
            and suggested is not None
            and judgement != suggested
            and not block.get("override_justification")
        ):
            problems.append(f"{domain_id}: overrides the suggestion without a justification")
    return problems


# --- reconciliation --------------------------------------------------------------------------


def reviewer_handles(repo: Repo, study: str) -> list[str]:
    directory = repo.path("rob", "by-reviewer")
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.iterdir() if (p / f"{study}.yaml").exists())


@dataclass
class RobItem:
    domain: str
    label: str
    candidates: dict[str, str | None]
    agree: bool
    resolved: bool


def compare(repo: Repo, study: str) -> list[RobItem]:
    """Each reviewer's judgement per domain (and overall), and where they agree."""
    handles = reviewer_handles(repo, study)
    if len(handles) < 2:
        raise RobError(f"{study} needs assessments from at least two reviewers")
    instrument = load_instrument(repo)
    by_handle = {h: read_assessment(reviewer_path(repo, h, study)) or {} for h in handles}
    consensus = read_assessment(consensus_path(repo, study)) or {}
    items = []
    for domain in [*instrument.domains, {"id": OVERALL, "label": "Overall"}]:
        key = domain["id"]
        values = {
            h: (
                (a.get(OVERALL) if key == OVERALL else (a.get("domains") or {}).get(key)) or {}
            ).get("judgement")
            for h, a in by_handle.items()
        }
        if all(v is None for v in values.values()):
            continue
        done = (
            (
                consensus.get(OVERALL)
                if key == OVERALL
                else (consensus.get("domains") or {}).get(key)
            )
            or {}
        ).get("judgement") is not None
        items.append(RobItem(key, domain["label"], values, len(set(values.values())) == 1, done))
    return items


def resolve(
    repo: Repo,
    *,
    study: str,
    reconciler: str,
    domain: str,
    choice: str,
    rationale: str,
    other_judgement: str | None = None,
) -> dict[str, Any]:
    """Settle one domain: take a reviewer's whole block, or enter another judgement."""
    if not rationale.strip():
        raise RobError("every reconciliation needs a rationale")
    items = {i.domain: i for i in compare(repo, study)}
    item = items.get(domain)
    if item is None:
        raise RobError(f"nothing to reconcile for domain {domain!r}")
    handles = reviewer_handles(repo, study)
    if choice not in (*handles, "other", "agreement"):
        raise RobError(f"choose one of {', '.join(handles)}, other, or agreement")
    if choice == "agreement" and not item.agree:
        raise RobError(f"{domain} is a disagreement; choose a reviewer or give a judgement")

    instrument = load_instrument(repo)
    path = consensus_path(repo, study)
    consensus = read_assessment(path) or {
        "study": study,
        "instrument": instrument.doc.get("id") or instrument.name,
        "instrument_version": instrument.version,
        "assessed_by": handles,
        "domains": {},
    }
    consensus["reconciled_by"] = reconciler
    donor_name = handles[0] if choice in ("agreement", "other") else choice
    donor = read_assessment(reviewer_path(repo, donor_name, study)) or {}
    source_block = (
        donor.get(OVERALL) if domain == OVERALL else (donor.get("domains") or {}).get(domain)
    ) or {}
    block = dict(source_block)
    if choice == "other":
        if not other_judgement:
            raise RobError("choosing 'other' needs a judgement")
        block = {"judgement": other_judgement, "support": f"Reconciled: {rationale.strip()}"}
        if domain != OVERALL and other_judgement not in (instrument.domain(domain) or {}).get(
            "judgements", []
        ):
            raise RobError(f"{domain}: judgement must be one of the instrument's judgements")
    if domain == OVERALL:
        consensus[OVERALL] = block
    else:
        consensus["domains"][domain] = block
    _write(path, consensus, instrument)

    chosen = block.get("judgement")
    body = {
        "study": study,
        "field": f"rob.{domain}",
        "chosen": chosen,
        "from": choice,
        "rationale": rationale.strip(),
        "candidates": {h: v for h, v in item.candidates.items()},
    }
    if block.get("source"):
        body["source"] = block["source"]
    validate_event_body("reconcile", body)
    event = append_new_event(
        repo.path("events", "reconcile", f"{reconciler}.ndjson"),
        ev="reconcile",
        actor=reconciler,
        body=body,
    )
    rob_body: dict[str, Any] = {
        "study": study,
        "domain": domain,
        "judgement": str(chosen),
        "support": block.get("support", ""),
        "instrument": str(instrument.doc.get("id") or instrument.name),
        "scope": "consensus",
    }
    validate_event_body("rob", rob_body)
    append_new_event(
        repo.path("events", "rob", f"{reconciler}.ndjson"),
        ev="rob",
        actor=reconciler,
        body=rob_body,
    )
    return event
