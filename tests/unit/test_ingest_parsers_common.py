"""Unit tests for strata.ingest.parsers: the shared decode/normalisation helpers."""

from __future__ import annotations

from strata.ingest.parsers import decode_bytes, has_title, normalise_newlines


def test_decode_bytes_plain_utf8() -> None:
    text, encoding = decode_bytes("café".encode())
    assert text == "café"
    assert encoding == "utf-8"


def test_decode_bytes_strips_bom_and_reports_it() -> None:
    text, encoding = decode_bytes(b"\xef\xbb\xbfhello")
    assert text == "hello"
    assert encoding == "utf-8-sig"


def test_decode_bytes_falls_back_to_cp1252() -> None:
    raw = "“smart quotes”".encode("cp1252")
    text, encoding = decode_bytes(raw)
    assert text == "“smart quotes”"
    assert encoding == "cp1252"


def test_decode_bytes_falls_back_to_latin1_as_last_resort() -> None:
    # 0x81 is unassigned in CP1252 but valid (as U+0081) in Latin-1.
    raw = b"\x81"
    text, encoding = decode_bytes(raw)
    assert encoding == "latin-1"
    assert text == "\x81"


def test_normalise_newlines_handles_crlf_and_lone_cr() -> None:
    assert normalise_newlines("a\r\nb\rc\n") == "a\nb\nc\n"


def test_has_title() -> None:
    assert has_title({"title": "Something"})
    assert not has_title({"title": ""})
    assert not has_title({"title": "   "})
    assert not has_title({})
