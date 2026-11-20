"""Holding the repository lock as someone else would, for tests of what waits for it.

`repo_lock` is re-entrant within a thread, so a test that takes it and then runs an operation in the
same thread would only re-enter it. `held_elsewhere` takes it in another thread, as another process
or another request of the web server would.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator

from strata.core.repo import Repo, repo_lock


@contextlib.contextmanager
def held_elsewhere(repo: Repo) -> Iterator[None]:
    taken = threading.Event()
    done = threading.Event()

    def hold() -> None:
        with repo_lock(repo):
            taken.set()
            done.wait(120)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert taken.wait(30), "the lock could not be taken"
    try:
        yield
    finally:
        done.set()
        thread.join(30)
