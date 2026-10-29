"""`strata.web.uploads`: openspec:web-uploads (change `add-web-ui-write-surfaces`, tasks 3.1-3.6).

The file-name sanitiser and the staging store are what stand between a stranger's bytes and the
working tree, so they are tested as properties as well as by example.
"""

import io
import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from strata import gitio
from strata.core.init import init_repository
from strata.web import uploads
from strata.web.uploads import (
    ExpiredBatch,
    UnknownBatch,
    UploadRefused,
    UploadStaging,
    check_declared_length,
    check_literature_file,
    sanitise_filename,
    unique_name,
)

MIB = uploads.MIB


# --------------------------------------------------------------------------- declared length


def _headers(**kw: str) -> dict[str, str]:
    return {k.replace("_", "-"): v for k, v in kw.items()}


def test_a_request_within_the_limit_passes() -> None:
    check_declared_length(
        _headers(content_length=str(5 * MIB)),
        "multipart/form-data; boundary=x",
        max_upload_bytes=100 * MIB,
    )


def test_a_request_over_the_limit_is_refused_naming_the_limit() -> None:
    with pytest.raises(UploadRefused) as caught:
        check_declared_length(
            _headers(content_length=str(150 * MIB)),
            "multipart/form-data; boundary=x",
            max_upload_bytes=100 * MIB,
        )

    assert caught.value.status_code == 413
    assert "150 MB" in caught.value.message and "limit is 100 MB" in caught.value.message
    assert "--max-upload-mb" in caught.value.message


def test_a_request_declaring_no_length_is_refused() -> None:
    with pytest.raises(UploadRefused) as caught:
        check_declared_length({}, "multipart/form-data; boundary=x", max_upload_bytes=100 * MIB)

    assert caught.value.status_code == 411
    assert "100 MB" in caught.value.message


def test_a_chunked_request_is_refused_even_if_it_also_declares_a_length() -> None:
    with pytest.raises(UploadRefused) as caught:
        check_declared_length(
            _headers(content_length="10", transfer_encoding="chunked"),
            "multipart/form-data; boundary=x",
            max_upload_bytes=100 * MIB,
        )

    assert caught.value.status_code == 411


def test_a_length_that_is_not_a_number_is_refused() -> None:
    with pytest.raises(UploadRefused) as caught:
        check_declared_length(
            _headers(content_length="lots"), "multipart/form-data", max_upload_bytes=100 * MIB
        )

    assert caught.value.status_code == 400


def test_an_ordinary_form_is_held_to_the_small_limit_whatever_the_upload_limit_is() -> None:
    with pytest.raises(UploadRefused) as caught:
        check_declared_length(
            _headers(content_length=str(2 * MIB)),
            "application/x-www-form-urlencoded",
            max_upload_bytes=500 * MIB,
        )

    assert caught.value.status_code == 413
    assert "limit is 1 MB" in caught.value.message
    assert "--max-upload-mb" not in caught.value.message


# ------------------------------------------------------------------------------- file names


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("export.ris", "export.ris"),
        ("Medline export (2026-10-01).RIS", "Medline export (2026-10-01).RIS"),
        ("../../protocol/criteria.yaml", "criteria.yaml"),
        ("..\\..\\protocol\\criteria.yaml", "criteria.yaml"),
        ("/etc/passwd", "passwd"),
        ("C:\\Users\\ada\\export.csv", "export.csv"),
        (".hidden.ris", "hidden.ris"),
        ("trailing dots...", "trailing dots"),
        ("résumé-études.bib", "résumé-études.bib"),
        ("a<b>c:d|e?f*g.ris", "a_b_c_d_e_f_g.ris"),
        ("nul\x00byte.ris", "nulbyte.ris"),
        ("tab\tand\nnewline.ris", "tabandnewline.ris"),
        ("CON.ris", "_CON.ris"),
        ("nul", "_nul"),
        ("com1.txt", "_com1.txt"),
        ("lpt9", "_lpt9"),
        ("", "upload"),
        ("...", "upload"),
        ("///", "upload"),
        (".ris", "ris"),
    ],
)
def test_file_names_become_safe_labels(label: str, expected: str) -> None:
    assert sanitise_filename(label) == expected


def test_a_very_long_name_is_cut_but_keeps_its_extension() -> None:
    name = sanitise_filename("x" * 400 + ".ris")

    assert len(name) <= uploads.MAX_NAME_CHARS
    assert name.endswith(".ris")


def test_an_absurd_extension_is_not_preserved_as_one() -> None:
    name = sanitise_filename("file." + "y" * 300)

    assert len(name) <= uploads.MAX_NAME_CHARS


@given(st.text(max_size=300))
@settings(max_examples=500, deadline=None)
def test_any_name_sanitises_to_a_safe_one(label: str) -> None:
    name = sanitise_filename(label)

    assert name
    assert "/" not in name and "\\" not in name
    assert not name.startswith(".")
    assert not name.endswith((" ", "."))
    assert len(name) <= uploads.MAX_NAME_CHARS
    assert all(ord(c) >= 32 and c != "\x7f" for c in name)
    assert Path(name).name == name
    assert name.split(".")[0].lower() not in {"con", "prn", "aux", "nul", "com1", "lpt1"}


@given(st.text(max_size=300))
@settings(max_examples=500, deadline=None)
def test_sanitising_twice_changes_nothing(label: str) -> None:
    once = sanitise_filename(label)

    assert sanitise_filename(once) == once


@given(st.text(max_size=300))
@settings(max_examples=200, deadline=None)
def test_a_sanitised_name_always_lands_inside_its_directory(label: str) -> None:
    directory = Path("/staging/batch")

    assert (directory / sanitise_filename(label)).parent == directory


def test_two_files_with_one_name_both_keep_a_name() -> None:
    taken: set[str] = set()
    names = []
    for _ in range(3):
        name = unique_name("export.ris", taken)
        taken.add(name)
        names.append(name)

    assert names == ["export.ris", "export-2.ris", "export-3.ris"]


def test_names_differing_only_in_case_are_told_apart() -> None:
    assert unique_name("Export.RIS", {"export.ris"}) == "Export-2.RIS"


def test_a_name_without_an_extension_is_numbered_at_the_end() -> None:
    assert unique_name("export", {"export"}) == "export-2"


# ------------------------------------------------------------------------------------ staging


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _staging(tmp_path: Path, clock: _Clock | None = None, **kw: object) -> UploadStaging:
    root = tmp_path / "review"
    if not root.exists():
        init_repository(root, title="Staging", actor_handle="ethan", actor_name="Ethan")
    return UploadStaging(
        root,
        max_total_bytes=10 * MIB,
        clock=clock or _Clock(),
        **kw,  # type: ignore[arg-type]
    )


def _file(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


def test_a_batch_is_staged_and_read_back(tmp_path: Path) -> None:
    staging = _staging(tmp_path)

    batch = staging.stage(
        [("../evil/Export One.ris", _file("TY  - JOUR")), ("b.csv", _file("a,b"))],
        context={"search": "S-01-medline"},
    )
    again = staging.open(batch.id)

    assert [f.name for f in again.files] == ["Export One.ris", "b.csv"]
    assert [f.label for f in again.files] == ["../evil/Export One.ris", "b.csv"]
    assert again.files[0].path.read_text(encoding="utf-8") == "TY  - JOUR"
    assert again.files[0].path.parent == staging.root / batch.id
    assert again.context == {"search": "S-01-medline"}
    assert again.files[1].size == 3


def test_batch_ids_are_long_and_do_not_repeat(tmp_path: Path) -> None:
    staging = _staging(tmp_path)

    ids = {staging.stage([("a.ris", _file("x"))]).id for _ in range(50)}

    assert len(ids) == 50
    assert all(len(i) == 22 for i in ids)


@pytest.mark.parametrize(
    "bad",
    ["", "short", "../../etc", "a" * 21, "a" * 23, "a/b" + "c" * 19, "..\\" + "c" * 19, "é" * 22],
)
def test_a_forged_batch_reference_is_refused_without_touching_the_disk(
    tmp_path: Path, bad: str
) -> None:
    staging = _staging(tmp_path)

    with pytest.raises(UnknownBatch):
        staging.open(bad)
    staging.discard(bad)  # and removing one is a no-op, not a path operation


def test_an_id_that_was_never_issued_is_unknown(tmp_path: Path) -> None:
    staging = _staging(tmp_path)

    with pytest.raises(UnknownBatch, match="not recognised"):
        staging.open("A" * 22)


def test_a_batch_expires_after_an_hour_and_is_removed(tmp_path: Path) -> None:
    clock = _Clock()
    staging = _staging(tmp_path, clock)
    batch = staging.stage([("a.ris", _file("x"))])

    clock.now += uploads.BATCH_TTL_SECONDS - 1
    staging.open(batch.id)
    clock.now += 2
    with pytest.raises(ExpiredBatch, match="please upload the file again"):
        staging.open(batch.id)

    assert not (staging.root / batch.id).exists()


def test_discard_removes_the_batch(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    batch = staging.stage([("a.ris", _file("x"))])

    staging.discard(batch.id)

    assert not batch.directory.exists()
    with pytest.raises(UnknownBatch):
        staging.open(batch.id)


def test_staging_a_new_batch_purges_old_ones(tmp_path: Path) -> None:
    clock = _Clock()
    staging = _staging(tmp_path, clock)
    old = staging.stage([("a.ris", _file("x"))])
    clock.now += uploads.BATCH_TTL_SECONDS + 1

    fresh = staging.stage([("b.ris", _file("y"))])

    assert not old.directory.exists() and fresh.directory.exists()


def test_a_server_start_purges_everything_staged(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    staging.stage([("a.ris", _file("x"))])
    staging.stage([("b.ris", _file("y"))])

    assert staging.purge(everything=True) == 2
    assert list(staging.root.iterdir()) == []


def test_a_batch_that_never_completed_is_purged_by_age(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    abandoned = staging.root / ("B" * 22)
    abandoned.mkdir(parents=True)
    (abandoned / "half.ris").write_text("x", encoding="utf-8")

    # Judged by its directory's modification time against the (real) clock this test hands in.
    clock = _Clock()
    clock.now = abandoned.stat().st_mtime + uploads.BATCH_TTL_SECONDS + 5
    purger = UploadStaging(staging.repo_root, max_total_bytes=MIB, clock=clock)

    assert purger.purge() == 1
    assert not abandoned.exists()


def test_files_received_beyond_the_limit_are_refused_and_nothing_is_left(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="Staging", actor_handle="ethan", actor_name="Ethan")
    staging = UploadStaging(root, max_total_bytes=100)

    with pytest.raises(UploadRefused) as caught:
        staging.stage([("a.ris", io.BytesIO(b"x" * 60)), ("b.ris", io.BytesIO(b"y" * 60))])

    assert caught.value.status_code == 413
    assert list(staging.root.iterdir()) == []


def test_staging_nothing_is_a_programming_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _staging(tmp_path).stage([])


def test_a_staged_batch_leaves_the_working_tree_clean(tmp_path: Path) -> None:
    staging = _staging(tmp_path)

    staging.stage([("a.ris", _file("x"))])

    # Existing review repositories do not name the staging area in their .gitignore; the store
    # makes git ignore it locally, which is why this holds for them too.
    status = gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=staging.repo_root)
    assert status.stdout == ""


def test_the_local_exclusion_is_added_once(tmp_path: Path) -> None:
    staging = _staging(tmp_path)

    staging.stage([("a.ris", _file("x"))])
    staging.stage([("b.ris", _file("y"))])

    exclude = staging.repo_root / ".git" / "info" / "exclude"
    assert exclude.read_text(encoding="utf-8").splitlines().count("/.strata/tmp/") == 1


def test_batch_metadata_survives_a_restart_of_the_store(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    batch = staging.stage([("a.ris", _file("x"))])

    reopened = UploadStaging(staging.repo_root, max_total_bytes=MIB, clock=_Clock())

    assert reopened.open(batch.id).files[0].label == "a.ris"
    meta = json.loads((batch.directory / "batch.json").read_text(encoding="utf-8"))
    assert meta["files"][0]["name"] == "a.ris"


# ------------------------------------------------------------------------------------ formats

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "exports"


def _fixture_files() -> list[Path]:
    return sorted(p for p in _FIXTURES.rglob("*") if p.is_file() and p.name != "README.md")


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_golden_export_is_accepted_exactly_as_the_command_line_accepts_it(
    path: Path,
) -> None:
    # The format step of `strata import` and of the upload gate are one function.
    from strata.ingest import pipeline

    try:
        expected: str | None = pipeline.sniff_format(path)
    except pipeline.ImportPipelineError:
        expected = None

    if expected is None:
        with pytest.raises(UploadRefused):
            check_literature_file(path, path.name)
    else:
        assert check_literature_file(path, path.name) == expected


def test_a_pdf_is_refused_with_the_reason(tmp_path: Path) -> None:
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")

    with pytest.raises(UploadRefused) as caught:
        check_literature_file(pdf, "article.pdf")

    assert caught.value.status_code == 422
    assert "article.pdf" in caught.value.message
    assert "does not store full texts" in caught.value.message


def test_a_pdf_is_refused_whatever_it_is_called(tmp_path: Path) -> None:
    disguised = tmp_path / "export.ris"
    disguised.write_bytes(b"%PDF-1.4 not really an export")

    with pytest.raises(UploadRefused, match="does not store full texts"):
        check_literature_file(disguised, "export.ris")


def test_a_real_export_is_accepted_whatever_the_browser_called_it(tmp_path: Path) -> None:
    # The browser's declared content type never reaches the check: detection reads the file.
    ris = tmp_path / "export.ris"
    ris.write_text("TY  - JOUR\nTI  - A title\nER  - \n", encoding="utf-8")

    assert check_literature_file(ris, "export.ris") == "ris"


def test_an_unknown_extension_is_refused_for_the_reason_import_gives(tmp_path: Path) -> None:
    odd = tmp_path / "export.xyz"
    odd.write_text("whatever", encoding="utf-8")

    with pytest.raises(UploadRefused) as caught:
        check_literature_file(odd, "export.xyz")

    assert caught.value.message == (
        "export.xyz: unsupported file extension '.xyz'; pass --format explicitly"
    )
