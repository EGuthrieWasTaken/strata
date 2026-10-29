"""Compare what two surfaces left in git, with the parts that legitimately differ masked.

Used by the tests that hold the command line and the web interface to the same result
(openspec:architecture#mutating-operations-are-shared-services).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from strata import gitio

_IMPORT_ID = re.compile(r"imp_[0-9a-z]{26}")
_EVENT_ID = re.compile(r"ev_[0-9a-z]{26}")
_STUDY_ID = re.compile(r"std_[0-9a-z]{16}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_TEMP_DIR = re.compile(r"/tmp/\S*?/(?=[^/\s]+\.(?:ris|json|csv|xlsx))")


def mask(text: str) -> str:
    """Generated ids, timestamps and the hash chain that covers them, and temp paths."""
    text = _IMPORT_ID.sub("<IMPORT>", text)
    text = _EVENT_ID.sub("<EVENT>", text)
    text = _STUDY_ID.sub("<STUDY>", text)
    text = _TIMESTAMP.sub("<TS>", text)
    return _TEMP_DIR.sub("", text)


def committed_snapshot(root: Path, revision: str = "HEAD") -> dict[str, str]:
    """What `revision` changed: its commit message, and every file it touched, masked.

    Event files are reduced to their type, actor and body, because everything else in an event is
    an id, a timestamp or a digest. Everything else (record ids, manifests, raw files, the PRISMA
    counts, the search files) is compared as written.
    """
    names = gitio.run(["show", "--name-only", "--format=", revision], cwd=root).stdout
    message = gitio.run(["log", "-1", "--format=%B", revision], cwd=root).stdout
    snapshot = {"<message>": mask(message)}
    for name in sorted(n for n in names.splitlines() if n):
        content = gitio.run(["show", f"{revision}:{name}"], cwd=root).stdout
        if name.startswith("events/"):
            content = "\n".join(
                json.dumps(
                    {k: json.loads(line)[k] for k in ("ev", "actor", "body")}, sort_keys=True
                )
                for line in content.splitlines()
            )
        snapshot[mask(name)] = mask(content)
    return snapshot
