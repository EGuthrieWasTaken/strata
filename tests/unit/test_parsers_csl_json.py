"""Unit tests for strata.ingest.parsers.csl_json beyond the golden fixtures."""

from __future__ import annotations

import json

from strata.ingest.parsers.csl_json import parse


def test_parse_empty_array() -> None:
    result = parse("[]")
    assert result.records == []
    assert result.rejected == []


def test_parse_unwraps_items_container() -> None:
    result = parse(json.dumps({"items": [{"title": "A", "type": "article-journal"}]}))
    assert result.records == [{"title": "A", "type": "article-journal"}]


def test_parse_top_level_object_without_items_is_rejected() -> None:
    result = parse(json.dumps({"title": "Not an array"}))
    assert result.records == []
    assert len(result.rejected) == 1
    assert "not an array" in result.rejected[0].error


def test_parse_preserves_unknown_fields_verbatim() -> None:
    item = {"title": "A", "some-custom-extension-field": {"nested": True}}
    result = parse(json.dumps([item]))
    assert result.records[0]["some-custom-extension-field"] == {"nested": True}


def test_parse_defaults_missing_type_to_article_journal() -> None:
    result = parse(json.dumps([{"title": "No type given"}]))
    assert result.records[0]["type"] == "article-journal"


def test_parse_invalid_json_syntax_rejected_with_line_number() -> None:
    result = parse("{not valid json")
    assert result.records == []
    assert result.rejected[0].line is not None
