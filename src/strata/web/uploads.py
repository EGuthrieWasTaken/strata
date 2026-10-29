"""How `strata serve` accepts files from a browser: openspec:web-uploads.

An upload is the one place the web interface reads bytes someone else chose, so everything about
it is decided here rather than in the routes that use it:

- **Limits are checked on the declared length, before the body is read** (`check_declared_length`).
  The ASGI server enforces the declared length (a body longer than it declares is cut off or
  refused by the HTTP layer), so the declaration can be trusted; a request that makes none cannot be
  checked and is refused.
- **A file name from the browser is a label, never a path** (`sanitise_filename`).
- **An upload waits in a staging area until a person confirms it** (`UploadStaging`): a directory
  under `.strata/tmp/uploads/` named by a server-generated id nobody can guess, referred to by that
  id and never by a path, deleted on confirm, discard, start-up and after an hour. Nothing in it is
  ever committed.
- **Only bibliographic exports are taken** (`check_literature_file`).
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from strata import gitio
from strata.ingest import pipeline

MIB = 1024 * 1024
DEFAULT_MAX_UPLOAD_MB = 100
MAX_FILES_PER_REQUEST = 20
MAX_FIELDS_PER_REQUEST = 200
MAX_FIELD_BYTES = MIB  # a non-file form field (a query string, a note)
MAX_URLENCODED_BYTES = MIB  # an ordinary form post
BATCH_TTL_SECONDS = 60 * 60
MAX_NAME_CHARS = 120
_COPY_CHUNK = MIB

STAGING_DIR = (".strata", "tmp", "uploads")
_BATCH_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")
_NOT_RECOGNISED = "that upload is not recognised; please upload the file again"


class UploadRefused(Exception):
    """An upload that is turned away, with the HTTP status and the message to give."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ------------------------------------------------------------------------------------ limits


def _megabytes(size: int) -> str:
    return f"{size / MIB:g} MB"


def check_declared_length(
    headers: Mapping[str, str], content_type: str, *, max_upload_bytes: int
) -> None:
    """Refuse a form post whose declared size is missing, malformed or over its limit.

    Run before the body is read. A file upload (`multipart/form-data`) may be as large as the
    server's upload limit; any other form is small.
    """
    multipart = content_type.lower().startswith("multipart/")
    limit = max_upload_bytes if multipart else MAX_URLENCODED_BYTES
    declared = headers.get("content-length")
    if declared is None or "transfer-encoding" in headers:
        raise UploadRefused(
            411,
            "this request does not say how large it is, so it cannot be checked against "
            f"the limit of {_megabytes(limit)}",
        )
    if not declared.isdigit():
        raise UploadRefused(400, "the request's Content-Length is not a number")
    size = int(declared)
    if size > limit:
        hint = " (raise it with strata serve --max-upload-mb)" if multipart else ""
        raise UploadRefused(
            413,
            f"this request is {_megabytes(size)}; the limit is {_megabytes(limit)}{hint}",
        )


# ------------------------------------------------------------------------------- file names

_RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)
_SAFE_PUNCTUATION = frozenset(" .-_()+,[]")


def _safe_char(char: str) -> str:
    if char.isalnum() or char in _SAFE_PUNCTUATION:
        return char
    return "_"


def sanitise_filename(label: str) -> str:
    """A name safe to create inside the staging directory, from whatever the browser called it.

    The browser's name is never trusted: only its last component after either kind of separator is
    kept, control characters and anything outside a conservative set are replaced, dots and spaces
    that Windows would strip are removed from the ends, device names are defused, and the length is
    capped. The extension is kept, because format detection depends on it. A name that sanitises
    to nothing becomes `upload`. Idempotent.
    """
    name = unicodedata.normalize("NFC", label)
    name = re.split(r"[\\/]", name)[-1]
    name = "".join(_safe_char(c) for c in name if unicodedata.category(c) not in {"Cc", "Cf"})
    name = name.strip(" .")
    name = name.lstrip(".")
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""
    if len(extension) > 16:
        stem, extension = name, ""
    if len(stem) + (len(extension) + 1 if extension else 0) > MAX_NAME_CHARS:
        stem = stem[: MAX_NAME_CHARS - (len(extension) + 1 if extension else 0)].rstrip(" .")
    if stem.split(".")[0].lower() in _RESERVED_DEVICE_NAMES:
        stem = "_" + stem
    if not stem.strip(" ._"):
        stem = "upload" + (stem if "." in stem else "")
    return f"{stem}.{extension}" if extension else stem


def unique_name(name: str, taken: set[str]) -> str:
    """`name`, or `name` with `-2`, `-3`... before its extension, so no two files in a batch share
    one (compared without regard to case, because the staging area may sit on a file system that
    ignores it)."""
    if name.lower() not in {t.lower() for t in taken}:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""
    counter = 2
    while True:
        candidate = f"{stem}-{counter}" + (f".{extension}" if extension else "")
        if candidate.lower() not in {t.lower() for t in taken}:
            return candidate
        counter += 1


# ----------------------------------------------------------------------------------- staging


class BatchError(Exception):
    """A staged upload cannot be used; the message is safe to show to the person."""


class UnknownBatch(BatchError):
    pass


class ExpiredBatch(BatchError):
    pass


@dataclass(frozen=True)
class StagedFile:
    name: str  # as stored: sanitised and unique within the batch
    label: str  # as the browser called it, for display only
    size: int
    path: Path


@dataclass(frozen=True)
class StagedBatch:
    id: str
    directory: Path
    files: tuple[StagedFile, ...]
    created: float
    context: dict[str, Any]


class UploadStaging:
    """Where uploads wait for confirmation. See the module docstring."""

    def __init__(
        self,
        repo_root: Path,
        *,
        max_total_bytes: int,
        ttl: float = BATCH_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repo_root = repo_root
        self.root = repo_root.joinpath(*STAGING_DIR)
        self.max_total_bytes = max_total_bytes
        self.ttl = ttl
        self._clock = clock

    # -- writing

    def stage(
        self,
        uploads: Sequence[tuple[str, BinaryIO]],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> StagedBatch:
        """Copy the uploaded files (browser name, open file) into a new batch.

        Raises `UploadRefused` (413) if the bytes actually received exceed the upload limit,
        whatever the request declared, and removes what it had written.
        """
        if not uploads:
            raise ValueError("there is nothing to stage")
        self.purge()
        # Local to this clone, so no tracked file changes and no commit is needed: existing review
        # repositories do not ignore the staging area in their .gitignore.
        gitio.ensure_local_exclude(self.repo_root, ["/.strata/tmp/"])
        batch_id = secrets.token_urlsafe(16)
        directory = self.root / batch_id
        directory.mkdir(parents=True)
        staged: list[StagedFile] = []
        taken: set[str] = set()
        total = 0
        try:
            for label, source in uploads:
                name = unique_name(sanitise_filename(label), taken)
                taken.add(name)
                path = directory / name
                size = 0
                with path.open("wb") as out:
                    while chunk := source.read(_COPY_CHUNK):
                        size += len(chunk)
                        total += len(chunk)
                        if total > self.max_total_bytes:
                            raise UploadRefused(
                                413,
                                f"these files are larger than the limit of "
                                f"{_megabytes(self.max_total_bytes)}",
                            )
                        out.write(chunk)
                staged.append(StagedFile(name=name, label=label, size=size, path=path))
            batch = StagedBatch(
                id=batch_id,
                directory=directory,
                files=tuple(staged),
                created=self._clock(),
                context=dict(context or {}),
            )
            (directory / "batch.json").write_text(
                json.dumps(
                    {
                        "created": batch.created,
                        "context": batch.context,
                        "files": [
                            {"name": f.name, "label": f.label, "size": f.size} for f in staged
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return batch

    # -- reading

    def open(self, batch_id: str) -> StagedBatch:
        """The batch with this id. Raises `UnknownBatch` for an id that is malformed or was never
        issued (it is checked against a strict pattern before it is ever joined to a path), and
        `ExpiredBatch`, after removing it, for one that has outlived its hour."""
        if not _BATCH_ID.fullmatch(batch_id):
            raise UnknownBatch(_NOT_RECOGNISED)
        directory = self.root / batch_id
        try:
            meta = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise UnknownBatch(_NOT_RECOGNISED) from None
        if self._clock() - float(meta["created"]) > self.ttl:
            shutil.rmtree(directory, ignore_errors=True)
            raise ExpiredBatch("that upload has expired; please upload the file again")
        files = tuple(
            StagedFile(
                name=f["name"],
                label=f["label"],
                size=int(f["size"]),
                path=directory / f["name"],
            )
            for f in meta["files"]
        )
        return StagedBatch(
            id=batch_id,
            directory=directory,
            files=files,
            created=float(meta["created"]),
            context=dict(meta.get("context", {})),
        )

    # -- removing

    def discard(self, batch_id: str) -> None:
        """Remove a batch (a malformed or unknown id removes nothing)."""
        if _BATCH_ID.fullmatch(batch_id):
            shutil.rmtree(self.root / batch_id, ignore_errors=True)

    def purge(self, *, everything: bool = False) -> int:
        """Remove batches older than the lifetime, or all of them; returns how many."""
        if not self.root.is_dir():
            return 0
        now = self._clock()
        removed = 0
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            if not everything:
                try:
                    created = float(
                        json.loads((directory / "batch.json").read_text(encoding="utf-8"))[
                            "created"
                        ]
                    )
                except (OSError, ValueError, KeyError):
                    # Never completed, or damaged: judged by when the directory was last touched.
                    created = directory.stat().st_mtime
                if now - created <= self.ttl:
                    continue
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1
        return removed


# ------------------------------------------------------------------------------------ formats

_PDF_MAGIC = b"%PDF-"
_FULL_TEXT_MESSAGE = (
    "strata does not store full texts: it tracks them by identifier and leaves the document with "
    "you (or in Zotero). Upload the export from the database search, not the article itself"
)


def check_literature_file(path: Path, label: str) -> str:
    """The format of an uploaded bibliographic export, or `UploadRefused` (422) if it is not one.

    The format is decided by the same code `strata import` uses, from the file's name and
    content, never from the content type the browser declared. A PDF is refused with the reason,
    whatever it is called.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(len(_PDF_MAGIC))
    except OSError:
        raise UploadRefused(422, f"{label}: the file could not be read") from None
    if head == _PDF_MAGIC or path.suffix.lower() == ".pdf":
        raise UploadRefused(422, f"{label}: {_FULL_TEXT_MESSAGE}")
    try:
        return pipeline.sniff_format(path)
    except pipeline.ImportPipelineError as exc:
        raise UploadRefused(422, f"{label}: {exc}") from None
