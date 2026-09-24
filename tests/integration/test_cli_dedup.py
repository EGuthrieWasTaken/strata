import json
from pathlib import Path

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, app

runner = CliRunner()


def _init(tmp_path: Path, name: str = "review") -> Path:
    root = tmp_path / name
    result = runner.invoke(
        app,
        [
            "init",
            str(root),
            "--title",
            "Test Review",
            "--actor",
            "ethan",
            "--actor-name",
            "Ethan Test",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def _import(root: Path, tmp_path: Path, name: str, content: str) -> None:
    export = tmp_path / name
    export.write_text(content, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--why",
            f"importing {name} for a dedup test",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--via",
            "registry",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output


# Reordered-title near-duplicates: the title token *set* is identical (so
# Jaccard title_sim = 1.0) but the word order -- and so the first 12
# normalised characters that feed the "title-prefix" identity fallback --
# differs, so the two imports get genuinely different record ids instead of
# colliding into one at import time (an exact title+year+first-author match,
# like a punctuation-only title difference, would otherwise unify them
# before dedup ever saw two records -- a real trap this fixture had to dodge).
# With journal/volume/page also matching, every feature scores 1.0 (score
# 1.0), clearing even a --strict 1.0 threshold.
_AUTO_MERGE_A = (
    '[{"title": "Learning and spacing effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}, "container-title": "Psychological Science", '
    '"volume": "19", "page": "1095"}]'
)
_AUTO_MERGE_B = (
    '[{"title": "Spacing and learning effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}, "container-title": "Psychological Science", '
    '"volume": "19", "page": "1095"}]'
)

# Same reordered-title trick, without journal/volume/page, to land in the
# [0.80, 0.95) review band (score 0.85) instead of clearing auto-merge.
_REVIEW_PAIR_A = (
    '[{"title": "Learning and spacing effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}}]'
)
_REVIEW_PAIR_B = (
    '[{"title": "Spacing and learning effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}}]'
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_dedup_auto_merges_and_commits(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _AUTO_MERGE_A)
    _import(root, tmp_path, "b.json", _AUTO_MERGE_B)

    result = runner.invoke(
        app,
        ["--why", "running dedup after two imports", "-C", str(root), "dedup", "--by", "ethan"],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "1 auto-merged" in result.output
    assert not gitio.is_dirty(root)

    message = gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout
    assert "Strata-Op: dedup" in message
    assert "Strata-Actor: ethan" in message

    records_path = root / "records" / "records.ndjson"
    lines = [line for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    canonical_lines = [line for line in lines if '"canonical":true' in line]
    assert len(canonical_lines) == 1


def test_dedup_second_run_is_sticky_no_op(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _AUTO_MERGE_A)
    _import(root, tmp_path, "b.json", _AUTO_MERGE_B)
    first = runner.invoke(
        app, ["--why", "first dedup run", "-C", str(root), "dedup", "--by", "ethan"]
    )
    assert first.exit_code == EXIT_OK, first.output

    second = runner.invoke(app, ["-C", str(root), "dedup", "--by", "ethan"])
    assert second.exit_code == EXIT_OK, second.output
    assert "0 auto-merged" in second.output
    assert not gitio.is_dirty(root)


def test_dedup_requires_rationale_when_auto_merging(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _AUTO_MERGE_A)
    _import(root, tmp_path, "b.json", _AUTO_MERGE_B)

    result = runner.invoke(app, ["-C", str(root), "dedup", "--by", "ethan"])
    assert result.exit_code == EXIT_RATIONALE_REFUSED, result.output
    assert gitio.is_dirty(root)


def test_dedup_no_commit_flag_leaves_tree_dirty(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _AUTO_MERGE_A)
    _import(root, tmp_path, "b.json", _AUTO_MERGE_B)

    result = runner.invoke(app, ["--no-commit", "-C", str(root), "dedup", "--by", "ethan"])
    assert result.exit_code == EXIT_OK, result.output
    assert gitio.is_dirty(root)


def test_dedup_json_output_shape(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _AUTO_MERGE_A)
    _import(root, tmp_path, "b.json", _AUTO_MERGE_B)

    result = runner.invoke(
        app,
        [
            "--why",
            "checking dedup --json output",
            "--json",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    assert payload["candidate_pairs_considered"] == 1
    assert len(payload["auto_merged"]) == 1
    assert payload["review_queue"] == []


def test_dedup_review_queue_merge_decision(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _REVIEW_PAIR_A)
    _import(root, tmp_path, "b.json", _REVIEW_PAIR_B)

    result = runner.invoke(
        app,
        [
            "--why",
            "reviewing a near-duplicate pair and merging it",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
            "--review",
        ],
        input="m\n",
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "merged" in _lines(result.output)
    assert not gitio.is_dirty(root)

    records_path = root / "records" / "records.ndjson"
    lines = [line for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    canonical_lines = [line for line in lines if '"canonical":true' in line]
    assert len(canonical_lines) == 1


def test_dedup_review_queue_keep_both_decision(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _REVIEW_PAIR_A)
    _import(root, tmp_path, "b.json", _REVIEW_PAIR_B)

    result = runner.invoke(
        app,
        [
            "--why",
            "reviewing a near-duplicate pair and keeping both",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
            "--review",
        ],
        input="k\n",
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "kept both" in _lines(result.output)

    records_path = root / "records" / "records.ndjson"
    lines = [line for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    canonical_lines = [line for line in lines if '"canonical":true' in line]
    assert len(canonical_lines) == 2  # both survive


def test_dedup_review_queue_skip_leaves_pair_pending_next_run(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _REVIEW_PAIR_A)
    _import(root, tmp_path, "b.json", _REVIEW_PAIR_B)

    first = runner.invoke(
        app,
        ["-C", str(root), "dedup", "--by", "ethan", "--review"],
        input="s\n",
    )
    assert first.exit_code == EXIT_OK, first.output
    assert any(line.startswith("skipped") for line in _lines(first.output))

    second_json = runner.invoke(app, ["--json", "-C", str(root), "dedup", "--by", "ethan"])
    payload = json.loads(second_json.output)
    assert len(payload["review_queue"]) == 1  # still pending, not sticky


def test_dedup_review_queue_help_then_merge(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _REVIEW_PAIR_A)
    _import(root, tmp_path, "b.json", _REVIEW_PAIR_B)

    result = runner.invoke(
        app,
        [
            "--why",
            "asking for help before deciding, then merging",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
            "--review",
        ],
        input="?\nm\n",
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "merge now" in " ".join(result.output.split())


def test_dedup_strict_still_auto_merges_exact_duplicate(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _AUTO_MERGE_A)
    _import(root, tmp_path, "b.json", _AUTO_MERGE_B)

    result = runner.invoke(
        app,
        [
            "--why",
            "running a strict dedup pass",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
            "--strict",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "1 auto-merged" in result.output


def test_dedup_strict_routes_near_duplicate_to_review_not_auto_merge(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _REVIEW_PAIR_A)
    _import(root, tmp_path, "b.json", _REVIEW_PAIR_B)

    result = runner.invoke(
        app,
        ["--json", "-C", str(root), "dedup", "--by", "ethan", "--strict"],
    )
    payload = json.loads(result.output)
    assert payload["auto_merged"] == []
    assert len(payload["review_queue"]) == 1


def test_dedup_undo_restores_absorbed_record(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "a.json", _AUTO_MERGE_A)
    _import(root, tmp_path, "b.json", _AUTO_MERGE_B)

    merge_result = runner.invoke(
        app,
        [
            "--why",
            "auto-merge before testing undo",
            "--json",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
        ],
    )
    payload = json.loads(merge_result.output)
    canonical_id, absorbed_id = payload["auto_merged"][0]

    undo_result = runner.invoke(
        app,
        [
            "--why",
            "undoing a merge that turns out to be wrong",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
            "--undo",
            canonical_id,
            absorbed_id,
        ],
    )
    assert undo_result.exit_code == EXIT_OK, undo_result.output
    assert any(line.startswith("restored") for line in _lines(undo_result.output))

    records_path = root / "records" / "records.ndjson"
    lines = [line for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    canonical_lines = [line for line in lines if '"canonical":true' in line]
    assert len(canonical_lines) == 2
