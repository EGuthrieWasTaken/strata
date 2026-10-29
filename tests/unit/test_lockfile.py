"""The repository lock as the operating system's, not a file's existence
(openspec:architecture#concurrency-and-locking; OpenSpec change `add-web-ui-write-surfaces`, 2.1).

What matters is what happens to a lock when its holder does not get to clean up, and that two
holders can never overlap, including across the moment one of them removes the file.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from strata.core.repo import LockTimeoutError, Repo, repo_lock

_HOLDER = """
import os, sys, time
from pathlib import Path
from strata.core.repo import Repo, repo_lock

repo = Repo(root=Path(sys.argv[1]), config={})
with repo_lock(repo):
    # Say who the holder is: on Windows the process `Popen` starts can be a launcher that runs
    # the interpreter as a child, so `Popen.pid` is not the process that holds the lock. The file
    # is written whole and then moved into place, so a reader never sees half of it.
    ready = Path(sys.argv[2])
    ready.with_suffix(".tmp").write_text(str(os.getpid()), encoding="utf-8")
    os.replace(ready.with_suffix(".tmp"), ready)
    time.sleep(120)
"""


def _repo(tmp_path: Path) -> Repo:
    return Repo(root=tmp_path, config={})


def _try_to_take(repo: Repo, timeout: float, *, match: str) -> None:
    """Expect the lock to stay held by someone else for the whole `timeout`."""
    with pytest.raises(LockTimeoutError, match=match), repo_lock(repo, timeout=timeout):
        pass


def _wait_for(path: Path, process: subprocess.Popen[bytes], seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        if process.poll() is not None:
            raise AssertionError(f"the holder exited early with {process.returncode}")
        if time.monotonic() > deadline:
            raise AssertionError("the holder never took the lock")
        time.sleep(0.05)


def test_a_holder_killed_without_cleaning_up_does_not_strand_the_lock(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ready = tmp_path / "ready"
    holder = subprocess.Popen([sys.executable, "-c", _HOLDER, str(tmp_path), str(ready)])
    try:
        _wait_for(ready, holder)
        holder_pid = int(ready.read_text(encoding="utf-8"))

        # While it is alive, the lock is its, and a waiter is told who has it.
        _try_to_take(repo, 0.3, match=str(holder_pid))

        holder.kill()  # SIGKILL on POSIX, TerminateProcess on Windows: no chance to clean up
        holder.wait(timeout=30)

        with repo_lock(repo, timeout=10) as held:
            assert held.reclaimed_from == holder_pid
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=30)

    assert not (tmp_path / ".strata" / "lock").exists()


def test_a_waiter_gets_the_lock_when_the_holder_lets_go(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    holding = threading.Event()
    order: list[str] = []

    def hold() -> None:
        with repo_lock(repo):
            holding.set()
            time.sleep(0.4)
            order.append("holder done")

    thread = threading.Thread(target=hold)
    thread.start()
    assert holding.wait(10)
    with repo_lock(repo, timeout=10):
        order.append("waiter in")
    thread.join()

    assert order == ["holder done", "waiter in"]


def test_two_holders_never_overlap_even_as_the_file_is_removed_and_recreated(
    tmp_path: Path,
) -> None:
    """Every release removes the file while others may be waiting on it; none of that may let two
    holders in at once, or the read-modify-write below would lose updates."""
    repo = _repo(tmp_path)
    counter = tmp_path / "counter"
    counter.write_text("0", encoding="utf-8")
    failures: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(25):
                with repo_lock(repo, timeout=60):
                    value = int(counter.read_text(encoding="utf-8"))
                    time.sleep(0.0005)
                    counter.write_text(str(value + 1), encoding="utf-8")
        except BaseException as exc:  # pragma: no cover - reported below
            failures.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert counter.read_text(encoding="utf-8") == "200"
    assert not (tmp_path / ".strata" / "lock").exists()


def test_the_lock_file_holds_the_holders_process_id_only_while_held(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    lock_path = tmp_path / ".strata" / "lock"

    with repo_lock(repo):
        assert lock_path.read_text(encoding="ascii").strip().isdigit()

    assert not lock_path.exists()


def test_a_timeout_when_the_holder_cannot_be_named_says_unknown(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    lock_path = tmp_path / ".strata" / "lock"

    with repo_lock(repo):
        lock_path.write_text("not a number", encoding="ascii")
        _try_to_take(repo, 0.2, match="held by process unknown")
