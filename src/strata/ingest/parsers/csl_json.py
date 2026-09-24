"""CSL-JSON parser: the native format, and a near-passthrough.

Implements the CSL-JSON row of docs/spec/05-workflow-import.md §2.1. CSL-JSON
already matches the shape docs/spec/03-schemas.md §2 wants (minus the `strata`
extension object, attached later by the import pipeline), so this parser's
only job is to isolate malformed entries. Unlike every other format in this
package, a JSON document is not line-oriented: a single unparsable *document*
has no per-row recovery, but a single unparsable *entry* inside an otherwise
well-formed array does, and unknown CSL fields are preserved verbatim since
`strata` is not permitted to silently drop metadata (docs/spec/03-schemas.md
§2).
"""

from __future__ import annotations

import json

from strata.ingest.parsers import ParseResult, RejectedRow, has_title


def parse(text: str) -> ParseResult:
    result = ParseResult()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        result.rejected.append(RejectedRow(line=exc.lineno, raw=text, error=str(exc)))
        return result

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list):
        result.rejected.append(
            RejectedRow(line=None, raw=text, error="top-level CSL-JSON value is not an array")
        )
        return result

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            result.rejected.append(
                RejectedRow(line=index, raw=json.dumps(item), error="entry is not an object")
            )
            continue
        record = dict(item)
        record.setdefault("type", "article-journal")
        if not has_title(record):
            result.rejected.append(
                RejectedRow(line=index, raw=json.dumps(item), error="missing or empty title")
            )
            continue
        result.records.append(record)
    return result
