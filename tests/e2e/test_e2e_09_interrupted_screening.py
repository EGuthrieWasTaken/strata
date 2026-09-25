"""E2E-09: interrupted screening (SIGKILL mid-session), then resume with no
lost decisions.

docs/spec/14-testing.md §5: "Interrupted screening (SIGKILL mid-session),
then resume with no lost decisions." docs/spec/04-git-integration.md §2.4:
"Decisions are appended to the event log immediately (so nothing is lost if
the process dies) but left uncommitted. A commit is created when the user
ends a screening session[...]." That is exactly the boundary this test
exercises: `typer.testing.CliRunner` runs in-process and can't be SIGKILLed
mid-call, so this is the one E2E test in this suite that drives a real
`strata` subprocess, feeds it one decision, kills it before it can write a
second, and checks what survived on disk -- the first decision's `screen`
event (fsynced immediately) but no commit (batched screening commits only
at session end), then that a fresh, ordinary `strata screen` session
resumes cleanly and accounts for every record exactly once.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core.repo import open_repo
from strata.core.verify import verify_repository
from strata.protocol.screening import all_screen_events

runner = CliRunner()

_RECORDS = """\
[
  {"id": "1", "type": "article-journal", "title": "First record in the interrupted batch",
   "author": [{"family": "Cepeda", "given": "Nicholas"}], "issued": {"date-parts": [[2008]]},
   "container-title": "Psychological Science", "DOI": "10.1111/e2e09.one",
   "abstract": "The record decided before the process is killed."},
  {"id": "2", "type": "article-journal", "title": "Second record in the interrupted batch",
   "author": [{"family": "Roediger", "given": "Henry"}], "issued": {"date-parts": [[2009]]},
   "container-title": "Medical Education", "DOI": "10.1111/e2e09.two",
   "abstract": "The record whose prompt is showing when the process dies."},
  {"id": "3", "type": "article-journal", "title": "Third record in the interrupted batch",
   "author": [{"family": "Bjork", "given": "Robert"}], "issued": {"date-parts": [[2010]]},
   "container-title": "Annual Review of Psychology", "DOI": "10.1111/e2e09.three",
   "abstract": "The record never reached before the interruption."}
]
"""


def _run(args: list[str], input: str | None = None) -> object:  # noqa: A002
    result = runner.invoke(app, args, input=input)
    assert result.exit_code == EXIT_OK, result.output
    return result


@pytest.mark.req("E2E-09")
def test_sigkill_mid_session_loses_nothing_and_resumes_cleanly(tmp_path: Path) -> None:
    root = tmp_path / "review"
    _run(
        [
            "init",
            str(root),
            "--title",
            "E2E-09 interrupted screening",
            "--actor",
            "ethan",
            "--actor-name",
            "Ethan",
        ]
    )
    export = tmp_path / "records.json"
    export.write_text(_RECORDS, encoding="utf-8")
    _run(
        [
            "--why",
            "Importing the search results for this review.",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--via",
            "registry",
        ]
    )

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "strata.cli.main",
            "--why",
            "Screening the imported batch for the review.",
            "-C",
            str(root),
            "screen",
            "title-abstract",
            "--by",
            "ethan",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None

        # Decide the first record ("include", no note) and wait for the
        # second record's prompt to appear -- proof the first decision was
        # fully processed (event appended) before we kill the process.
        proc.stdin.write("i\n\n")
        proc.stdin.flush()

        deadline = time.monotonic() + 15.0
        saw_second_prompt = False
        lines: list[str] = []
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line)
            if "record 2 of 3" in line:
                saw_second_prompt = True
                break
        assert saw_second_prompt, f"never saw the second record's prompt; got: {lines!r}"

        # Kill it *before* answering the second prompt -- nothing for
        # record 2 should ever reach disk.
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    assert proc.returncode != 0

    # Exactly one decision survived: appended immediately, per §2.4.
    repo = open_repo(root)
    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 1
    assert events[0]["body"]["decision"] == "include"

    # Batched screening commits only at session end -- a killed session
    # never got there, so the working tree is (correctly) still dirty.
    assert gitio.is_dirty(root)

    # No torn/corrupt write: the event log is still well-formed.
    report = verify_repository(repo)
    assert report.ok, report.issues

    # Resume with an ordinary session: the already-decided record is not
    # re-offered, and the other two are, in full.
    resume_result = _run(
        [
            "--why",
            "Resuming screening after the interrupted session.",
            "-C",
            str(root),
            "screen",
            "title-abstract",
            "--by",
            "ethan",
        ],
        input="i\n\ni\n\n",
    )
    assert "2 decision" in resume_result.output

    repo = open_repo(root)
    events = all_screen_events(repo, "title-abstract")
    # Every canonical record has exactly one decision -- nothing lost,
    # nothing duplicated.
    assert len(events) == 3
    assert len({e["body"]["record"] for e in events}) == 3

    assert not gitio.is_dirty(root)
    report = verify_repository(repo)
    assert report.ok, report.issues
