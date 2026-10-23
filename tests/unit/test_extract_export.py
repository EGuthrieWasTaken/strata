"""`strata export effects` (openspec:data-extraction#exporting-effects-for-outside-analysis)."""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from strata.extract import export as ex
from strata.extract import records as rec_mod
from strata.stats import effect_sizes as es
from tests.unit.test_extract_records import MEANS, _review, study


def _filled(tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = _review(tmp_path, studies=3)
    for n, (n_total, interval) in enumerate((("148", "1 week"), ("90", "24 h")), start=1):
        rec_mod.set_field(repo, study=study(n), handle="ethan", name="n_total", raw=n_total)
        rec_mod.set_field(repo, study=study(n), handle="ethan", name="design", raw="rct")
        rec_mod.set_field(
            repo, study=study(n), handle="ethan", name="retention_interval", raw=interval
        )
        rec_mod.set_field(repo, study=study(n), handle="ethan", name="blinded", raw="yes")
    rec_mod.add_effect(
        repo, study=study(1), handle="ethan", outcome="recall", design="two-group-means",
        inputs=MEANS, timepoint="1 week", source="Table 2",
        moderators={"dose": 3, "condition": "spaced"},
    )  # fmt: skip
    rec_mod.add_effect(
        repo, study=study(1), handle="ethan", outcome="recognition", design="two-group-binary",
        inputs={"events1": 4, "n1": 123, "events2": 11, "n2": 139},
    )  # fmt: skip
    rec_mod.add_effect(
        repo, study=study(2), handle="ethan", outcome="recall", design="p-value-only",
        inputs={"p": 0.05, "n1": 30, "n2": 30, "direction": 1},
    )  # fmt: skip
    return repo


def _rows(table: ex.Table) -> list[dict[str, Any]]:
    return table.rows


def test_one_row_per_effect_with_the_columns_rma_needs(tmp_path: Path) -> None:
    table = ex.effect_table(_filled(tmp_path))
    assert len(table.rows) == 3
    assert table.columns[:9] == [
        "study_id", "effect_id", "outcome", "design", "timepoint", "label", "measure", "yi", "vi",
    ]  # fmt: skip
    for row in table.rows:
        assert row["study_id"].startswith("std_") and row["effect_id"].startswith("eff_")
    smd = es.smd(0.62, 0.18, 74, 0.48, 0.21, 74)
    first = table.rows[0]
    assert (first["measure"], first["yi"], first["vi"]) == ("SMD", smd.yi, smd.vi)


def test_study_fields_and_effect_moderators_are_joined_onto_each_row(tmp_path: Path) -> None:
    table = ex.effect_table(_filled(tmp_path))
    first = table.rows[0]
    assert (
        first["n_total"] == 148 and first["design"] == "two-group-means"
    )  # `design` is the effect's
    assert first["retention_interval"] == 168  # normalised to the field's unit
    assert first["blinded"] is True and first["timepoint"] == "1 week"
    assert (first["dose"], first["condition"]) == (3, "spaced")
    assert first["n1"] == 74 and first["sd2"] == 0.21 and first["source"] == "Table 2"
    other_study = table.rows[2]
    assert other_study["retention_interval"] == 24 and other_study["dose"] is None


def test_colliding_names_are_prefixed_not_overwritten(tmp_path: Path) -> None:
    table = ex.effect_table(_filled(tmp_path))
    assert "field_design" in table.columns  # the study's `design` field vs the effect's `design`
    assert table.rows[0]["field_design"] == "rct"
    assert len(set(table.columns)) == len(table.columns)


def test_provenance_flags_travel_with_the_effect(tmp_path: Path) -> None:
    table = ex.effect_table(_filled(tmp_path))
    from_p = [r for r in table.rows if r["design"] == "p-value-only"][0]
    assert from_p["derived_from_pvalue"] is True and from_p["derived_from"] == "p"
    binary = [r for r in table.rows if r["design"] == "two-group-binary"][0]
    assert binary["measure"] == "logOR" and binary["continuity_correction"] is None


def test_an_effect_that_cannot_be_computed_is_still_a_row(tmp_path: Path) -> None:
    repo = _filled(tmp_path)
    path = rec_mod.consensus_path(repo, study(1))
    record = rec_mod.read_record(path)
    assert record is not None
    record["effects"][0]["sd2"] = -1
    rec_mod.write_record(path, record, None)
    row = ex.effect_table(repo).rows[0]
    assert row["yi"] is None and row["vi"] is None and row["n1"] == 74


def test_only_included_studies_with_a_consensus_are_exported(tmp_path: Path) -> None:
    repo = _filled(tmp_path)  # study 3 has no extraction at all
    assert {r["study_id"] for r in ex.effect_table(repo).rows} == {study(1), study(2)}


def test_extra_study_level_columns_can_be_supplied(tmp_path: Path) -> None:
    table = ex.effect_table(
        _filled(tmp_path), extras=lambda s: {"rob_overall": "low"} if s == study(1) else {}
    )
    assert table.rows[0]["rob_overall"] == "low" and table.rows[2]["rob_overall"] is None


def test_an_empty_review_exports_just_a_header(tmp_path: Path) -> None:
    table = ex.effect_table(_review(tmp_path, studies=1))
    assert table.rows == []
    assert ex.render(table, "csv").decode().splitlines()[0].startswith("study_id,effect_id")
    assert ex.render(table, "json") == b"[]\n"
    assert ex.render(table, "rds").startswith(b"X\n")


# --- the formats -----------------------------------------------------------------------------


def _sample() -> ex.Table:
    return ex.Table(
        columns=["study_id", "yi", "n", "ok", "note"],
        rows=[
            {"study_id": "std_a", "yi": 0.5, "n": 74, "ok": True, "note": 'a, "b"\nc'},
            {"study_id": "std_b", "yi": None, "n": None, "ok": False, "note": "tab\there"},
        ],
    )


def test_csv_quotes_and_marks_missing_cells_empty() -> None:
    rows = list(csv.reader(io.StringIO(ex.render(_sample(), "csv").decode())))
    assert rows[0] == ["study_id", "yi", "n", "ok", "note"]
    assert rows[1] == ["std_a", "0.5", "74", "TRUE", 'a, "b"\nc']
    assert rows[2] == ["std_b", "", "", "FALSE", "tab\there"]


def test_tsv_never_lets_a_tab_or_newline_break_a_row() -> None:
    lines = ex.render(_sample(), "tsv").decode().splitlines()
    assert len(lines) == 3 and all(line.count("\t") == 4 for line in lines)
    assert lines[1].endswith('a, "b" c') and lines[2].endswith("tab here")


def test_json_is_an_array_of_objects() -> None:
    parsed = json.loads(ex.render(_sample(), "json"))
    assert parsed[0] == {"study_id": "std_a", "yi": 0.5, "n": 74, "ok": True, "note": 'a, "b"\nc'}
    assert parsed[1]["yi"] is None


def test_xlsx_is_a_valid_deterministic_workbook() -> None:
    blob = ex.render(_sample(), "xlsx")
    assert blob == ex.render(_sample(), "xlsx")
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert names == sorted(names) and "xl/worksheets/sheet1.xml" in names
        assert {i.date_time for i in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert "<v>0.5</v>" in sheet and 't="b"' in sheet and "std_a" in sheet


def test_rds_is_a_deterministic_r_data_frame() -> None:
    blob = ex.render(_sample(), "rds")
    assert blob == ex.render(_sample(), "rds")
    assert blob[:2] == b"X\n"  # XDR serialisation, readable by readRDS
    assert b"data.frame" in blob and b"row.names" in blob and b"study_id" in blob


def test_rds_and_xlsx_round_trip_through_independent_readers() -> None:
    rdata = pytest.importorskip("rdata")
    openpyxl = pytest.importorskip("openpyxl")
    frame = rdata.read_rds(io.BytesIO(ex.render(_sample(), "rds")))  # type: ignore[arg-type]
    assert list(frame.columns) == ["study_id", "yi", "n", "ok", "note"]
    assert frame["yi"].iloc[0] == 0.5 and bool(frame["ok"].iloc[0]) is True
    book = openpyxl.load_workbook(io.BytesIO(ex.render(_sample(), "xlsx")))
    assert [c.value for c in book["effects"][2]] == ["std_a", 0.5, 74, True, 'a, "b"\nc']


def test_an_unknown_format_is_refused() -> None:
    with pytest.raises(ex.ExportError, match="format"):
        ex.render(_sample(), "pdf")


def test_non_finite_numbers_cannot_be_written_to_rds() -> None:
    bad = ex.Table(columns=["x"], rows=[{"x": float("nan")}])
    with pytest.raises(ex.ExportError, match="NaN"):
        ex.render(bad, "rds")


def test_unicode_and_large_integers_survive_rds() -> None:
    table = ex.Table(columns=["a", "b"], rows=[{"a": "héllo", "b": 2**40}, {"a": None, "b": 1}])
    blob = ex.render(table, "rds")
    assert "héllo".encode() in blob
    assert ex.render(table, "csv").decode().splitlines()[1] == f"héllo,{2**40}"


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is not installed")
def test_the_csv_loads_in_metafor_rma(tmp_path: Path) -> None:
    """Task 6.5: `metafor::rma()` accepts the export and keeps each row's ids."""
    probe = subprocess.run(
        ["Rscript", "-e", "quit(status = !requireNamespace('metafor', quietly = TRUE))"],
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip("the metafor R package is not installed")
    path = tmp_path / "effects.csv"
    path.write_bytes(ex.render(ex.effect_table(_filled(tmp_path / "r")), "csv"))
    script = (
        "library(metafor); d <- read.csv(commandArgs(TRUE)[1], stringsAsFactors = FALSE);"
        "stopifnot(all(c('study_id', 'effect_id', 'yi', 'vi') %in% names(d)));"
        "d <- d[d$measure == 'SMD' & !is.na(d$yi), ]; fit <- rma(yi, vi, data = d);"
        "cat(nrow(d), length(unique(d$effect_id)), '\\n')"
    )
    result = subprocess.run(
        ["Rscript", "-e", script, str(path)], capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == ["2", "2"]


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is not installed")
def test_the_rds_loads_in_r_as_a_data_frame_with_the_same_values(tmp_path: Path) -> None:
    path = tmp_path / "effects.rds"
    path.write_bytes(ex.render(_sample(), "rds"))
    script = (
        "d <- readRDS(commandArgs(TRUE)[1]); stopifnot(is.data.frame(d));"
        "cat(names(d), '\\n'); cat(d$yi[1], d$n[1], as.character(d$ok[1]), d$study_id[1], '\\n')"
    )
    result = subprocess.run(
        ["Rscript", "-e", script, str(path)], capture_output=True, text=True, check=True
    )
    first, second = result.stdout.splitlines()
    assert first.split() == ["study_id", "yi", "n", "ok", "note"]
    assert second.split() == ["0.5", "74", "TRUE", "std_a"]
