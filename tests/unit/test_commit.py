import pytest
from hypothesis import given
from hypothesis import strategies as st

from strata.core.commit import (
    SUBJECT_LIMIT,
    RationaleRejectedError,
    StructuredCommit,
    fit_subject,
    validate_rationale,
)


def test_validate_rationale_rejects_none() -> None:
    with pytest.raises(RationaleRejectedError, match="required"):
        validate_rationale(None)


def test_validate_rationale_rejects_empty_and_whitespace() -> None:
    with pytest.raises(RationaleRejectedError, match="empty or whitespace"):
        validate_rationale("   ")


def test_validate_rationale_rejects_stoplisted_words_before_length_check() -> None:
    with pytest.raises(RationaleRejectedError, match="is not a rationale"):
        validate_rationale("fix")


def test_validate_rationale_rejects_too_short() -> None:
    with pytest.raises(RationaleRejectedError, match="at least 12 characters"):
        validate_rationale("short one")


def test_validate_rationale_accepts_and_strips() -> None:
    assert validate_rationale("  a genuinely explanatory rationale  ") == (
        "a genuinely explanatory rationale"
    )


def test_structured_commit_subject_format() -> None:
    commit = StructuredCommit(
        op="screen", scope="title-abstract", summary="exclude 1 record", body=None
    )
    assert commit.subject() == "screen(title-abstract): exclude 1 record"


def test_structured_commit_subject_without_scope() -> None:
    commit = StructuredCommit(op="init", scope=None, summary="initialise review", body=None)
    assert commit.subject() == "init: initialise review"


def test_structured_commit_subject_too_long_raises() -> None:
    commit = StructuredCommit(op="screen", scope=None, summary="x" * 70, body=None)
    with pytest.raises(ValueError, match="exceeds 72 characters"):
        commit.subject()


def test_structured_commit_message_body_and_trailers() -> None:
    commit = StructuredCommit(
        op="init",
        scope=None,
        summary="initialise review",
        body="Created by strata.",
        trailers={"Op": "init", "Actor": "ethan"},
    )
    message = commit.message()
    assert message.startswith("init: initialise review\n\nCreated by strata.\n\n")
    assert "Strata-Op: init" in message
    assert "Strata-Actor: ethan" in message
    assert message.endswith("\n")


def test_structured_commit_message_no_body_no_trailers() -> None:
    commit = StructuredCommit(op="init", scope=None, summary="initialise review", body=None)
    assert commit.message() == "init: initialise review\n"


# --------------------------------------------------------------------------------- fit_subject


def test_fit_subject_leaves_a_subject_that_fits_alone() -> None:
    assert fit_subject("screen", "title-abstract", "exclude 1 record") == (
        "title-abstract",
        "exclude 1 record",
    )
    assert fit_subject("init", None, "initialise review") == (None, "initialise review")


def test_fit_subject_shortens_the_summary_first() -> None:
    scope, summary = fit_subject(
        "import", "imp_01m62y4n2etk2j22640hhrn4z8", "import medline-export-2026-10-01-final-v2.ris"
    )

    assert scope == "imp_01m62y4n2etk2j22640hhrn4z8"
    assert summary.startswith("import medline-export") and summary.endswith("...")
    # It gives up only as much as it must, so the subject lands exactly on the limit.
    assert len(StructuredCommit("import", scope, summary, None).subject()) == SUBJECT_LIMIT


def test_fit_subject_shortens_the_scope_when_the_summary_cannot_give_enough() -> None:
    long_id = "S-01-" + "cochrane-central-register-of-controlled-trials"
    scope, summary = fit_subject("search-add", long_id, f"record search {long_id}")

    assert scope is not None and scope.endswith("...")
    assert scope != long_id
    assert len(StructuredCommit("search-add", scope, summary, None).subject()) <= SUBJECT_LIMIT


def test_fit_subject_never_cuts_the_operation() -> None:
    scope, summary = fit_subject("search-add", "S-1", "x" * 200)

    assert summary.endswith("...")
    assert StructuredCommit("search-add", scope, summary, None).subject().startswith("search-add(")


@given(
    scope=st.one_of(st.none(), st.text(min_size=1, max_size=120)),
    summary=st.text(min_size=1, max_size=200),
)
def test_fit_subject_always_yields_a_subject_that_fits(scope: str | None, summary: str) -> None:
    fitted_scope, fitted_summary = fit_subject("import", scope, summary)

    subject = StructuredCommit("import", fitted_scope, fitted_summary, None).subject()
    assert len(subject) <= SUBJECT_LIMIT


@given(
    scope=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
    summary=st.text(min_size=1, max_size=30),
)
def test_fit_subject_is_the_identity_when_the_subject_already_fits(
    scope: str | None, summary: str
) -> None:
    assert fit_subject("import", scope, summary) == (scope, summary)
