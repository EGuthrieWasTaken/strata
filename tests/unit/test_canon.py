from strata.core.canon import CanonError, canonical_json, dump_yaml_str, serialise_envelope


def test_canonical_json_sorts_nested_keys() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_no_spaces() -> None:
    assert canonical_json({"a": [1, 2, 3]}) == '{"a":[1,2,3]}'


def test_canonical_json_non_ascii_literal() -> None:
    assert canonical_json({"title": "Über"}) == '{"title":"Über"}'


def test_canonical_json_null_vs_bool() -> None:
    assert canonical_json(None) == "null"
    assert canonical_json(True) == "true"
    assert canonical_json(False) == "false"


def test_canonical_json_rejects_nan_and_inf() -> None:
    try:
        canonical_json(float("nan"))
    except CanonError:
        pass
    else:
        raise AssertionError("expected CanonError")
    try:
        canonical_json(float("inf"))
    except CanonError:
        pass
    else:
        raise AssertionError("expected CanonError")


def test_canonical_json_deterministic_across_runs() -> None:
    value = {"z": 1, "a": {"y": 2, "x": 3}, "m": [3, 1, 2]}
    assert canonical_json(value) == canonical_json(value)
    assert canonical_json(value) == '{"a":{"x":3,"y":2},"m":[3,1,2],"z":1}'


def test_serialise_envelope_declared_order() -> None:
    envelope = {
        "digest": "sha256:d",
        "id": "ev_x",
        "ev": "note",
        "actor": "ethan",
        "seq": 1,
        "ts": "t",
        "body": {"b": 1, "a": 2},
        "tool": "strata/0.1.0",
    }
    line = serialise_envelope(envelope)
    assert line == (
        '{"ev":"note","id":"ev_x","ts":"t","actor":"ethan","seq":1,'
        '"body":{"a":2,"b":1},"tool":"strata/0.1.0","digest":"sha256:d"}'
    )


def test_serialise_envelope_omits_absent_fields() -> None:
    envelope = {
        "ev": "note",
        "id": "ev_x",
        "ts": "t",
        "actor": "ethan",
        "seq": 1,
        "body": {},
        "tool": "t",
    }
    line = serialise_envelope(envelope)
    assert "prev" not in line
    assert "digest" not in line


def test_dump_yaml_str_preserves_key_order() -> None:
    text = dump_yaml_str({"z": 1, "a": 2})
    assert text.index("z:") < text.index("a:")
