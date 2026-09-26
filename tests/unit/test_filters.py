"""Unit tests for strata.core.filters, per openspec:filter-language."""

from __future__ import annotations

from typing import Any

import pytest

from strata.core.filters import (
    FilterEvaluationError,
    FilterSyntaxError,
    matches_filter,
    parse,
)


def _resolver(values: dict[str, Any]) -> Any:
    def resolve(field: str) -> Any:
        if field not in values:
            raise FilterEvaluationError(f"unknown field {field!r}")
        return values[field]

    return resolve


def _check(expr: str, values: dict[str, Any]) -> bool:
    return matches_filter(expr, _resolver(values))


# ---- comparisons -------------------------------------------------------------


def test_equality() -> None:
    assert _check("year == 2020", {"year": 2020})
    assert not _check("year == 2020", {"year": 2019})


def test_inequality() -> None:
    assert _check("year != 2020", {"year": 2019})
    assert not _check("year != 2020", {"year": 2020})


@pytest.mark.parametrize(
    ("op", "left", "right", "expected"),
    [
        ("<", 1999, 2000, True),
        ("<", 2000, 2000, False),
        ("<=", 2000, 2000, True),
        (">", 2001, 2000, True),
        (">", 2000, 2000, False),
        (">=", 2000, 2000, True),
    ],
)
def test_ordered_comparisons(op: str, left: int, right: int, expected: bool) -> None:
    assert _check(f"year {op} {right}", {"year": left}) is expected


def test_ordered_comparison_type_mismatch_raises() -> None:
    with pytest.raises(FilterEvaluationError, match="cannot compare"):
        _check("year < 'x'", {"year": 2020})


def test_string_literal_single_and_double_quotes() -> None:
    assert _check("title == 'Hello'", {"title": "Hello"})
    assert _check('title == "Hello"', {"title": "Hello"})


def test_string_literal_escape() -> None:
    assert _check(r"title == 'it\'s'", {"title": "it's"})


def test_number_literal_float() -> None:
    assert _check("score == 0.5", {"score": 0.5})


def test_boolean_and_null_literals() -> None:
    assert _check("stale == true", {"stale": True})
    assert _check("stale == false", {"stale": False})
    assert _check("doi == null", {"doi": None})


# ---- in / not in ---------------------------------------------------------------


def test_in_operator() -> None:
    assert _check("year in [2019, 2020]", {"year": 2020})
    assert not _check("year in [2019, 2020]", {"year": 2021})


def test_not_in_operator() -> None:
    assert _check("year not in [2019, 2020]", {"year": 2021})
    assert not _check("year not in [2019, 2020]", {"year": 2019})


def test_in_requires_list_value() -> None:
    with pytest.raises(FilterEvaluationError, match="requires a list"):
        _check("year in 2020", {"year": 2020})


def test_empty_list_literal() -> None:
    assert not _check("year in []", {"year": 2020})


# ---- contains -----------------------------------------------------------------


def test_contains_on_string_is_case_insensitive_substring() -> None:
    assert _check("title contains 'wor'", {"title": "Hello World"})
    assert _check("title contains 'WOR'", {"title": "Hello World"})
    assert not _check("title contains 'xyz'", {"title": "Hello World"})


def test_contains_on_string_requires_string_value() -> None:
    with pytest.raises(FilterEvaluationError, match="requires a string value"):
        _check("title contains 5", {"title": "Hello"})


def test_contains_on_list_tests_membership() -> None:
    assert _check("authors contains 'Smith'", {"authors": ["Smith", "Jones"]})
    assert not _check("authors contains 'Doe'", {"authors": ["Smith", "Jones"]})


def test_contains_on_unsupported_type_raises() -> None:
    with pytest.raises(FilterEvaluationError, match="not supported"):
        _check("year contains 5", {"year": 2020})


# ---- matches --------------------------------------------------------------------


def test_matches_basic_regex() -> None:
    assert _check("title matches 'wor.d'", {"title": "hello world"})
    assert not _check("title matches '^world'", {"title": "hello world"})


def test_matches_requires_string_field() -> None:
    with pytest.raises(FilterEvaluationError, match="requires a string field"):
        _check("year matches '2020'", {"year": 2020})


def test_matches_requires_string_pattern() -> None:
    with pytest.raises(FilterEvaluationError, match="requires a string pattern"):
        _check("title matches 5", {"title": "hello"})


def test_matches_invalid_regex_raises() -> None:
    with pytest.raises(FilterEvaluationError, match="invalid regex"):
        _check("title matches '('", {"title": "hello"})


@pytest.mark.parametrize(
    "pattern",
    ["(a+)+b", "(a*)+b", "(a+)*b", "((a+)+)+b", "(a+|b)+c"],
)
def test_matches_rejects_nested_unbounded_repeat(pattern: str) -> None:
    # These are the textbook catastrophic-backtracking shape (an unbounded
    # repeat nested inside another); rejected statically, before any regex
    # ever runs -- see strata.core.filters._is_catastrophic's docstring for
    # why a runtime timeout doesn't work here instead.
    with pytest.raises(FilterEvaluationError, match="exponential"):
        _check(f"title matches {pattern!r}", {"title": "a" * 10})


def test_matches_allows_a_single_unbounded_repeat() -> None:
    assert _check("title matches 'a+b'", {"title": "aaab"})


def test_matches_allows_alternation_without_nested_repeat() -> None:
    # A repeated group over plain (multi-character, so Python's parser
    # doesn't fold them into a single character class) alternatives -- no
    # branch has its own unbounded repeat -- isn't the catastrophic shape.
    assert _check("title matches '(ab|cd)+e'", {"title": "abcde"})


def test_matches_allows_bounded_repeat_of_a_group_containing_a_repeat() -> None:
    # The outer repeat is bounded ({1,3}), not unbounded, so nesting an
    # unbounded inner repeat inside it doesn't have the exponential property.
    assert _check("title matches '(a+){1,3}b'", {"title": "aaab"})


# ---- logical operators -------------------------------------------------------


def test_and() -> None:
    assert _check("year == 2020 and title == 'X'", {"year": 2020, "title": "X"})
    assert not _check("year == 2020 and title == 'X'", {"year": 2020, "title": "Y"})


def test_or() -> None:
    assert _check("year == 2020 or year == 2021", {"year": 2021})
    assert not _check("year == 2020 or year == 2021", {"year": 2022})


def test_not() -> None:
    assert _check("not (year == 2020)", {"year": 2021})
    assert not _check("not (year == 2020)", {"year": 2020})


def test_and_has_higher_precedence_than_or() -> None:
    # "A or B and C" must parse as "A or (B and C)", not "(A or B) and C".
    # With A true and C false the two groupings disagree -- the correct one
    # gives True (True or anything is True), the wrong one gives False
    # (True and False) -- so this actually discriminates between the parses.
    assert _check("year == 1 or year == 2 and title == 'no'", {"year": 1, "title": "yes"})


def test_not_binds_tighter_than_and() -> None:
    assert _check("not year == 1 and title == 'x'", {"year": 2, "title": "x"})
    assert not _check("not year == 1 and title == 'x'", {"year": 1, "title": "x"})


def test_parentheses_override_precedence() -> None:
    assert _check("(year == 1 or year == 2) and title == 'x'", {"year": 2, "title": "x"})


def test_double_not() -> None:
    assert _check("not not year == 1", {"year": 1})


def test_bare_field_is_truthy_check() -> None:
    assert _check("stale", {"stale": True})
    assert not _check("stale", {"stale": False})
    assert not _check("stale", {"stale": None})


# ---- spec examples, verbatim -------------------------------------------------


def test_spec_example_year_and_tiab() -> None:
    assert _check("year >= 2000 and tiab == 'include'", {"year": 2005, "tiab": "include"})


def test_spec_example_abstract_contains_and_not_journal_contains() -> None:
    values = {"abstract": "a randomised trial", "journal": "Psych Science"}
    assert _check("abstract contains 'randomi' and not (journal contains 'Proceedings')", values)


def test_spec_example_stale_and_fulltext() -> None:
    assert _check("stale == true and fulltext == 'include'", {"stale": True, "fulltext": "include"})


def test_spec_example_rob_in_list() -> None:
    assert _check("rob_overall in ['low', 'some-concerns']", {"rob_overall": "low"})


def test_spec_example_criteria_contains() -> None:
    assert _check("criteria contains 'EXC-03'", {"criteria": ["EXC-01", "EXC-03"]})


# ---- syntax errors ------------------------------------------------------------


def test_unexpected_character() -> None:
    with pytest.raises(FilterSyntaxError, match="unexpected character"):
        parse("year == 2020 & title == 'x'")


def test_unexpected_trailing_character() -> None:
    with pytest.raises(FilterSyntaxError, match="unexpected character"):
        parse("year == 1 %")


def test_unbalanced_paren() -> None:
    with pytest.raises(FilterSyntaxError):
        parse("(year == 2020")


def test_trailing_input() -> None:
    with pytest.raises(FilterSyntaxError, match="trailing"):
        parse("year == 2020 2020")


def test_missing_value_after_operator() -> None:
    with pytest.raises(FilterSyntaxError, match="expected a value"):
        parse("year ==")


def test_primary_requires_field_or_paren() -> None:
    with pytest.raises(FilterSyntaxError, match="expected a field name"):
        parse("== 5")


def test_empty_expression() -> None:
    with pytest.raises(FilterSyntaxError, match="expected a field name"):
        parse("")


def test_unterminated_string_is_unexpected_character() -> None:
    with pytest.raises(FilterSyntaxError):
        parse("title == 'unterminated")


def test_unknown_field_propagates_from_resolver() -> None:
    with pytest.raises(FilterEvaluationError, match="unknown field"):
        _check("nonexistent == 1", {})
