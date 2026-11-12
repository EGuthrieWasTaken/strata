"""Build a scratch hosted instance for a browser to drive.

The page tests (`tests/browser`) and the hand-run pass with Claude in Chrome
(`docs/chrome-pass.md`, Part H) drive `strata serve` over reviews built by `scripts/seed_review.py`.
This builds the same kind of thing for `strata host`: an instance with accounts and members, so
that its own pages (sign-in, the project list, the sync page, the member and invitation screens)
and what only several signed-in people can show (blinding between them, roles, a conflict with the
shared remote) can be looked at in a real browser.

Usage::

    uv run python scripts/seed_hosted.py OUT_DIR [--public-url URL] [--idle-minutes N] [--force]

writes, under OUT_DIR:

``data/``
    The instance's data directory, for ``strata host --data OUT_DIR/data``.
``remotes/spacing.git``, ``remotes/disputed.git``
    The bare repositories that stand in for the shared remotes.

and, in the instance, two projects cloned from them:

``spacing``
    The two-reviewer review of `seed_review.py` (``dual``): one record ``ada`` and ``sam``
    disagree about, two records ``sam`` has not screened, stale decisions.
``disputed``
    The same review, where the lead reworded ``EXC-01`` on the instance while a collaborator
    pushed a different wording to the remote. The first sync finds the conflict and holds it for a
    lead to resolve; nothing is pushed until then.

and three accounts, all with the password ``PASSWORD`` below: ``ada`` (lead), ``sam`` (screener)
and ``olive`` (observer: may read, may not write), each a member of both projects.

To look at it::

    uv run strata host --data OUT_DIR/data --public-url http://127.0.0.1:8765 \\
        --port 8765 --insecure-local-testing

Everything is invented data, and the instance accepts plain HTTP only because it is told to: never
serve it to anyone else.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from strata import gitio
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.hosted.instance import Instance

try:  # imported as `scripts.seed_hosted` (the tests), or run as a file
    from scripts import seed_review
except ImportError:  # pragma: no cover - `python scripts/seed_hosted.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import seed_review

MARKER = ".strata-hosted-seed"
PASSWORD = "correct horse battery staple"  # noqa: S105 - a scratch instance's, printed below
PUBLIC_URL = "http://127.0.0.1:8765"
#: username -> (display name, actor in the review, role in the project)
USERS = {
    "ada": ("Ada Example", "ada", "lead"),
    "sam": ("Sam Example", "sam", "screener"),
    "olive": ("Olive Observer", "olive", "observer"),
}
INSTANCE_WORDING = "Commentaries, editorials and reviews: not a report of a study."
REMOTE_WORDING = "Not a primary study (a commentary, an editorial or a narrative review)."


class SeedError(RuntimeError):
    pass


def _bare_from(review: Path, bare: Path) -> Path:
    bare.parent.mkdir(parents=True, exist_ok=True)
    gitio.run(["init", "--bare", "--initial-branch=main", str(bare)], cwd=bare.parent)
    gitio.run(["push", str(bare), "HEAD:main"], cwd=review)
    return bare


def _review(work: Path) -> Path:
    """`seed_review`'s two-reviewer review, with an observer among its actors."""
    seed_review.write_exports(work / "exports")  # the review imports from them
    root = seed_review.build_dual(work)
    seed_review._run(root, "actor", "add", "olive", "Olive Observer", "--role", "observer")
    seed_review._commit(root, "ada", "settings: add an observer")
    return root


def _diverge(instance: Instance, bare: Path, work: Path) -> None:
    """Reword EXC-01 one way on the instance and another way on the remote."""
    project = instance.project_dir("disputed")
    seed_review._run(
        project, "criteria", "edit", "EXC-01", "--direction", "both",
        "--definition", INSTANCE_WORDING, "--by", "ada",
    )  # fmt: skip
    laptop = work / "laptop"
    gitio.clone(str(bare), laptop)
    gitio.run(["checkout", "-B", "main", "origin/main"], cwd=laptop)
    seed_review._run(laptop, "doctor", "--fix")
    seed_review._run(
        laptop, "criteria", "edit", "EXC-01", "--direction", "both",
        "--definition", REMOTE_WORDING, "--by", "sam",
    )  # fmt: skip
    gitio.run(["push", "origin", "HEAD:main"], cwd=laptop)


def seed(
    out: Path,
    *,
    public_url: str = PUBLIC_URL,
    idle_minutes: int | None = None,
    force: bool = False,
) -> dict[str, Path]:
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).exists():
            raise SeedError(f"{out} exists and was not made by this script; choose another folder")
        if not force:
            raise SeedError(f"{out} already holds a seeded instance; pass --force to rebuild it")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Made by scripts/seed_hosted.py; safe to delete.\n", encoding="utf-8")

    instance = Instance(out / "data", environ={})
    instance.initialise(public_url=public_url)
    if idle_minutes is not None:
        with instance.settings_path.open("a", encoding="utf-8") as settings:
            settings.write(f"\n[sessions]\nidle_minutes = {idle_minutes}\n")
        instance = Instance(out / "data", environ={})

    with tempfile.TemporaryDirectory(prefix="strata-hosted-seed-") as tmp:
        work = Path(tmp)
        with seed_review._without_git_hooks():
            review = _review(work)
            remotes = {
                name: _bare_from(review, out / "remotes" / f"{name}.git")
                for name in ("spacing", "disputed")
            }
            for name, bare in remotes.items():
                instance.add_project(name, remote=str(bare))
            _diverge(instance, remotes["disputed"], work)

    for username, (display, actor, role) in USERS.items():
        accounts.add_user(instance.store, username, display_name=display, password=PASSWORD)
        for project in remotes:
            members_mod.add_member(instance, project, username, actor=actor, role=role)
    return {"data": out / "data", **{f"remote:{name}": bare for name, bare in remotes.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a scratch hosted instance.")
    parser.add_argument("out", type=Path, help="a folder to put it in (made if it does not exist)")
    parser.add_argument(
        "--public-url", default=PUBLIC_URL, help=f"the address it will be served at ({PUBLIC_URL})"
    )
    parser.add_argument(
        "--idle-minutes", type=int, default=None, help="sign people out after this long idle"
    )
    parser.add_argument(
        "--force", action="store_true", help="rebuild a folder this script made before"
    )
    args = parser.parse_args(argv)
    try:
        built = seed(
            args.out.resolve(),
            public_url=args.public_url,
            idle_minutes=args.idle_minutes,
            force=args.force,
        )
    except (SeedError, seed_review.SeedError) as error:
        print(f"seed_hosted: {error}", file=sys.stderr)
        return 1
    for name, path in built.items():
        print(f"{name:16} {path}")
    print(f"accounts         {', '.join(USERS)} (password: {PASSWORD})")
    print(
        f"serve it         strata host --data {built['data']} --public-url {args.public_url} "
        "--port <its port> --insecure-local-testing"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
