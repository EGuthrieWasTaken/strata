"""Canonical serialisation.

Implements docs/spec/02-repository-format.md §5: any file `strata` writes MUST
be byte-identical given the same logical content, on any platform. This module
is the single place that encodes JSON values; nothing else in the codebase
should call `json.dumps` on data destined for a committed file.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from io import StringIO
from typing import Any

from ruamel.yaml import YAML

# Event envelope field order, per docs/spec/02-repository-format.md §4.2.
ENVELOPE_KEY_ORDER = ("ev", "id", "ts", "actor", "seq", "body", "tool", "prev", "digest")


class CanonError(ValueError):
    """Raised when a value cannot be canonically serialised."""


def _canonical_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise CanonError("NaN and Infinity MUST NOT be emitted (02 §5.1)")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda kv: kv[0])
        body = ",".join(
            f"{json.dumps(str(k), ensure_ascii=False)}:{_canonical_value(v)}" for k, v in items
        )
        return "{" + body + "}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "[" + ",".join(_canonical_value(v) for v in value) + "]"
    raise CanonError(f"unsupported type for canonical serialisation: {type(value)!r}")


def canonical_json(value: Any) -> str:
    """Canonical JSON: sorted keys at every level, no NaN/Infinity, ensure_ascii=False."""
    return _canonical_value(value)


def serialise_envelope(envelope: Mapping[str, Any]) -> str:
    """Serialise an event envelope: declared top-level key order, sorted keys inside `body`.

    Fields absent from `envelope` (e.g. `prev` on the first line of a file, or
    `digest` while it is being computed) are simply omitted, in order.
    """
    unknown = set(envelope) - set(ENVELOPE_KEY_ORDER)
    if unknown:
        raise CanonError(f"unknown envelope field(s): {sorted(unknown)}")
    parts = []
    for key in ENVELOPE_KEY_ORDER:
        if key not in envelope:
            continue
        parts.append(f"{json.dumps(key, ensure_ascii=False)}:{_canonical_value(envelope[key])}")
    return "{" + ",".join(parts) + "}"


def dump_yaml_str(data: Any) -> str:
    """Block-style YAML, 2-space indent, no aliases/anchors, no flow mappings.

    Key order follows the insertion order of `data` (schema-declared order),
    per docs/spec/02-repository-format.md §5.3.
    """
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=2, offset=0)
    yaml.width = 4096
    yaml.allow_unicode = True
    yaml.representer.ignore_aliases = lambda _data: True
    stream = StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def load_yaml_str(text: str) -> Any:
    yaml = YAML(typ="rt")
    return yaml.load(text)
