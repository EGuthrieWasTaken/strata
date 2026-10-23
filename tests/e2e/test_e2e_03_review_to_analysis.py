"""E2E-03 (up to the analysis step): import, screen, retrieve, group, extract twice, reconcile,
assess risk of bias, and export an analysis-ready dataset -- all through the CLI.

openspec:test-suite#end-to-end-scenarios names E2E-03 "Full review to publication". M3 delivers
everything up to the analysis step (docs/roadmap.md, M3 acceptance); the analysis, PRISMA diagram,
characteristics table, manuscript export and reproducibility package belong to M4/M5 and are not
asserted here.

The review: three records, two of which report the same trial (a study of two reports), screened
independently by two reviewers at both stages; every report is retrieved; the two reviewers extract
independently and disagree about one value; both assess risk of bias; the reconciler settles each
difference with a rationale; and `strata export effects` writes one row per effect.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core.canon import dump_yaml_str
from strata.core.events import read_events
from strata.core.repo import open_repo
from strata.core.verify import verify_repository
from strata.extract import records as extraction_records
from strata.extract import rob
from strata.protocol import studies as studies_mod

runner = CliRunner()
WHY = "Recording this step of the end-to-end review."

_RECORDS = [
    {
        "id": "1",
        "type": "article-journal",
        "title": "Spaced retrieval practice in adult learners",
        "author": [{"family": "Cepeda", "given": "Nicholas"}],
        "issued": {"date-parts": [[2008]]},
        "container-title": "Psychological Science",
        "DOI": "10.1111/e2e03.a",
        "abstract": "A randomised trial of spaced retrieval practice.",
    },
    {
        "id": "2",
        "type": "article-journal",
        "title": "Spaced retrieval practice in adult learners: one-year follow-up",
        "author": [{"family": "Cepeda", "given": "Nicholas"}],
        "issued": {"date-parts": [[2009]]},
        "container-title": "Psychological Science",
        "DOI": "10.1111/e2e03.b",
        "abstract": "Follow-up of the randomised trial of spaced retrieval practice.",
    },
    {
        "id": "3",
        "type": "article-journal",
        "title": "Testing effects in older adults",
        "author": [{"family": "Jones", "given": "Maria"}],
        "issued": {"date-parts": [[2012]]},
        "container-title": "Memory",
        "DOI": "10.1111/e2e03.c",
        "abstract": "A randomised comparison of testing and restudy.",
    },
]

_MEANS = {"n1": 40, "m1": 0.62, "sd1": 0.18, "n2": 40, "m2": 0.48, "sd2": 0.21}
_OTHER = {"n1": 30, "m1": 0.55, "sd1": 0.2, "n2": 30, "m2": 0.5, "sd2": 0.19}


def _run(root: Path | None, *args: str, input: str | None = None, code: int = EXIT_OK) -> Any:  # noqa: A002
    prefix = ["--why", WHY, *(["-C", str(root)] if root else [])]
    result = runner.invoke(app, [*prefix, *args], input=input)
    assert result.exit_code == code, result.output
    return result


def _json(root: Path, *args: str) -> Any:
    return json.loads(_run(root, "--json", *args).output)


@pytest.mark.req("E2E-03")
def test_a_review_runs_from_import_to_an_analysis_ready_dataset(tmp_path: Path) -> None:
    root = tmp_path / "review"
    _run(None, "init", str(root), "--title", "E2E-03", "--actor", "ethan", "--actor-name", "Ethan")
    _run(root, "actor", "add", "sam", "Sam")
    _run(
        root, "criteria", "add", "--kind", "inclusion", "--label", "Empirical study",
        "--definition", "Reports original empirical data.", "--applies-at", "title-abstract",
        "--applies-at", "full-text", "--by", "ethan", "--id", "INC-01",
    )  # fmt: skip
    export = tmp_path / "records.json"
    export.write_text(json.dumps(_RECORDS), encoding="utf-8")
    _run(root, "import", str(export), "--by", "ethan", "--via", "registry")

    # Two reviewers screen both stages independently; every record is included.
    for stage in ("title-abstract", "full-text"):
        for handle in ("ethan", "sam"):
            _run(root, "screen", stage, "--by", handle, input="i\n\n" * 3)

    # --- retrieval ---------------------------------------------------------------------------
    queue = _json(root, "retrieve", "--by", "ethan")
    assert (queue["sought"], queue["outstanding"]) == (3, 3)
    status = _json(root, "status")
    assert status["next_action"] == "strata retrieve"
    for item in queue["reports"]:
        _run(
            root, "retrieve", "--by", "ethan", "--report", item["report"], "--outcome", "retrieved",
            "--source", "institutional-access", "--version", "version-of-record",
        )  # fmt: skip
    assert _json(root, "retrieve", "--by", "ethan")["outstanding"] == 0

    # --- studies: the two Cepeda reports are one trial -----------------------------------------
    ids = [r["report"] for r in queue["reports"]]
    suggested = _json(root, "studies")["groupings"]
    assert [set(g["reports"]) for g in suggested] == [{ids[0], ids[1]}]  # same authors, follow-up
    _run(root, "studies", "--by", "ethan", "--group", ids[0], "--group", ids[1])
    members = studies_mod.study_map(open_repo(root)).members
    assert len(members) == 2
    trial, other = (s for s in sorted(members, key=lambda s: -len(members[s])))
    assert set(members[trial]) == {ids[0], ids[1]} and members[other] == (ids[2],)

    # --- extraction: a coding form from the protocol, filled in twice ----------------------------
    root.joinpath("protocol", "moderators.yaml").write_text(
        dump_yaml_str(
            {"moderators": [{"name": "design", "label": "Design", "type": "categorical",
                             "levels": ["rct", "quasi-experimental"]}]}
        ),
        encoding="utf-8",
    )  # fmt: skip
    root.joinpath("protocol", "outcomes.yaml").write_text(
        dump_yaml_str({"outcomes": [{"name": "recall"}]}), encoding="utf-8"
    )
    _run(root, "extract", "init", "--by", "ethan")
    manifest = root / "strata.toml"
    manifest.write_text(manifest.read_text() + '\n[extraction]\nmode = "dual"\n', encoding="utf-8")
    gitio.add_all(root)
    gitio.commit(root, "chore: dual extraction\n\nStrata-Op: config\nStrata-Actor: ethan")

    effect = {"outcome": "recall", "design": "two-group-means", "source": "Table 2"}
    for handle in ("ethan", "sam"):
        for study, means in ((trial, _MEANS), (other, _OTHER)):
            # sam reads the sample size of the Jones study differently from ethan.
            n_total = "158" if (handle == "sam" and study == other) else "80"
            _run(
                root, "extract", study, "--by", handle, "--set", f"n_total={n_total} @ Table 1",
                "--set", "design=rct", "--effect", json.dumps({**effect, **means}),
            )  # fmt: skip
    # n_total on the trial agrees; on the Jones study ethan and sam disagree.
    assert _json(root, "status")["extraction"]["reconcile"] == 2
    comparison = _json(root, "extract", "--reconcile")
    assert 0 < comparison["agreement"]["rate"] < 1
    differing = [
        (s["study"], i["id"]) for s in comparison["studies"] for i in s["items"] if not i["agree"]
    ]
    assert differing == [(other, "field:n_total")]

    # Reconciliation records every decision: agreements are confirmed, the difference is settled.
    _run(root, "extract", "--reconcile", trial, "--by", "ethan", input="y\n")
    _run(
        root,
        "extract",
        "--reconcile",
        other,
        "--by",
        "ethan",
        input="y\nethan\nThe flow chart says 80.\n",
    )
    events = [
        e
        for p in sorted(root.joinpath("events", "reconcile").glob("*.ndjson"))
        for e in read_events(p)
    ]
    assert {e["body"]["study"] for e in events} == {trial, other}
    assert all(e["body"]["rationale"] for e in events)
    settled = next(
        e for e in events if e["body"]["field"] == "n_total" and e["body"]["study"] == other
    )
    assert settled["body"]["rationale"] == "The flow chart says 80."
    assert extraction_records.studies_missing(open_repo(root)) == {}

    # --- risk of bias ------------------------------------------------------------------------
    _run(root, "rob", "init", "--instrument", "rob2", "--by", "ethan")
    answers = {"D1": ["1.1=Y", "1.2=Y", "1.3=N"]}
    for study, overall in ((trial, "low"), (other, "high")):
        for handle in ("ethan", "sam"):
            args = [
                "--answer",
                answers["D1"][0],
                "--answer",
                answers["D1"][1],
                "--answer",
                answers["D1"][2],
            ]
            _run(root, "rob", study, "--by", handle, "--domain", "D1", *args, "--judgement", "low")
            for domain in ("D2", "D3", "D4", "D5"):
                judged = "high" if (study == other and domain == "D3") else "low"
                _run(root, "rob", study, "--by", handle, "--domain", domain, "--judgement", judged)
            _run(root, "rob", study, "--by", handle, "--domain", "overall", "--judgement", overall)
        _run(
            root, "rob", "--reconcile", study, "--by", "ethan",
            input="y\n" * 6,
        )  # fmt: skip
    consensus = open_repo(root)
    assert {s: m["rob_overall"] for s, m in rob.moderators(consensus).items()} == {
        trial: "low",
        other: "high",
    }
    low_risk = json.loads(
        _run(root, "records", "list", "--format", "json", "--filter", "rob_overall == 'low'").output
    )
    assert {r["id"] for r in low_risk} == {r["id"] for r in _RECORDS_IN(root, members[trial])}

    # --- the analysis-ready dataset --------------------------------------------------------------
    out = tmp_path / "effects.csv"
    _run(root, "export", "effects", "--format", "csv", "--out", str(out))
    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
    assert [(r["study_id"], r["outcome"]) for r in rows] == sorted(
        [(trial, "recall"), (other, "recall")]
    )
    assert all(
        r["effect_id"].startswith("eff_") and float(r["yi"]) and float(r["vi"]) > 0 for r in rows
    )
    by_study = {r["study_id"]: r for r in rows}
    assert by_study[trial]["rob_overall"] == "low" and by_study[other]["rob_overall"] == "high"
    assert by_study[other]["n_total"] == "80" and by_study[trial]["field_design"] == "rct"
    assert out.read_bytes() == _rerun_export(root, tmp_path / "again.csv")  # deterministic

    # --- the whole repository is consistent and clean ------------------------------------------
    report = verify_repository(open_repo(root))
    assert report.ok, report.issues
    assert not [i for i in report.issues if i.severity == "warning"], report.issues
    assert not gitio.is_dirty(root)
    final = _json(root, "status")
    assert final["extraction"]["complete"] == final["extraction"]["studies"] == 2
    assert final["next_action"] is None
    log = "\n".join(gitio.log(root, fmt="%s"))
    for op in ("retrieve", "studies", "extract", "reconcile", "rob"):
        assert op in log


def _RECORDS_IN(root: Path, reports: tuple[str, ...]) -> list[dict[str, Any]]:  # noqa: N802
    from strata.core import records as records_mod
    from strata.core.ids import record_id_for_report

    wanted = {record_id_for_report(r) for r in reports}
    return [r for r in records_mod.read_records(open_repo(root)) if r["id"] in wanted]


def _rerun_export(root: Path, path: Path) -> bytes:
    _run(root, "export", "effects", "--format", "csv", "--out", str(path))
    return path.read_bytes()
