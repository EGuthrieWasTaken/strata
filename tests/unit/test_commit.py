import pytest

from strata.core.commit import RationaleRejectedError, StructuredCommit, validate_rationale


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
