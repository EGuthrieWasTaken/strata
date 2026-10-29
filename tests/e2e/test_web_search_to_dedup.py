"""A review taken from nothing to deduplicated records using only HTTP requests
(OpenSpec change `add-web-ui-write-surfaces`, task 4.7).

Nobody touches a terminal: two database searches are recorded with their exports, each export is
reviewed and imported, the duplicate between them is merged, and the PRISMA diagram reflects it.
Afterwards the review passes `strata verify`, which is what shows the web interface wrote it the way
the command line would have.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core import records as records_mod
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol import pool as pool_mod
from strata.web.app import create_app

_TOKEN = "e2e-session-token-0123456789abcdef"
_MEDLINE = (
    "TY  - JOUR\n"
    "TI  - Spacing effects in learning: A temporal ridgeline of optimal retention\n"
    "AU  - Cepeda, Nicholas J.\nAU  - Vul, Edward\nPY  - 2008\nJO  - Psychological Science\n"
    "VL  - 19\nSP  - 1095\nEP  - 1102\nDO  - 10.1111/j.1467-9280.2008.02209.x\nER  - \n"
    "TY  - JOUR\nTI  - Retrieval practice and the testing effect\nAU  - Roediger, Henry L.\n"
    "PY  - 2006\nJO  - Current Directions\nDO  - 10.1111/j.1467-8721.2006.00415.x\nER  - \n"
)
# The same first paper as Embase prints it (no DOI, abbreviated names), and one other paper.
_EMBASE = (
    "TY  - JOUR\n"
    "TI  - Spacing effects in learning: a temporal ridgeline of optimal retention.\n"
    "AU  - Cepeda, N. J.\nAU  - Vul, E.\nPY  - 2008\nJO  - Psychol Sci\n"
    "VL  - 19\nSP  - 1095\nEP  - 1102\nER  - \n"
    "TY  - JOUR\nTI  - A study of something else entirely\nAU  - Nobody, A.\nPY  - 2015\n"
    "JO  - Other Journal\nDO  - 10.1000/other\nER  - \n"
)


def _post(client: TestClient, path: str, data: dict[str, str] | None = None, files=None):  # type: ignore[no-untyped-def]
    return client.post(
        path, data={"csrf_token": _TOKEN, **(data or {})}, files=files, follow_redirects=False
    )


def _record_and_import(client: TestClient, database: str, platform: str, ris: str) -> str:
    started = _post(
        client,
        "/searches",
        {
            "database": database,
            "platform": platform,
            "executed": "2026-03-04",
            "executed_by": "ethan",
            "query": f"the {database} strategy",
            "rationale": f"Recording the {database} search in the end-to-end test",
        },
        files=[("files", (f"{database.lower()}.ris", ris.encode(), "application/octet-stream"))],
    )
    assert started.status_code == 303
    review_path = started.headers["location"]
    review = client.get(review_path)
    assert review.status_code == 200 and "Nothing has been imported yet" in review.text
    done = _post(client, review_path, {"rationale": f"Importing the {database} export"})
    assert done.status_code == 200 and "Imported as" in done.text
    return review_path


def test_a_review_goes_from_nothing_to_deduplicated_records_using_only_http(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review"
    init_repository(root, title="Web only", actor_handle="ethan", actor_name="Ethan")
    client = TestClient(
        create_app(repo_root=root, actor="ethan", session_token=_TOKEN),
        base_url="http://127.0.0.1:8000",
    )
    assert client.get(f"/?token={_TOKEN}").status_code == 200

    # 1. Two searches, each with its export.
    _record_and_import(client, "MEDLINE", "Ovid", _MEDLINE)
    _record_and_import(client, "Embase", "Ovid", _EMBASE)
    listing = client.get("/searches").text
    assert "S-01-medline" in listing and "S-01-embase" in listing
    assert "No export yet" not in listing  # both have theirs
    assert 'data-testid="awaiting-export"' not in client.get("/").text
    assert len(records_mod.read_records(open_repo(root))) == 4  # 2 + 2 before deduplication

    # 2. The duplicate between the two exports is found, and merged on the person's say-so.
    queue = client.get("/dedup")
    assert "1 pair would auto-merge" in re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", queue.text))
    merged = _post(client, "/dedup/run", {"rationale": "Merging the obvious duplicate pair"})
    assert merged.status_code == 303

    # 3. Three papers remain, and the counts say where they came from.
    canonical = [r for r in records_mod.read_records(open_repo(root)) if r["strata"]["canonical"]]
    assert len(canonical) == 3
    counts = json.loads((root / "derived" / "counts.json").read_text(encoding="utf-8"))
    assert counts["identification"]["identified_total"] == 4
    assert counts["identification"]["databases"]["by_search"] == {
        "S-01-embase": 2,
        "S-01-medline": 2,
    }
    assert counts["totals"]["duplicates_removed"] == 1
    assert counts["totals"]["records_screened"] == 3
    assert counts["reconciled"] is True
    # And no derived file is left behind what the records now say (the pool lost the merged record).
    assert pool_mod.derived_drift(open_repo(root)) == []
    assert client.get("/prisma").status_code == 200
    assert client.get("/records").status_code == 200

    # 4. Everything is committed, and the repository is exactly what the command line would write.
    assert gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=root).stdout == ""
    verified = CliRunner().invoke(app, ["-C", str(root), "verify"])
    assert verified.exit_code == EXIT_OK, verified.output
    subjects = gitio.log(root, fmt="%s")
    assert sum(1 for s in subjects if s.startswith("search-add(")) == 2
    assert sum(1 for s in subjects if s.startswith("import(")) == 2
    assert sum(1 for s in subjects if s.startswith("dedup")) == 1
