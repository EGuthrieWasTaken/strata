import json
from pathlib import Path

from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol.criteria import add_criterion
from strata.protocol.pool import regenerate_all, regenerate_conflicts_tsv, regenerate_pool_tsv
from strata.protocol.screening import record_screen_decision


def _init(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    return open_repo(root)


def _add_record(repo, record_id: str, **overrides) -> None:  # type: ignore[no-untyped-def]
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": record_id,
        "type": "article-journal",
        "title": "A test record",
        "author": [{"family": "Smith", "given": "Jo"}],
        "issued": {"date-parts": [[2010]]},
        "container-title": "Journal of Testing",
        "DOI": "10.1234/test",
        "strata": {"canonical_key": f"sig:{record_id}", "canonical": True, "sources": []},
    }
    record.update(overrides)
    existing = []
    if records_path.exists():
        existing = [
            json.loads(line) for line in records_path.read_text().splitlines() if line.strip()
        ]
    existing.append(record)
    records_path.write_text("\n".join(json.dumps(r) for r in existing) + "\n", encoding="utf-8")


def test_pool_tsv_header_and_empty_body(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    text = regenerate_pool_tsv(repo)
    assert text == "record_id\ttiab\tfulltext\tstale\tyear\tfirst_author\ttitle\tjournal\tdoi\n"


def test_pool_tsv_reports_unscreened_by_default(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_record(repo, "rec_0000000000000001")
    text = regenerate_pool_tsv(repo)
    lines = text.splitlines()
    assert len(lines) == 2
    columns = lines[1].split("\t")
    assert columns[0] == "rec_0000000000000001"
    assert columns[1] == "unscreened"
    assert columns[2] == "unscreened"
    assert columns[3] == "-"
    assert columns[4] == "2010"
    assert columns[5] == "Smith"
    assert columns[7] == "Journal of Testing"
    assert columns[8] == "10.1234/test"

    on_disk = repo.path("derived", "pool.tsv").read_text(encoding="utf-8")
    assert on_disk == text


def test_pool_tsv_excludes_absorbed_records(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_record(repo, "rec_0000000000000001")
    _add_record(
        repo,
        "rec_0000000000000002",
        strata={"canonical_key": "sig:x", "canonical": False, "sources": []},
    )
    text = regenerate_pool_tsv(repo)
    assert "rec_0000000000000002" not in text


def test_pool_tsv_truncates_long_titles(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_record(repo, "rec_0000000000000001", title="x" * 200)
    text = regenerate_pool_tsv(repo)
    title_column = text.splitlines()[1].split("\t")[6]
    assert len(title_column) == 121  # 120 chars + the ellipsis
    assert title_column.endswith("…")


def test_pool_tsv_marks_stale_columns(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_record(repo, "rec_0000000000000001")
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="sam",
    )
    record_screen_decision(
        repo, stage="full-text", record_id="rec_0000000000000001", decision="include", actor="ethan"
    )
    record_screen_decision(
        repo, stage="full-text", record_id="rec_0000000000000001", decision="include", actor="sam"
    )
    add_criterion(
        repo,
        kind="exclusion",
        label="Under 18",
        definition="Mean sample age under 18.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Pilot extraction showed several child samples.",
        criterion_id="EXC-07",
    )
    text = regenerate_pool_tsv(repo)
    columns = text.splitlines()[1].split("\t")
    assert columns[1] == "include"
    assert columns[2] == "include"
    assert columns[3] == "tiab,ft"  # cascades to full-text too


def test_pool_tsv_handles_record_with_no_author(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_record(repo, "rec_0000000000000001", author=[])
    text = regenerate_pool_tsv(repo)
    columns = text.splitlines()[1].split("\t")
    assert columns[5] == ""


def test_pool_tsv_skips_unconfigured_stage(tmp_path: Path) -> None:
    from strata.core import manifest as manifest_mod

    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    doc = manifest_mod.load_manifest_doc(root)
    manifest_mod.set_value(doc, "screening.stages", ["title-abstract"])
    manifest_mod.write_manifest(root, doc)
    repo = open_repo(root)
    _add_record(repo, "rec_0000000000000001")
    text = regenerate_pool_tsv(repo)
    columns = text.splitlines()[1].split("\t")
    assert columns[1] == "unscreened"
    assert columns[2] == "unscreened"  # full-text isn't configured, defaults cleanly


def test_pool_tsv_reflects_adjudicated_decision(tmp_path: Path) -> None:
    from strata.core.events import append_new_event

    repo = _init(tmp_path)
    _add_record(repo, "rec_0000000000000001")
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="maybe",
        actor="sam",
    )
    append_new_event(
        repo.path("events", "adjudication", "ethan.ndjson"),
        ev="adjudicate",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": [],
            "rationale": "Adjudicated in favour of exclusion.",
        },
    )
    text = regenerate_pool_tsv(repo)
    columns = text.splitlines()[1].split("\t")
    assert columns[1] == "exclude"


def test_conflicts_tsv_empty_when_no_conflicts(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    text = regenerate_conflicts_tsv(repo)
    assert text == "record_id\tstage\topinions\tcriteria_cited\tfirst_seen\ttitle\n"


def test_conflicts_tsv_reports_opinions_and_criteria(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_record(repo, "rec_0000000000000001")
    add_criterion(
        repo,
        kind="exclusion",
        label="Wrong population",
        definition="Not the target population.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-04",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="sam",
        cited=["EXC-04"],
    )
    text = regenerate_conflicts_tsv(repo)
    lines = text.splitlines()
    assert len(lines) == 2
    columns = lines[1].split("\t")
    assert columns[0] == "rec_0000000000000001"
    assert columns[1] == "title-abstract"
    assert columns[2] == "ethan=include;sam=exclude"
    assert columns[3] == "EXC-04"

    on_disk = repo.path("derived", "conflicts.tsv").read_text(encoding="utf-8")
    assert on_disk == text


def test_regenerate_all_writes_every_derived_file(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_record(repo, "rec_0000000000000001")
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="sam",
    )
    regenerate_all(repo)
    for name in ("pool.tsv", "conflicts.tsv", "stale.tsv", "irr.json"):
        path = repo.path("derived", name)
        assert path.exists()
        assert path.read_text(encoding="utf-8")
