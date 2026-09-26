"""Integration tests for `strata records`/`why`/`fix`, openspec:cli."""

import json
from pathlib import Path

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_USAGE, app

runner = CliRunner()

_RECORD = (
    '[{"title": "Learning and spacing effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}, "container-title": "Psychological Science", '
    '"volume": "19", "page": "1095", "DOI": "10.1000/spacing"}]'
)

# Word-reordered near-duplicate: same title token *set* (Jaccard title_sim =
# 1.0) but a different word order -- and so a different canonical key at
# import time -- so this becomes a genuinely separate record for `strata
# dedup` to merge, rather than an exact-id match the import pipeline would
# just fold into _RECORD's existing sources. See test_cli_dedup.py's
# _AUTO_MERGE_A/_AUTO_MERGE_B for the same technique.
_DUPLICATE_OF_RECORD = (
    '[{"title": "Spacing and learning effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}, "container-title": "Psychological Science", '
    '"volume": "19", "page": "1095"}]'
)


def _init(tmp_path: Path, name: str = "review") -> Path:
    root = tmp_path / name
    result = runner.invoke(
        app,
        ["init", str(root), "--title", "Test Review", "--actor", "ethan", "--actor-name", "Ethan"],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def _import(
    root: Path, tmp_path: Path, name: str, content: str, search_id: str | None = None
) -> None:
    export = tmp_path / name
    export.write_text(content, encoding="utf-8")
    args = [
        "--why",
        f"importing {name}",
        "-C",
        str(root),
        "import",
        str(export),
        "--by",
        "ethan",
        "--via",
        "registry",
    ]
    if search_id:
        args += ["--search", search_id]
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_OK, result.output


def _record_id(root: Path) -> str:
    records_path = root / "records" / "records.ndjson"
    line = next(line for line in records_path.read_text(encoding="utf-8").splitlines() if line)
    return json.loads(line)["id"]


def test_records_list_tsv_default(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    result = runner.invoke(app, ["-C", str(root), "records", "list"])
    assert result.exit_code == EXIT_OK, result.output
    assert "id\tyear\tauthors\ttitle" in result.output
    assert "Cepeda, Vul" in result.output
    assert "2008" in result.output


def test_records_list_json_format(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    result = runner.invoke(app, ["-C", str(root), "records", "list", "--format", "json"])
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["title"] == "Learning and spacing effects in memory consolidation"


def test_records_list_csl_format_strips_strata_block(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    result = runner.invoke(app, ["-C", str(root), "records", "list", "--format", "csl"])
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    assert "strata" not in payload[0]
    assert payload[0]["DOI"] == "10.1000/spacing"


def test_records_list_invalid_format_rejected(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "records", "list", "--format", "xml"])
    assert result.exit_code == EXIT_USAGE, result.output


def test_records_list_filter_matches(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    result = runner.invoke(
        app, ["-C", str(root), "records", "list", "--filter", "year == 2008", "--format", "json"]
    )
    assert result.exit_code == EXIT_OK, result.output
    assert len(json.loads(result.output)) == 1


def test_records_list_filter_no_match(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    result = runner.invoke(
        app, ["-C", str(root), "records", "list", "--filter", "year == 1999", "--format", "json"]
    )
    assert result.exit_code == EXIT_OK, result.output
    assert json.loads(result.output) == []


def test_records_list_filter_syntax_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "records", "list", "--filter", "year >>"])
    assert result.exit_code == EXIT_USAGE, result.output
    assert "invalid --filter" in result.output


def test_records_list_filter_evaluation_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    result = runner.invoke(
        app, ["-C", str(root), "records", "list", "--filter", "nonexistent_field == 1"]
    )
    assert result.exit_code == EXIT_USAGE, result.output
    assert "unknown filter field" in result.output


def test_records_show_full_id_and_prefix(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    record_id = _record_id(root)

    full = runner.invoke(app, ["-C", str(root), "records", "show", record_id])
    assert full.exit_code == EXIT_OK, full.output
    assert "Learning and spacing effects" in full.output
    assert "DOI: 10.1000/spacing" in full.output

    prefix = runner.invoke(app, ["-C", str(root), "records", "show", record_id[:8]])
    assert prefix.exit_code == EXIT_OK, prefix.output
    assert record_id in prefix.output


def test_records_show_json(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    record_id = _record_id(root)
    result = runner.invoke(app, ["--json", "-C", str(root), "records", "show", record_id])
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    assert payload["id"] == record_id


def test_records_show_unknown_id(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "records", "show", "rec_doesnotexist000"])
    assert result.exit_code == EXIT_USAGE, result.output
    assert "no record id starts with" in result.output


def test_why_shows_import_and_record_add(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    record_id = _record_id(root)
    result = runner.invoke(app, ["-C", str(root), "why", record_id])
    assert result.exit_code == EXIT_OK, result.output
    assert "IMPORT" in result.output
    assert "RECORD-ADD" in result.output


def test_why_json_shape(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    record_id = _record_id(root)
    result = runner.invoke(app, ["--json", "-C", str(root), "why", record_id])
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    kinds = [entry["kind"] for entry in payload]
    assert "import" in kinds
    assert "record-add" in kinds


def test_why_includes_dedup_provenance(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    _import(root, tmp_path, "b.json", _DUPLICATE_OF_RECORD)
    dedup_result = runner.invoke(
        app,
        ["--why", "running dedup before checking why", "-C", str(root), "dedup", "--by", "ethan"],
    )
    assert dedup_result.exit_code == EXIT_OK, dedup_result.output
    assert "1 auto-merged" in dedup_result.output

    records_path = root / "records" / "records.ndjson"
    canonical_id = next(
        json.loads(line)["id"]
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line and '"canonical":true' in line
    )
    result = runner.invoke(app, ["-C", str(root), "why", canonical_id])
    assert result.exit_code == EXIT_OK, result.output
    assert "DEDUP-MERGE" in result.output


def test_why_no_provenance_for_untouched_record(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "why", "rec_0000000000000001"])
    assert result.exit_code == EXIT_USAGE, result.output  # unknown id, not resolvable


def test_fix_corrects_field_and_commits(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    record_id = _record_id(root)

    result = runner.invoke(
        app,
        [
            "--why",
            "correcting a title typo",
            "-C",
            str(root),
            "fix",
            record_id,
            "--field",
            "title",
            "--value",
            "Corrected Title",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "fixed" in result.output
    assert not gitio.is_dirty(root)

    show = runner.invoke(app, ["--json", "-C", str(root), "records", "show", record_id])
    assert json.loads(show.output)["title"] == "Corrected Title"

    message = gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout
    assert "Strata-Op: fix" in message


def test_fix_rejects_structured_field(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    record_id = _record_id(root)
    result = runner.invoke(
        app,
        ["-C", str(root), "fix", record_id, "--field", "author", "--value", "x", "--by", "ethan"],
    )
    assert result.exit_code == EXIT_USAGE, result.output
    assert "cannot be corrected" in result.output


def test_fix_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _RECORD)
    record_id = _record_id(root)
    result = runner.invoke(
        app,
        [
            "--why",
            "fix via json",
            "--json",
            "-C",
            str(root),
            "fix",
            record_id,
            "--field",
            "volume",
            "--value",
            "20",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    assert payload == {"record": record_id, "field": "volume", "old": "19", "new": "20"}
