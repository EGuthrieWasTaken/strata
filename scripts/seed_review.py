"""Build the scratch reviews that the browser checks run against.

Two things use this: the Playwright page tests (`tests/browser`) and the hand-run pass with Claude
in Chrome (`docs/chrome-pass.md`). Both need reviews with something in them (screened records, a
conflict, stale decisions, an analysis, a flow diagram), and building those through the browser
each time would be slow and would test the builder, not the screens.

Usage::

    uv run python scripts/seed_review.py OUT_DIR [--force]

writes, under OUT_DIR:

``blank/``
    A review with four criteria and nothing else, in single-reviewer mode (actor ``ada``). For
    walking the write screens from the start: record a search, attach an export, review it,
    import it.
``pipeline/``
    The wiki Quickstart, complete: two searches imported, duplicates merged, both stages screened,
    five reports retrieved and one not, four studies extracted and assessed for risk of bias, a
    pooled analysis, the flow diagram and the draft text. Single-reviewer mode (actor ``ada``).
    Nothing in it is stale.
``dual/``
    Two reviewers (``ada`` the lead, ``sam``). One record they disagree about, two records ``sam``
    has not screened, a criterion added after screening (so decisions are stale), a search with no
    query and a search with no export, and one record whose title and abstract are hostile markup.
``exports/``
    The files to attach: the two wiki example exports, a small new one (``later.ris``), one that
    cannot be imported, one that is not an export at all, and one carrying hostile markup.

Everything is invented data. The reviews are built through the same command line a person uses
(in-process), so they are what `strata` really produces. Building takes about fifteen seconds.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "wiki" / "examples"
MARKER = ".strata-seed"
WHY = "Seeding a scratch review for the browser checks."

# The records of the wiki example. Their ids come from their canonical keys, so they are the
# ones the Quickstart prints.
RATS = "rec_1f2ehvhyywav8zj5"  # Sleep and memory consolidation in rats        (excluded: not human)
JOVANOVIC = (
    "rec_1qjn6pvab3h794qe"  # Retrieval practice ... adult language learners  (report not retrieved)
)
HADDAD = "rec_3bfqqz4nft3qqtqr"  # Spacing and mathematics learning in primary school children
ALDER = (
    "rec_9fz6sp8zep3zep1h"  # Spaced practice and vocabulary retention in secondary school students
)
ERIKSEN = "rec_ayx2jbeg0p7ka6qq"  # Massed vs spaced reading in undergraduates
CASTELLANO = (
    "rec_bja43jkhyfj1qxwv"  # Distributed practice improves recall: a randomised classroom trial
)
EXCLUDED_AT_FULL_TEXT = "rec_yszjwbn5drx1ybr0"
NARRATIVE = "A narrative review of the spacing effect"

HOSTILE_RIS = (
    "TY  - JOUR\n"
    "TI  - Payload test <script>document.title='PWNED'</script> in a title\n"
    "AU  - Mallory, Eve\n"
    "PY  - 2021\n"
    "DO  - 10.0000/example.2021.666\n"
    "AB  - <img src=x onerror=\"document.title='PWNED'\"> and "
    "<script>document.title='PWNED'</script> and </main><h1>closing tags</h1> as an abstract.\n"
    "ER  - \n"
)
LATER_RIS = (
    "TY  - JOUR\n"
    "TI  - Retrieval cues and spaced practice in older adults\n"
    "AU  - Okafor, Ngozi\n"
    "PY  - 2015\n"
    "DO  - 10.0000/example.2015.101\n"
    "AB  - Invented abstract for illustration. Older adults learned names on spaced "
    "or massed schedules.\n"
    "ER  - \n"
    "\n"
    "TY  - JOUR\n"
    "TI  - Interleaving and spacing in undergraduate statistics\n"
    "AU  - Petrov, Dmitri\n"
    "AU  - Quist, Elin\n"
    "PY  - 2021\n"
    "DO  - 10.0000/example.2021.102\n"
    "AB  - Invented abstract for illustration. Students practised problems in blocked "
    "or interleaved order.\n"
    "ER  - \n"
)
# Three records: two have no title and are rejected, one is fine.
BROKEN_RIS = (
    "TY  - JOUR\nAU  - Nobody, N.\nPY  - 2020\nER  - \n\n"
    "TY  - JOUR\nTI  - The one usable record in a bad export\nAU  - Somebody, S.\nPY  - 2021\n"
    "DO  - 10.0000/example.good.1\nER  - \n\n"
    "TY  - JOUR\nER  - \n"
)
NOT_AN_EXPORT = b"%PDF-1.4\n% this is a full text, not a bibliographic export\n"

_runner = CliRunner()


class SeedError(RuntimeError):
    """A step of the build did not do what it should."""


def _run(
    root: Path | None,
    *args: str,
    input: str | None = None,  # noqa: A002
    code: int = EXIT_OK,
) -> str:
    prefix = ["--why", WHY, *(["-C", str(root)] if root else [])]
    result = _runner.invoke(app, [*prefix, *args], input=input)
    if result.exit_code != code:
        raise SeedError(f"strata {' '.join(args)} exited {result.exit_code}:\n{result.output}")
    return result.output


def _json(root: Path, *args: str) -> Any:
    return json.loads(_run(root, "--json", *args))


def _commit(root: Path, actor: str, subject: str) -> None:
    if gitio.is_dirty(root):
        gitio.add_all(root)
        gitio.commit(root, f"{subject}\n\nStrata-Op: config\nStrata-Actor: {actor}")


def _start(root: Path, title: str, actor: str, name: str, *, single: bool) -> None:
    _run(None, "init", str(root), "--title", title, "--actor", actor, "--actor-name", name)
    if single:
        _run(root, "config", "screening.mode", "single")
        _commit(root, actor, "settings: single reviewer")


def _criteria(root: Path, actor: str) -> None:
    both = "title-abstract,full-text"
    rows = [
        (
            "inclusion",
            "Learners in formal education",
            "Participants are school pupils or university students.",
            both,
        ),
        (
            "inclusion",
            "Spacing manipulated",
            "Compares a spaced practice schedule with a massed one.",
            both,
        ),
        (
            "exclusion",
            "Not an empirical study",
            "Narrative reviews, editorials and commentaries without new data.",
            both,
        ),
        ("exclusion", "Not human", "Animal or in-vitro studies.", "title-abstract"),
    ]
    for kind, label, definition, applies in rows:
        _run(
            root,
            "criteria",
            "add",
            "--kind",
            kind,
            "--label",
            label,
            "--definition",
            definition,
            "--applies-at",
            applies,
            "--by",
            actor,
        )


def _record_ids_by_title(root: Path) -> dict[str, str]:
    rows = json.loads(_run(root, "records", "list", "--format", "json"))
    return {row["title"]: row["id"] for row in rows}


def _screen(root: Path, stage: str, actor: str, decisions: dict[str, str]) -> None:
    """One session per record, each limited to that record, answering the prompts in `keys`."""
    for record, keys in decisions.items():
        _run(root, "screen", stage, "--by", actor, "--filter", f"id in ['{record}']", input=keys)


INCLUDE = "i\n\n"


def _exclude(criterion: int, note: str = "") -> str:
    return f"e\n{criterion}\n{note}\n"


def _import_example(root: Path, actor: str) -> None:
    _run(
        root,
        "search",
        "add",
        "--database",
        "MEDLINE",
        "--platform",
        "Ovid",
        "--by",
        actor,
        "--query",
        "1. exp Learning/ 2. (spaced or distributed or massed) adj3 practi*.ti,ab. 3. 1 and 2",
        "--hits",
        "8",
        "--executed",
        "2026-10-01",
    )
    _run(
        root,
        "search",
        "add",
        "--database",
        "Embase",
        "--platform",
        "Ovid",
        "--by",
        actor,
        "--query",
        "spaced or distributed practice",
        "--hits",
        "3",
        "--executed",
        "2026-10-02",
    )
    _run(
        root,
        "import",
        "--by",
        actor,
        "--search",
        "S-01-medline",
        str(EXAMPLES / "spacing-medline.ris"),
    )
    _run(
        root,
        "import",
        "--by",
        actor,
        "--search",
        "S-01-embase",
        str(EXAMPLES / "spacing-embase.ris"),
    )
    _run(root, "dedup", "--by", actor)


def write_exports(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("spacing-medline.ris", "spacing-embase.ris"):
        shutil.copyfile(EXAMPLES / name, directory / name)
    (directory / "later.ris").write_text(LATER_RIS, encoding="utf-8")
    (directory / "hostile.ris").write_text(HOSTILE_RIS, encoding="utf-8")
    (directory / "broken.ris").write_text(BROKEN_RIS, encoding="utf-8")
    (directory / "full-text.pdf").write_bytes(NOT_AN_EXPORT)


def build_blank(out: Path) -> Path:
    root = out / "blank"
    _start(root, "Spacing and retention (blank)", "ada", "Ada Example", single=True)
    _criteria(root, "ada")
    return root


def build_pipeline(out: Path) -> Path:
    root = out / "pipeline"
    _start(root, "Spacing and retention", "ada", "Ada Example", single=True)
    _criteria(root, "ada")
    _import_example(root, "ada")

    titles = _record_ids_by_title(root)
    narrative = next(i for t, i in titles.items() if t.startswith(NARRATIVE))
    for expected in (
        RATS,
        JOVANOVIC,
        HADDAD,
        ALDER,
        ERIKSEN,
        CASTELLANO,
        EXCLUDED_AT_FULL_TEXT,
        narrative,
    ):
        if expected not in titles.values():
            raise SeedError(
                f"the example data no longer holds {expected}; update the ids in {__file__}"
            )
    decisions = {i: INCLUDE for i in titles.values()}
    decisions[RATS] = _exclude(4)
    decisions[narrative] = _exclude(3)
    _screen(root, "title-abstract", "ada", decisions)

    for record in (HADDAD, ALDER, ERIKSEN, CASTELLANO, EXCLUDED_AT_FULL_TEXT):
        _run(
            root,
            "retrieve",
            "--by",
            "ada",
            "--report",
            record.replace("rec_", "rpt_"),
            "--outcome",
            "retrieved",
            "--source",
            "institutional-access",
            "--version",
            "version-of-record",
        )
    _run(
        root,
        "retrieve",
        "--by",
        "ada",
        "--report",
        JOVANOVIC.replace("rec_", "rpt_"),
        "--outcome",
        "not-retrieved",
        "--reason",
        "no-access",
    )
    full_text = {r: INCLUDE for r in (HADDAD, ALDER, ERIKSEN, CASTELLANO)}
    full_text[EXCLUDED_AT_FULL_TEXT] = _exclude(2, "Compares no practice schedules")
    _screen(root, "full-text", "ada", full_text)

    _run(root, "extract", "init")
    effects = {  # study, n_total, (n1, m1, sd1), (n2, m2, sd2) -- the Quickstart's invented numbers
        HADDAD: (120, (60, 14.2, 3.1), (60, 12.5, 3.3)),
        ALDER: (90, (45, 68.0, 14.0), (45, 60.5, 15.2)),
        ERIKSEN: (72, (36, 22.1, 5.0), (36, 19.8, 5.4)),
        CASTELLANO: (103, (52, 55.0, 11.0), (51, 50.2, 12.0)),
    }
    for record, (n_total, (n1, m1, sd1), (n2, m2, sd2)) in effects.items():
        effect = {
            "outcome": "recall",
            "design": "two-group-means",
            "source": "Table 2",
            "n1": n1,
            "m1": m1,
            "sd1": sd1,
            "n2": n2,
            "m2": m2,
            "sd2": sd2,
        }
        study = record.replace("rec_", "std_")
        _run(
            root,
            "extract",
            study,
            "--by",
            "ada",
            "--set",
            f"n_total={n_total} @ Table 1",
            "--effect",
            json.dumps(effect),
        )
    alder_study = ALDER.replace("rec_", "std_")
    _run(
        root,
        "extract",
        alder_study,
        "--by",
        "ada",
        "--ack",
        f"sd-outlier=eff_{alder_study[4:]}_0001",
        "--note",
        "0-100 test; SMD is scale-free",
    )

    _run(root, "rob", "init", "--instrument", "rob2", "--by", "ada")
    for record in effects:
        study = record.replace("rec_", "std_")
        _run(
            root,
            "rob",
            study,
            "--by",
            "ada",
            "--domain",
            "D1",
            "--answer",
            "1.1=Y",
            "--answer",
            "1.2=Y",
            "--answer",
            "1.3=N",
            "--judgement",
            "low",
        )
        for domain in ("D2", "D3", "D4", "D5"):
            _run(root, "rob", study, "--by", "ada", "--domain", domain, "--judgement", "low")
        _run(root, "rob", study, "--by", "ada", "--domain", "overall", "--judgement", "low")

    analysis = root / "analysis"
    analysis.mkdir(exist_ok=True)
    (analysis / "primary.yaml").write_text(
        "id: primary\n"
        "title: Effect of spaced practice on delayed recall\n"
        "preregistered: true\n"
        "effect_size:\n  measure: SMD\n"
        "model:\n  type: random-effects\n  tau2_estimator: REML\n  ci_method: knapp-hartung\n"
        "heterogeneity: [Q, I2, tau2, prediction_interval]\n"
        "sensitivity:\n- id: leave-one-out\n  type: leave_one_out\n"
        "plots: [forest, funnel]\n",
        encoding="utf-8",
    )
    _run(root, "analyze", "primary", "--ack", "k-lt-5")
    _run(root, "prisma")
    _run(root, "report", "checklist")
    _run(root, "report", "methods")
    _run(root, "report", "results")
    _commit(root, "ada", "chore: the example review, complete")
    return root


def build_dual(out: Path) -> Path:
    root = out / "dual"
    _start(root, "Spacing and retention (two reviewers)", "ada", "Ada Example", single=False)
    _run(root, "actor", "add", "sam", "Sam Example")
    _criteria(root, "ada")

    _run(
        root,
        "search",
        "add",
        "--database",
        "MEDLINE",
        "--platform",
        "Ovid",
        "--by",
        "ada",
        "--query",
        "1. exp Learning/ 2. spaced adj3 practi*.ti,ab.",
        "--hits",
        "8",
        "--executed",
        "2026-10-01",
    )
    _run(
        root,
        "search",
        "add",
        "--database",
        "CINAHL",
        "--platform",
        "EBSCO",
        "--by",
        "ada",
        "--hits",
        "0",
        "--executed",
        "2026-10-03",
    )  # no query: recorded as missing it
    _run(
        root,
        "search",
        "add",
        "--database",
        "PsycINFO",
        "--platform",
        "Ovid",
        "--by",
        "ada",
        "--query",
        "spacing effect",
        "--hits",
        "0",
        "--executed",
        "2026-10-04",
    )  # no export yet
    _run(
        root,
        "import",
        "--by",
        "ada",
        "--search",
        "S-01-medline",
        str(EXAMPLES / "spacing-medline.ris"),
    )
    _run(
        root,
        "import",
        "--by",
        "ada",
        "--via",
        "contact",
        str(Path(out) / "exports" / "hostile.ris"),
    )
    _run(root, "dedup", "--by", "ada")

    titles = _record_ids_by_title(root)
    hostile = next(i for t, i in titles.items() if t.startswith("Payload test"))
    ada = {i: INCLUDE for i in titles.values()}
    ada[RATS] = _exclude(4)
    _screen(root, "title-abstract", "ada", ada)
    # Sam disagrees about one record and has not got to two others.
    sam = {i: INCLUDE for i in titles.values() if i not in (hostile, HADDAD)}
    sam[RATS] = _exclude(4)
    sam[ERIKSEN] = _exclude(3)
    _screen(root, "title-abstract", "sam", sam)

    # A criterion added after screening: the decisions it could change are now stale.
    _run(
        root,
        "criteria",
        "add",
        "--kind",
        "exclusion",
        "--label",
        "Not a classroom setting",
        "--definition",
        "Studies run entirely outside an educational setting.",
        "--applies-at",
        "title-abstract",
        "--by",
        "ada",
    )
    return root


@contextmanager
def _without_git_hooks() -> Iterator[None]:
    """Commit without the pre-commit hook for the duration.

    The hook starts a fresh `strata` to verify the repository, which costs a few seconds per
    commit and there are about a hundred of them. Each review is verified in full at the end
    instead.
    """
    empty = tempfile.mkdtemp(prefix="strata-no-hooks-")
    wanted = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": empty,
    }
    saved = {key: os.environ.get(key) for key in wanted}
    os.environ.update(wanted)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(empty, ignore_errors=True)


def seed(out: Path, *, force: bool = False) -> dict[str, Path]:
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).exists():
            raise SeedError(f"{out} exists and was not made by this script; choose another folder")
        if not force:
            raise SeedError(f"{out} already holds seeded reviews; pass --force to rebuild them")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Made by scripts/seed_review.py; safe to delete.\n", encoding="utf-8")
    write_exports(out / "exports")
    with _without_git_hooks():
        built = {
            "blank": build_blank(out),
            "pipeline": build_pipeline(out),
            "dual": build_dual(out),
        }
    for (
        name,
        root,
    ) in built.items():  # what the hook would have checked, once, on the finished review
        _run(root, "verify")
        if gitio.is_dirty(root):
            raise SeedError(f"{name} was left with uncommitted changes")
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build scratch reviews for the browser checks.")
    parser.add_argument(
        "out", type=Path, help="a folder to put them in (made if it does not exist)"
    )
    parser.add_argument(
        "--force", action="store_true", help="rebuild a folder this script made before"
    )
    args = parser.parse_args(argv)
    try:
        built = seed(args.out.resolve(), force=args.force)
    except SeedError as error:
        print(f"seed_review: {error}", file=sys.stderr)
        return 1
    for name, path in built.items():
        print(f"{name:9} {path}")
    print(f"exports   {args.out.resolve() / 'exports'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
