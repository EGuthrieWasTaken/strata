"""The `strata` command-line interface.

Per docs/spec/12-architecture.md §2, invariant 3: this module contains no
domain logic. Every command is a thin adapter that parses arguments, calls
into `strata.core`/`strata.gitio`, and formats the result — the same service
layer the (future) web UI will call.
"""

from __future__ import annotations

import json as json_mod
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console

from strata import __version__, gitio
from strata.core import actor as actor_mod
from strata.core import doctor as doctor_mod
from strata.core import init as init_mod
from strata.core import logcmd as logcmd_mod
from strata.core import manifest as manifest_mod
from strata.core import status as status_mod
from strata.core import verify as verify_mod
from strata.core.hooks import validate_commit_message_trailers
from strata.core.repo import Repo, RepoNotFoundError, SchemaTooNewError, open_repo

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_NOT_REPO = 3
EXIT_VALIDATION = 4
EXIT_CONFLICT = 5
EXIT_SCHEMA_TOO_NEW = 6
EXIT_RATIONALE_REFUSED = 7
EXIT_GUARDRAIL = 8

app = typer.Typer(
    name="strata",
    no_args_is_help=True,
    add_completion=False,
    help="A version-controlled workbench for systematic reviews and meta-analyses.",
)
actor_app = typer.Typer(name="actor", help="Manage contributors.", no_args_is_help=True)
internal_app = typer.Typer(name="internal", help="Internal hook entry points.", hidden=True)
app.add_typer(actor_app, name="actor")
app.add_typer(internal_app, name="internal")

err_console = Console(stderr=True)
out_console = Console()


@app.callback()
def main(
    ctx: typer.Context,
    directory: str | None = typer.Option(None, "-C", help="Run as if started in <path>"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output on stdout"),
    quiet: bool = typer.Option(False, "-q"),
    verbose: int = typer.Option(0, "-v", count=True),
    no_color: bool = typer.Option(False, "--no-color"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    ctx.obj = {
        "directory": directory,
        "json": json_output,
        "quiet": quiet,
        "verbose": verbose,
        "yes": yes,
    }
    if no_color:
        err_console.no_color = True
        out_console.no_color = True


@app.command()
def version() -> None:
    out_console.print(f"strata {__version__}")


def _resolve_repo(ctx: typer.Context) -> Repo:
    directory = ctx.obj["directory"] if ctx.obj else None
    try:
        return open_repo(Path(directory) if directory else None)
    except RepoNotFoundError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_NOT_REPO) from None
    except SchemaTooNewError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_SCHEMA_TOO_NEW) from None


def _parse_config_value(raw: str) -> bool | int | float | str:
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


@app.command()
def init(
    ctx: typer.Context,
    path: str = typer.Argument(".", help="Directory to create the repository in"),
    title: str | None = typer.Option(None, "--title"),
    remote: str | None = typer.Option(None, "--remote"),
    actor_handle: str | None = typer.Option(None, "--actor", help="Your actor handle"),
    actor_name: str | None = typer.Option(None, "--actor-name"),
    actor_email: str | None = typer.Option(None, "--actor-email"),
) -> None:
    """Create a repository: layout, strata.toml, .gitattributes, hooks, merge drivers, commit."""
    interactive = sys.stdin.isatty()
    if title is None:
        if interactive:
            title = typer.prompt("Review title")
        else:
            err_console.print("[red]error:[/] --title is required in a non-interactive context")
            raise typer.Exit(EXIT_USAGE)
    if actor_handle is None:
        if interactive:
            actor_handle = typer.prompt("Your actor handle (e.g. 'ethan')")
        else:
            err_console.print("[red]error:[/] --actor is required in a non-interactive context")
            raise typer.Exit(EXIT_USAGE)
    if actor_name is None:
        actor_name = typer.prompt("Your name") if interactive else actor_handle

    root = Path(path).resolve()
    try:
        init_mod.init_repository(
            root,
            title=title,
            actor_handle=actor_handle,
            actor_name=actor_name,
            actor_email=actor_email,
            remote=remote,
        )
    except init_mod.InitError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_GENERIC) from None
    out_console.print(f"[green]initialised[/] strata repository at {root}")


@app.command()
def clone(url: str, dest: str | None = typer.Argument(None)) -> None:
    """`git clone` plus merge-driver and hook installation plus `strata verify`."""
    if dest is not None:
        dest_path = Path(dest)
    else:
        name = url.rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[: -len(".git")]
        dest_path = Path(name)

    gitio.clone(url, dest_path)
    repo = open_repo(dest_path)
    doctor_report = doctor_mod.run_doctor(repo, fix=True)
    for finding in doctor_report.findings:
        if finding.fixed:
            out_console.print(f"[yellow]fixed[/] {finding.message}")

    verify_report = verify_mod.verify_repository(repo)
    if verify_report.ok:
        out_console.print("[green]ok[/] — cloned and verified")
        return
    for issue in verify_report.issues:
        err_console.print(f"[red]{issue.code}[/]: {issue.message}")
    raise typer.Exit(EXIT_VALIDATION)


@app.command()
def doctor(ctx: typer.Context, fix: bool = typer.Option(False, "--fix")) -> None:
    """Diagnose and repair: missing merge drivers, missing hooks, git version."""
    repo = _resolve_repo(ctx)
    report = doctor_mod.run_doctor(repo, fix=fix)
    for finding in report.findings:
        if finding.fixed:
            symbol = "[yellow]fixed[/]"
        elif finding.ok:
            symbol = "[green]ok[/]  "
        else:
            symbol = "[red]!!  [/]"
        out_console.print(f"{symbol} {finding.message}")
    raise typer.Exit(EXIT_OK if report.healthy else EXIT_GENERIC)


@app.command()
def config(
    ctx: typer.Context,
    key: str,
    value: str | None = typer.Argument(None),
) -> None:
    """Read or set `strata.toml` values."""
    repo = _resolve_repo(ctx)
    doc = manifest_mod.load_manifest_doc(repo.root)
    if value is None:
        try:
            result = manifest_mod.get_value(doc, key)
        except KeyError:
            err_console.print(f"[red]error:[/] unknown key {key!r}")
            raise typer.Exit(EXIT_USAGE) from None
        out_console.print(result)
        return
    parsed = _parse_config_value(value)
    manifest_mod.set_value(doc, key, parsed)
    manifest_mod.write_manifest(repo.root, doc)
    out_console.print(f"set {key} = {parsed!r}")


@app.command()
def verify(
    ctx: typer.Context,
    fast: bool = typer.Option(False, "--fast"),
    fix: bool = typer.Option(False, "--fix"),
) -> None:
    """Validate the whole repository."""
    repo = _resolve_repo(ctx)
    report = verify_mod.verify_repository(repo, fast=fast)
    del fix  # regeneration-based repair lands with the derived views in M1
    if ctx.obj["json"]:
        out_console.print(
            json_mod.dumps(
                {
                    "ok": report.ok,
                    "issues": [
                        {"code": i.code, "message": i.message, "path": i.path}
                        for i in report.issues
                    ],
                }
            )
        )
    elif report.ok:
        out_console.print("[green]ok[/] — repository is valid")
    else:
        for issue in report.issues:
            loc = f" ({issue.path})" if issue.path else ""
            err_console.print(f"[red]{issue.code}[/]{loc}: {issue.message}")
    raise typer.Exit(EXIT_OK if report.ok else EXIT_VALIDATION)


@app.command()
def status(ctx: typer.Context) -> None:
    """The dashboard: project identity, actors, commits, criteria version."""
    repo = _resolve_repo(ctx)
    s = status_mod.compute_status(repo)
    if ctx.obj["json"]:
        out_console.print(json_mod.dumps(vars(s)))
        return
    out_console.print(f"[bold]{s.title}[/]  criteria v{s.criteria_version}")
    clean = "clean" if s.is_clean else "dirty"
    out_console.print(f"{s.commit_count} commits · {s.actor_count} actors · {clean}")
    out_console.print(f"{s.record_count} records")


@app.command("log")
def log_command(
    ctx: typer.Context,
    criteria: bool = typer.Option(False, "--criteria"),
    stage: str | None = typer.Option(None, "--stage"),
    actor: str | None = typer.Option(None, "--actor"),
) -> None:
    """Domain-level history: reads `Strata-` trailers, not raw commit messages."""
    repo = _resolve_repo(ctx)
    commits = logcmd_mod.domain_log(repo, criteria_only=criteria, stage=stage, actor=actor)
    for c in commits:
        out_console.print(f"{c.sha[:10]}  {c.subject}")


@actor_app.command("add")
def actor_add(
    ctx: typer.Context,
    handle: str,
    name: str,
    email: str | None = typer.Option(None, "--email"),
    role: str = typer.Option("screener", "--role"),
) -> None:
    repo = _resolve_repo(ctx)
    try:
        actor_mod.add_actor(repo, handle=handle, name=name, email=email, role=role)
    except actor_mod.ActorError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    out_console.print(f"[green]added[/] actor {handle}")


@actor_app.command("list")
def actor_list(ctx: typer.Context) -> None:
    repo = _resolve_repo(ctx)
    actors = actor_mod.list_actors(repo)
    if ctx.obj["json"]:
        out_console.print(json_mod.dumps(actors))
        return
    for a in actors:
        out_console.print(f"{a['handle']:<16} {a.get('name', ''):<24} {a.get('role', '')}")


@actor_app.command("deactivate")
def actor_deactivate(ctx: typer.Context, handle: str) -> None:
    repo = _resolve_repo(ctx)
    try:
        actor_mod.deactivate_actor(repo, handle)
    except actor_mod.ActorError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    out_console.print(f"[green]deactivated[/] actor {handle}")


@internal_app.command("hook-pre-commit")
def hook_pre_commit() -> None:
    repo = open_repo()
    report = verify_mod.verify_repository(repo, fast=True)
    if not report.ok:
        for issue in report.issues:
            err_console.print(f"[red]{issue.code}[/]: {issue.message}")
        raise typer.Exit(EXIT_VALIDATION)


@internal_app.command("hook-commit-msg")
def hook_commit_msg(msg_file: str) -> None:
    repo = open_repo()
    structured = repo.config.get("git", {}).get("commit_style", "structured") == "structured"
    message = Path(msg_file).read_text(encoding="utf-8")
    errors = validate_commit_message_trailers(message, structured=structured)
    if errors:
        for e in errors:
            err_console.print(f"[red]error:[/] {e}")
        raise typer.Exit(EXIT_VALIDATION)


@internal_app.command("hook-post-merge")
def hook_post_merge() -> None:
    repo = open_repo()
    report = verify_mod.verify_repository(repo)
    if not report.ok:
        err_console.print("[yellow]warning:[/] verification found issues after merge")
        for issue in report.issues:
            err_console.print(f"  {issue.code}: {issue.message}")


@internal_app.command("hook-post-checkout")
def hook_post_checkout() -> None:
    repo = open_repo()
    cache_dir = repo.path(".strata", "cache")
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    app()
