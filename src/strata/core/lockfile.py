"""An advisory lock on a file that the operating system lets go of when its holder dies.

The repository lock (openspec:architecture#concurrency-and-locking) used to be a file whose mere
existence meant "held". A process killed while holding it left the file behind, and every later
write waited out the timeout and failed until a person found and deleted it. Here the lock is the
operating system's (`flock` on POSIX, a byte-range lock on Windows), so a holder that dies, however
it dies, no longer holds anything.

The file still carries the holder's process id, for the message a waiter gets, and still goes away
on a clean release, because `.strata/lock` is not git-ignored in existing review repositories and a
file left lying there would make the working tree look dirty. If a file is found with an id in it
after the lock has been taken, its holder cannot have released it cleanly (a clean release empties
and removes it), so it is reported as reclaimed.

Local file systems only: `flock` is unreliable over some network file systems, as git itself warns
for a working copy.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path

POLL_SECONDS = 0.1

if sys.platform == "win32":  # pragma: no cover - exercised by the Windows job in CI
    import msvcrt

    # Windows refuses reads of a byte that another handle has locked, and a waiter reads the
    # holder's id from the start of the file, so the lock is taken on a byte far past any text.
    _LOCK_OFFSET = 1 << 20

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
        return True

    def _names_this_file(path: Path, fd: int) -> bool:
        # Windows will not unlink a file another handle has open, so there is no unlink race.
        return True

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _names_this_file(path: Path, fd: int) -> bool:
        """Whether `path` still names the file `fd` has open.

        A holder releasing cleanly unlinks the file *before* it lets go of the lock, so a waiter
        that opened the old file and then wins the lock holds a file nobody can find any more, and
        another process could create and lock a new one at the same path. The waiter must start
        again.
        """
        try:
            on_disk = os.stat(path)
        except FileNotFoundError:
            return False
        held = os.fstat(fd)
        return (on_disk.st_dev, on_disk.st_ino) == (held.st_dev, held.st_ino)


class LockTimeout(Exception):
    """The lock stayed held by someone else for the whole timeout."""

    def __init__(self, holder: int | None, timeout: float) -> None:
        super().__init__(f"lock still held after {timeout:g}s")
        self.holder = holder
        self.timeout = timeout


def _read_holder(fd: int) -> int | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        text = os.read(fd, 32).decode("ascii", errors="ignore").strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


def acquire(path: Path, timeout: float) -> tuple[int, int | None]:
    """Take the lock on `path`, waiting up to `timeout` seconds.

    Returns the open descriptor that holds it and the process id found in the file if its holder
    did not release it cleanly (`None` for an ordinary acquisition). Raises `LockTimeout`, naming
    the holder if it can be read.
    """
    deadline = time.monotonic() + timeout
    while True:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            locked = _try_lock(fd)
            while not locked and time.monotonic() < deadline:
                time.sleep(POLL_SECONDS)
                locked = _try_lock(fd)
            if not locked:
                raise LockTimeout(_read_holder(fd), timeout)
            if not _names_this_file(path, fd):
                os.close(fd)  # closing drops the lock just taken on a file that is gone
                continue
            previous = _read_holder(fd)
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            return fd, previous
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise


def release(path: Path, fd: int) -> None:
    """Let go of the lock: empty and remove the file, then close it.

    On POSIX the file is removed before the descriptor is closed, which is what lets a waiter
    notice (see `_names_this_file`). Where a waiter still has the file open Windows refuses to
    remove it; it is left empty for that waiter to use.
    """
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
    if sys.platform == "win32":  # pragma: no cover - exercised by the Windows job in CI
        os.close(fd)
        with contextlib.suppress(OSError):
            path.unlink()
        return
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    os.close(fd)
