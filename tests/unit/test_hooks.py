from strata.core.hooks import validate_commit_message_trailers


def test_unstructured_style_always_passes() -> None:
    assert validate_commit_message_trailers("anything\n\nStrata-Op broken", structured=False) == []


def test_message_with_no_trailers_passes() -> None:
    message = "fix: correct a typo\n\nNo trailers here at all.\n"
    assert validate_commit_message_trailers(message, structured=True) == []


def test_well_formed_trailer_block_passes() -> None:
    message = (
        "screen(title-abstract): exclude 1 record\n\nBody text.\n\n"
        "Strata-Op: screen\nStrata-Actor: ethan\n"
    )
    assert validate_commit_message_trailers(message, structured=True) == []


def test_trailer_block_must_be_contiguous() -> None:
    message = "subject\n\nStrata-Op: screen\nnot a trailer\nStrata-Actor: ethan\n"
    errors = validate_commit_message_trailers(message, structured=True)
    assert any("contiguous" in e for e in errors)


def test_trailer_block_must_be_preceded_by_blank_line() -> None:
    message = "subject\nStrata-Op: screen\n"
    errors = validate_commit_message_trailers(message, structured=True)
    assert any("blank line" in e for e in errors)


def test_trailers_starting_at_line_one_need_no_blank_line() -> None:
    message = "Strata-Op: screen\n"
    assert validate_commit_message_trailers(message, structured=True) == []


def test_malformed_trailer_line_reported() -> None:
    message = "subject\n\nStrata-Op\n"
    errors = validate_commit_message_trailers(message, structured=True)
    assert any("malformed trailer" in e for e in errors)
