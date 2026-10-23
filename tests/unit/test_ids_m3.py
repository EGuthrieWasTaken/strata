"""Identifiers for reports, studies and effects (openspec:record-identity)."""

from __future__ import annotations

import pytest

from strata.core import ids


def test_report_id_mirrors_its_record() -> None:
    assert ids.report_id("rec_3kq8v1r0zx2m4a7b") == "rpt_3kq8v1r0zx2m4a7b"


def test_report_and_record_ids_round_trip() -> None:
    assert ids.record_id_for_report(ids.report_id("rec_3kq8v1r0zx2m4a7b")) == "rec_3kq8v1r0zx2m4a7b"


def test_singleton_study_shares_the_reports_characters() -> None:
    assert ids.singleton_study_id("rpt_3kq8v1r0zx2m4a7b") == "std_3kq8v1r0zx2m4a7b"


@pytest.mark.parametrize("bad", ["rpt_short", "rec_3kq8v1r0zx2m4a7b", "3kq8v1r0zx2m4a7b", ""])
def test_wrong_identifier_kinds_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        ids.record_id_for_report(bad)


def test_report_id_rejects_a_non_record() -> None:
    with pytest.raises(ValueError):
        ids.report_id("rpt_3kq8v1r0zx2m4a7b")


def test_new_study_ids_are_well_formed_and_distinct() -> None:
    generated = {ids.new_study_id() for _ in range(50)}
    assert len(generated) == 50
    for study in generated:
        assert study.startswith("std_")
        assert len(study) == 4 + 16
        assert study == study.lower()


def test_effect_id_carries_the_study_suffix_and_a_four_digit_sequence() -> None:
    assert ids.effect_id("std_7x2k9m1p3v5r8t0w", 1) == "eff_7x2k9m1p3v5r8t0w_0001"
    assert ids.effect_id("std_7x2k9m1p3v5r8t0w", 42) == "eff_7x2k9m1p3v5r8t0w_0042"


@pytest.mark.parametrize("sequence", [0, -1, 10000])
def test_effect_id_sequence_bounds(sequence: int) -> None:
    with pytest.raises(ValueError):
        ids.effect_id("std_7x2k9m1p3v5r8t0w", sequence)
