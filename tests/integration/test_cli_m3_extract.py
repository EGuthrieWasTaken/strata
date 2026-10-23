"""`strata extract`, `strata rob` and their effect on filters, status and export (M3)."""

# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_USAGE, app
from strata.core.canon import dump_yaml_str
from strata.core.repo import Repo
from strata.core.verify import verify_repository
from strata.extract import records as rec_mod
from strata.extract import rob
from tests.unit._m3 import add_records, decide, init_review
from tests.unit.test_extract_records import FORM, MEANS, _review, study

runner = CliRunner()
WHY = ("--why", "Recording this for the review record.")
S1, S2 = study(1), study(2)


def _cli(repo: Repo, *args: str, input: str | None = None, code: int = EXIT_OK) -> Any:  # noqa: A002
    result = runner.invoke(app, [*WHY, "-C", str(repo.root), *args], input=input)
    assert result.exit_code == code, result.output
    return result


def _commit_all(repo: Repo) -> Repo:
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")
    return repo


def _form_repo(tmp_path: Path, **kwargs: Any) -> Repo:
    return _commit_all(_review(tmp_path, **kwargs))


def _screened(repo: Repo) -> Repo:
    """Title/abstract decisions and retrieved full texts too: extraction is what is left."""
    from strata.core import records as records_mod
    from strata.core.ids import report_id
    from strata.protocol import retrieval

    ids = [r["id"] for r in records_mod.read_records(repo)]
    decide(repo, "title-abstract", ids)
    for record_id in ids:
        retrieval.record_retrieval(
            repo, report=report_id(record_id), status="retrieved", actor="ethan",
            source="institutional-access", version="version-of-record",
        )  # fmt: skip
    return _commit_all(repo)


def _subjects(repo: Repo) -> list[str]:
    return gitio.log(repo.root, fmt="%s")


def _json(repo: Repo, *args: str, code: int = EXIT_OK) -> Any:
    return json.loads(_cli(repo, "--json", *args, code=code).output)


# --- strata extract init ---------------------------------------------------------------------


def test_extract_init_drafts_the_form_from_the_protocol_and_commits(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    repo.path("protocol", "moderators.yaml").write_text(
        dump_yaml_str(
            {
                "moderators": [
                    {"name": "mean_age", "label": "Mean age", "type": "continuous", "unit": "years"},
                    {"name": "design", "label": "Design", "type": "categorical",
                     "levels": ["rct", "quasi-experimental"]},
                ]
            }
        ),
        encoding="utf-8",
    )  # fmt: skip
    _commit_all(repo)
    out = _json(repo, "extract", "init", "--by", "ethan")
    assert {"mean_age", "design"} <= set(out["fields"])
    assert repo.path("extraction", "schema.yaml").exists()
    assert _subjects(repo)[0].startswith("extract-init")
    assert not gitio.is_dirty(repo.root)
    assert not verify_repository(repo).issues
    _cli(repo, "extract", "init", "--by", "ethan", code=EXIT_USAGE)
    assert (
        "already exists" in _cli(repo, "extract", "init", "--by", "ethan", code=EXIT_USAGE).output
    )
    _cli(repo, "extract", "init", "--by", "ethan", "--overwrite")


def test_extract_before_init_points_at_init(tmp_path: Path) -> None:
    repo = _commit_all(init_review(tmp_path))
    result = _cli(repo, "extract", "--missing", "--list", code=EXIT_USAGE)
    assert "extract init" in result.output


# --- strata extract (scriptable) ----------------------------------------------------------------


def test_extract_lists_the_studies_with_missing_required_values(tmp_path: Path) -> None:
    """openspec scenario: `--missing` queues exactly the studies with missing required values."""
    repo = _form_repo(tmp_path, studies=3)
    for name, raw in (("n_total", "100"), ("design", "rct"), ("retention_interval", "1 week")):
        rec_mod.set_field(repo, study=S1, handle="ethan", name=name, raw=raw)
    _commit_all(repo)
    out = _json(repo, "extract", "--missing", "--by", "ethan")
    assert [s["study"] for s in out["studies"]] == [study(2), study(3)]
    assert out["studies"][0]["missing"] == ["n_total", "design", "retention_interval"]
    everything = _json(repo, "extract", "--by", "ethan")
    assert [s["study"] for s in everything["studies"]] == [S1, study(2), study(3)]
    text = _cli(repo, "extract", "--missing", "--list", "--by", "ethan").output
    assert "2 studies" in text and "missing: n_total, design, retention_interval" in text


def test_extract_records_fields_and_effects_from_the_command_line(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path)
    effect = json.dumps(
        {"outcome": "recall", "design": "two-group-means", "source": "Table 2", **MEANS}
    )
    out = _json(
        repo, "extract", S1, "--by", "ethan",
        "--set", "n_total=148 @ Table 1", "--set", "design=rct",
        "--set", "retention_interval=1 week", "--effect", effect,
    )  # fmt: skip
    assert out["fields"] == ["n_total", "design", "retention_interval"]
    [saved] = out["effects"]
    assert saved["yi"] is not None and saved["warnings"] == []
    record = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert record is not None
    assert record["fields"]["n_total"] == {"value": 148, "source": "Table 1"}
    assert record["fields"]["retention_interval"]["value"] == 168
    assert _subjects(repo)[0].startswith("extract")
    assert not gitio.is_dirty(repo.root)
    assert not [i for i in verify_repository(repo).issues if i.severity == "error"]


def test_extract_accepts_a_unique_study_prefix_and_rejects_unknown_studies(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path, studies=1)
    _cli(repo, "extract", "std_", "--by", "ethan", "--set", "n_total=5")  # the only study
    assert rec_mod.consensus_path(repo, S1).exists()
    unknown = _cli(
        repo, "extract", "std_zzz", "--by", "ethan", "--set", "n_total=5", code=EXIT_USAGE
    )
    assert "no included study" in unknown.output


def test_an_ambiguous_study_prefix_is_refused(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path, studies=3)
    result = _cli(repo, "extract", "std_", "--by", "ethan", "--set", "n_total=5", code=EXIT_USAGE)
    assert "matches 3 studies" in result.output


def test_extract_reports_bad_input_without_writing(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path)
    for args, message in (
        (("--set", "n_total=lots"), "not a number"),
        (("--set", "n_total"), "NAME=VALUE"),
        (("--set", "shoe=9"), "no field"),
        (("--effect", "{not json"), "not JSON"),
        (("--effect", '{"design": "t-test"}'), "outcome and design"),
        (("--effect", json.dumps({"outcome": "recall", "design": "two-group-means", "n1": 3})), "E_EFFECT_INPUTS"),
        (("--ack", "large-effect"), "CODE=EFFECT_KEY"),
        (("--ack", "large-effect=x"), "note"),
    ):  # fmt: skip
        result = _cli(repo, "extract", S1, "--by", "ethan", *args, code=EXIT_USAGE)
        assert message in result.output
    assert not rec_mod.consensus_path(repo, S1).exists()
    _cli(repo, "extract", "--by", "ethan", "--set", "n_total=5", code=EXIT_USAGE)  # no study
    _cli(repo, "extract", S1, "--set", "n_total=5", code=EXIT_USAGE)  # no --by


def test_a_large_effect_warns_and_the_acknowledgement_is_recorded(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path)
    huge = {
        "outcome": "recall",
        "design": "two-group-means",
        "n1": 20,
        "m1": 9.0,
        "sd1": 1.0,
        "n2": 20,
        "m2": 4.5,
        "sd2": 1.0,
    }
    out = _json(repo, "extract", S1, "--by", "ethan", "--effect", json.dumps(huge))
    [saved] = out["effects"]
    assert [w["code"] for w in saved["warnings"]] == ["large-effect"]
    text = _cli(repo, "extract", S1, "--by", "ethan", "--effect", json.dumps(huge)).output
    assert "warning (large-effect)" in text
    ack = _json(
        repo, "extract", S1, "--by", "ethan",
        "--ack", f"large-effect={saved['key']}", "--note", "Matches Table 2 of the paper",
    )  # fmt: skip
    assert ack["acknowledged"] == [{"code": "large-effect", "effect": saved["key"]}]
    record = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert record is not None and rec_mod.open_warnings(repo, S1, record) == []


# --- strata extract (interactive) -----------------------------------------------------------


def test_extract_walks_the_form_with_live_effect_sizes(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path)
    keystrokes = [
        "148 @ Table 1",  # n_total
        "cohort",  # design: refused ...
        "rct",  # ... and asked again
        "1 week",  # retention_interval
        "", "", "", "", "", "",  # the six optional fields
        "two-group-means", "recall", "1 week", "",  # an effect: design, outcome, timepoint, label
        "74", "0.62", "0.18", "74", "0.48", "0.21",  # its six inputs
        "Table 2",  # source
        "",  # no more effects
    ]  # fmt: skip
    result = _cli(repo, "extract", S1, "--by", "ethan", input="\n".join(keystrokes) + "\n")
    assert "not one of rct, quasi-experimental" in result.output
    assert "stored: 168 hours (entered 1 week)" in result.output
    assert "(waiting for more inputs)" in result.output and "effect size: SMD = " in result.output
    assert "saved effect: SMD = " in result.output
    record = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert record is not None and record["fields"]["design"] == {"value": "rct"}
    assert record["effects"][0]["source"] == "Table 2"
    assert _subjects(repo)[0].startswith("extract")


def test_extract_missing_only_asks_for_what_is_missing_and_quit_keeps_the_work(
    tmp_path: Path,
) -> None:
    repo = _form_repo(tmp_path, studies=2)
    rec_mod.set_field(repo, study=S1, handle="ethan", name="n_total", raw="100")
    _commit_all(repo)
    result = _cli(
        repo, "extract", "--missing", "--by", "ethan", input="rct\n:q\n"
    )  # design for study 1, then quit at retention_interval
    assert "N *" not in result.output and "Design" in result.output.replace("design", "Design")
    record = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert record is not None and set(record["fields"]) == {"n_total", "design"}
    assert not rec_mod.consensus_path(repo, S2).exists()
    assert "1 entry saved" in result.output


def test_extract_interactive_acknowledges_a_warning_with_a_note(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path)
    keystrokes = ["", "", "", "", "", "", "", "", ""]  # skip all nine fields
    keystrokes += ["two-group-means", "recall", "", ""]
    keystrokes += [
        "20",
        "9",
        "1",
        "20",
        "4.5",
        "1",
        "",
        "Typed from Figure 3",
    ]  # source blank, ack note
    keystrokes += [""]
    result = _cli(repo, "extract", S1, "--by", "ethan", input="\n".join(keystrokes) + "\n")
    assert "warning (large-effect)" in result.output
    record = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert record is not None and rec_mod.open_warnings(repo, S1, record) == []


def test_extract_with_nothing_to_do_says_so(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path, studies=1)
    for name, raw in (("n_total", "1"), ("design", "rct"), ("retention_interval", "NR")):
        rec_mod.set_field(repo, study=S1, handle="ethan", name=name, raw=raw)
    _commit_all(repo)
    assert "nothing to extract" in _cli(repo, "extract", "--missing", "--by", "ethan").output


# --- dual extraction -------------------------------------------------------------------------


def _dual_repo(tmp_path: Path) -> Repo:
    repo = _review(tmp_path, mode="dual", studies=2)
    for handle, interval in (("ethan", "1 week"), ("sam", "24 hours")):
        for name, raw in (("n_total", "100"), ("design", "rct"), ("retention_interval", interval)):
            rec_mod.set_field(repo, study=S1, handle=handle, name=name, raw=raw)
        rec_mod.add_effect(
            repo, study=S1, handle=handle, outcome="recall", design="two-group-means", inputs=MEANS
        )
    return _commit_all(repo)


def test_reconcile_lists_disagreements_and_the_agreement_rate(tmp_path: Path) -> None:
    repo = _dual_repo(tmp_path)
    out = _json(repo, "extract", "--reconcile")
    assert 0 < out["agreement"]["rate"] < 1
    [entry] = out["studies"]
    assert entry["study"] == S1 and entry["reviewers"] == ["ethan", "sam"]
    disagreement = next(i for i in entry["items"] if not i["agree"])
    assert disagreement["id"] == "field:retention_interval"
    assert disagreement["values"] == {"ethan": "168 hours", "sam": "24 hours"}
    text = _cli(repo, "extract", "--reconcile", "--list").output
    assert "items agree" in text and "field:retention_interval" in text


def test_reconcile_one_item_from_the_command_line(tmp_path: Path) -> None:
    """openspec scenario: the reconciler chooses ethan's value with a rationale."""
    repo = _dual_repo(tmp_path)
    out = _json(
        repo, "extract", "--reconcile", S1, "--by", "ethan",
        "--item", "field:retention_interval", "--choose", "ethan",
        "--rationale", "The paper says one week in the Methods.",
    )  # fmt: skip
    assert out["choice"] == "ethan"
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert consensus is not None and consensus["fields"]["retention_interval"]["value"] == 168
    assert _subjects(repo)[0].startswith("reconcile")
    _cli(repo, "extract", "--reconcile", S1, "--by", "ethan", "--item", "field:nope",
         "--choose", "ethan", "--rationale", "x", code=EXIT_USAGE)  # fmt: skip
    _cli(repo, "extract", "--reconcile", "--by", "ethan", "--item", "field:x", code=EXIT_USAGE)


def test_reconcile_interactively(tmp_path: Path) -> None:
    repo = _dual_repo(tmp_path)
    keystrokes = [
        "y",  # accept the agreements
        "sam",  # retention_interval -> sam
        "",  # (rationale empty ...)
        "The Methods table gives 24 hours.",
    ]
    result = _cli(
        repo, "extract", "--reconcile", "--by", "ethan", input="\n".join(keystrokes) + "\n"
    )
    assert "ethan: 168 hours" in result.output and "sam: 24 hours" in result.output
    assert result.output.count("Rationale:") == 2  # the empty answer is asked for again
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert consensus is not None and consensus["fields"]["retention_interval"]["value"] == 24
    assert "reconciled" in result.output and not [
        c for c in rec_mod.all_records(repo) if c[0] == "consensus" and c[2]["study"] != S1
    ]


# --- risk of bias ----------------------------------------------------------------------------


def _rob_repo(tmp_path: Path, instrument: str = "rob2", **kwargs: Any) -> Repo:
    repo = _form_repo(tmp_path, **kwargs)
    _cli(repo, "rob", "init", "--instrument", instrument, "--by", "ethan")
    return repo


def test_rob_init_copies_the_instrument_and_refuses_to_overwrite(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path)
    out = _json(repo, "rob", "init", "--instrument", "robins-i", "--by", "ethan")
    assert out["instrument"] == "ROBINS-I" and len(out["domains"]) == 7
    assert _subjects(repo)[0].startswith("rob-init")
    assert "already exists" in _cli(repo, "rob", "init", "--by", "ethan", code=EXIT_USAGE).output
    _cli(repo, "rob", "init", "--instrument", "rob2", "--overwrite", "--by", "ethan")
    assert (
        "no built-in"
        in _cli(repo, "rob", "init", "--instrument", "x", "--overwrite", code=EXIT_USAGE).output
    )


def test_rob_before_init_points_at_init(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path)
    assert "rob init" in _cli(repo, "rob", "--list", code=EXIT_USAGE).output


def test_rob_scripted_answers_then_a_judgement(tmp_path: Path) -> None:
    repo = _rob_repo(tmp_path)
    first = _json(repo, "rob", S1, "--by", "ethan", "--domain", "D1", "--answer", "1.2=Y")
    assert first["needed"] == "1.1" and first["suggested"] is None
    done = _json(
        repo, "rob", S1, "--by", "ethan", "--domain", "D1", "--answer", "1.1=Y", "--answer", "1.3=N",
        "--judgement", "low", "--support", "Central randomisation", "--source", "p. 3",
    )  # fmt: skip
    assert done["judgement"] == "low" and done["suggested"] == "low"
    assert _subjects(repo)[0].startswith("rob")
    assert not [i for i in verify_repository(repo).issues if i.severity == "error"]


def test_rob_override_needs_a_justification_and_keeps_both(tmp_path: Path) -> None:
    repo = _rob_repo(tmp_path)
    base = ("rob", S1, "--by", "ethan", "--domain", "D1", "--answer", "1.1=Y",
            "--answer", "1.2=Y", "--answer", "1.3=N")  # fmt: skip
    result = _cli(repo, *base, "--judgement", "some-concerns", code=EXIT_USAGE)
    assert "justification" in result.output
    out = _json(
        repo, *base, "--judgement", "some-concerns", "--override-justification", "Registry differs"
    )
    assert out["suggested"] == "low" and out["judgement"] == "some-concerns"
    saved = rob.read_assessment(rob.consensus_path(repo, S1))
    assert (
        saved is not None and saved["domains"]["D1"]["override_justification"] == "Registry differs"
    )
    _cli(repo, "rob", S1, "--by", "ethan", "--domain", "D1", "--answer", "9.9=Y", code=EXIT_USAGE)
    _cli(repo, "rob", S1, "--by", "ethan", "--domain", "D1", "--answer", "1.1", code=EXIT_USAGE)
    _cli(repo, "rob", "--domain", "D1", "--by", "ethan", code=EXIT_USAGE)


def test_rob_interactively_walks_the_domains_and_the_overall(tmp_path: Path) -> None:
    repo = _rob_repo(tmp_path, studies=1)
    keystrokes: list[str] = []
    for domain_answers in (
        ["Y", "Y", "N"],  # D1: 1.2, 1.1, 1.3 in the order the flow needs them
    ):
        keystrokes += domain_answers
    keystrokes += [
        "",
        "Sequence generated centrally",
        "p. 3",
    ]  # D1 judgement (default), support, source
    keystrokes += [":q"]  # quit at D2's first question
    result = _cli(repo, "rob", S1, "--by", "ethan", input="\n".join(keystrokes) + "\n")
    assert "the algorithm suggests: low" in result.output
    saved = rob.read_assessment(rob.consensus_path(repo, S1))
    assert saved is not None and saved["domains"]["D1"]["judgement"] == "low"
    assert "D2" not in saved["domains"] or "judgement" not in saved["domains"]["D2"]


def test_rob_list_shows_the_judgements(tmp_path: Path) -> None:
    repo = _rob_repo(tmp_path, studies=2)
    _cli(repo, "rob", S1, "--by", "ethan", "--domain", "D3", "--judgement", "high")
    out = _json(repo, "rob", "--by", "ethan")
    judged = {
        s["study"]: {d["domain"]: d["judgement"] for d in s["domains"]} for s in out["studies"]
    }
    assert judged[S1]["D3"] == "high" and judged[S2]["D3"] is None
    assert "D3:high" in _cli(repo, "rob", "--by", "ethan", "--list").output


def test_rob_dual_reviewers_reconcile(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path, mode="dual", studies=1)
    _cli(repo, "rob", "init", "--by", "ethan")
    _cli(repo, "rob", S1, "--by", "ethan", "--domain", "D3", "--judgement", "low")
    _cli(repo, "rob", S1, "--by", "sam", "--domain", "D3", "--judgement", "high")
    listing = _json(repo, "rob", "--reconcile")
    assert listing["studies"][0]["items"][0]["agree"] is False
    assert "D3" in _cli(repo, "rob", "--reconcile", "--list").output
    out = _json(
        repo, "rob", "--reconcile", S1, "--by", "ethan", "--domain", "D3", "--choose", "sam",
        "--rationale", "Outcome assessors were not blinded.",
    )  # fmt: skip
    assert out["choice"] == "sam"
    consensus = rob.read_assessment(rob.consensus_path(repo, S1))
    assert consensus is not None and consensus["domains"]["D3"]["judgement"] == "high"
    _cli(repo, "rob", "--reconcile", "--by", "ethan", "--domain", "D3", code=EXIT_USAGE)


def test_rob_reconcile_interactively(tmp_path: Path) -> None:
    repo = _form_repo(tmp_path, mode="dual", studies=1)
    _cli(repo, "rob", "init", "--by", "ethan")
    for handle, judgement in (("ethan", "low"), ("sam", "high")):
        _cli(repo, "rob", S1, "--by", handle, "--domain", "D3", "--judgement", judgement)
    result = _cli(
        repo, "rob", "--reconcile", "--by", "ethan",
        input="other\nsome-concerns\nBoth were partly right.\n",
    )  # fmt: skip
    assert "ethan: low  |  sam: high" in result.output
    consensus = rob.read_assessment(rob.consensus_path(repo, S1))
    assert consensus is not None and consensus["domains"]["D3"]["judgement"] == "some-concerns"


# --- moderators in filters and the export ----------------------------------------------------


def test_filter_on_rob_overall_selects_the_low_risk_studies(tmp_path: Path) -> None:
    """openspec scenario: `rob_overall == 'low'` includes only studies with an overall low risk."""
    repo = _rob_repo(tmp_path, studies=3)
    for domain in ("D1", "D2", "D3", "D4", "D5"):
        _cli(repo, "rob", S1, "--by", "ethan", "--domain", domain, "--judgement", "low")
    _cli(repo, "rob", S1, "--by", "ethan", "--domain", "overall", "--judgement", "low")
    _cli(repo, "rob", S2, "--by", "ethan", "--domain", "D1", "--judgement", "high")
    low = json.loads(
        _cli(repo, "records", "list", "--format", "json", "--filter", "rob_overall == 'low'").output
    )
    assert [r["id"] for r in low] == ["rec_" + S1[4:]]
    high = json.loads(
        _cli(repo, "records", "list", "--format", "json", "--filter", "rob.D1 == 'high'").output
    )
    assert [r["id"] for r in high] == ["rec_" + S2[4:]]


def test_the_export_carries_the_risk_of_bias_columns(tmp_path: Path) -> None:
    repo = _rob_repo(tmp_path, studies=2)
    for study_id in (S1, S2):
        for name, raw in (("n_total", "100"), ("design", "rct"), ("retention_interval", "1 week")):
            rec_mod.set_field(repo, study=study_id, handle="ethan", name=name, raw=raw)
        rec_mod.add_effect(
            repo,
            study=study_id,
            handle="ethan",
            outcome="recall",
            design="two-group-means",
            inputs=MEANS,
        )
    _cli(repo, "rob", S1, "--by", "ethan", "--domain", "D1", "--judgement", "low")
    text = _cli(repo, "export", "effects", "--format", "csv").output
    header = text.splitlines()[0].split(",")
    assert "rob_overall" in header and "rob.D1" in header
    rows = {
        line.split(",")[0]: dict(zip(header, line.split(","), strict=False))
        for line in text.splitlines()[1:]
    }
    assert rows[S1]["rob.D1"] == "low" and rows[S2]["rob.D1"] == ""


# --- strata status ---------------------------------------------------------------------------


def test_status_lists_studies_with_missing_values_and_the_next_step(tmp_path: Path) -> None:
    repo = _screened(_form_repo(tmp_path, studies=3))
    for n in (1, 2):
        for name, raw in (("n_total", "100"), ("design", "rct"), ("retention_interval", "1 week")):
            rec_mod.set_field(repo, study=study(n), handle="ethan", name=name, raw=raw)
    _commit_all(repo)
    out = _json(repo, "status")
    assert out["extraction"]["studies"] == 3 and out["extraction"]["complete"] == 2
    assert list(out["extraction"]["missing"]) == [study(3)]
    assert out["next_action"] == "strata extract --missing"
    text = _cli(repo, "status").output
    assert (
        "EXTRACTION" in text and f"{study(3)}  missing: n_total, design, retention_interval" in text
    )


def test_status_says_nothing_about_extraction_before_a_form_exists(tmp_path: Path) -> None:
    repo = _commit_all(init_review(tmp_path))
    decide(repo, "full-text", add_records(repo, 2))
    _commit_all(repo)
    assert _json(repo, "status")["extraction"] is None
    assert "EXTRACTION" not in _cli(repo, "status").output


def test_status_points_at_reconcile_when_dual_reviewers_differ(tmp_path: Path) -> None:
    repo = _screened(_dual_repo(tmp_path))
    out = _json(repo, "status")
    assert out["extraction"]["reconcile"] == 1
    assert out["next_action"] == "strata extract --reconcile"


def test_a_late_required_field_queues_every_completed_study(tmp_path: Path) -> None:
    """openspec scenario: completed extractions + a new required field -> reported and queued."""
    repo = _form_repo(tmp_path, studies=3)
    for n in (1, 2, 3):
        for name, raw in (("n_total", "100"), ("design", "rct"), ("retention_interval", "1 week")):
            rec_mod.set_field(repo, study=study(n), handle="ethan", name=name, raw=raw)
    grown = {
        **FORM,
        "version": 2,
        "fields": [*FORM["fields"], {"name": "setting", "type": "text", "required": True}],
    }
    repo.path("extraction", "schema.yaml").write_text(dump_yaml_str(grown), encoding="utf-8")
    _commit_all(repo)
    queue = _json(repo, "extract", "--missing", "--by", "ethan")["studies"]
    assert [q["study"] for q in queue] == [study(1), study(2), study(3)]
    assert all(q["missing"] == ["setting"] for q in queue)
    assert _json(repo, "status")["extraction"]["complete"] == 0
