"""The `strata` command-line interface.

Per docs/spec/12-architecture.md §2, invariant 3: this module contains no
domain logic. Every command is a thin adapter that parses arguments, calls
into `strata.core`/`strata.gitio`, and formats the result — the same service
layer the (future) web UI will call.
"""

from __future__ import annotations

import json as json_mod
import re
import shutil
import sys
from datetime import date
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
from strata.core.commit import RationaleRejectedError, StructuredCommit, validate_rationale
from strata.core.hooks import validate_commit_message_trailers
from strata.core.repo import Repo, RepoNotFoundError, SchemaTooNewError, open_repo
from strata.core.validate import SchemaValidationError
from strata.protocol import searches as searches_mod

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_NOT_REPO = 3
EXIT_VALIDATION = 4
EXIT_CONFLICT = 5
EXIT_SCHEMA_TOO_NEW = 6
EXIT_RATIONALE_REFUSED = 7
EXIT_GUARDRAIL = 8

# A repeatable list-typed typer.Option default must live at module scope,
# not inline in a signature, or ruff's flake8-bugbear B008 flags it.
_EXPORT_FILE_OPTION = typer.Option(None, "--export-file", help="May be repeated")

app = typer.Typer(
    name="strata",
    no_args_is_help=True,
    add_completion=False,
    help="A version-controlled workbench for systematic reviews and meta-analyses.",
)
actor_app = typer.Typer(name="actor", help="Manage contributors.", no_args_is_help=True)
search_app = typer.Typer(
    name="search", help="Record and list executed searches.", no_args_is_help=True
)
internal_app = typer.Typer(name="internal", help="Internal hook entry points.", hidden=True)
app.add_typer(actor_app, name="actor")
app.add_typer(search_app, name="search")
app.add_typer(internal_app, name="internal")

err_console = Console(stderr=True)
out_console = Console()


def _print_json(value: object) -> None:
    """Print a `--json` payload verbatim: no word-wrap, no markup/highlight
    interpretation of its content. `--json` output is a stable, versioned
    contract (docs/spec/10-cli.md §1); Rich's default `print` would otherwise
    wrap long lines and treat a literal `[...]` in the data as a markup tag.
    """
    out_console.print(json_mod.dumps(value), soft_wrap=True, markup=False, highlight=False)


@app.callback()
def main(
    ctx: typer.Context,
    directory: str | None = typer.Option(None, "-C", help="Run as if started in <path>"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output on stdout"),
    quiet: bool = typer.Option(False, "-q"),
    verbose: int = typer.Option(0, "-v", count=True),
    no_color: bool = typer.Option(False, "--no-color"),
    yes: bool = typer.Option(False, "--yes"),
    why: str | None = typer.Option(
        None, "--why", help="Supply the commit rationale non-interactively"
    ),
    why_file: str | None = typer.Option(None, "--why-file", help="Read the rationale from a file"),
    no_commit: bool = typer.Option(
        False, "--no-commit", help="Perform the operation, stage nothing, leave the tree dirty"
    ),
) -> None:
    ctx.obj = {
        "directory": directory,
        "json": json_output,
        "quiet": quiet,
        "verbose": verbose,
        "yes": yes,
        "why": why,
        "why_file": why_file,
        "no_commit": no_commit,
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


def _get_rationale(ctx: typer.Context, repo: Repo, context_lines: str) -> str | None:
    """Elicit a commit rationale per docs/spec/04-git-integration.md §2.3.

    Returns `None` when `git.require_rationale` is false and no rationale was
    supplied. Exits with `EXIT_RATIONALE_REFUSED` when one is required but
    unavailable (non-interactive, no `--why`/`--why-file`) or rejected by
    `validate_rationale` (empty, stop-listed, or too short).
    """
    require = bool(repo.config.get("git", {}).get("require_rationale", True))
    why_file = ctx.obj.get("why_file")
    why = ctx.obj.get("why")

    text: str | None
    if why_file:
        text = Path(why_file).read_text(encoding="utf-8")
    elif why:
        text = why
    elif not require:
        return None
    elif sys.stdin.isatty():
        out_console.print(context_lines)
        text = typer.prompt("Why? (this goes in the permanent record)")
    else:
        err_console.print(
            "[red]error:[/] a rationale is required (git.require_rationale is true); "
            "pass --why or --why-file in a non-interactive context"
        )
        raise typer.Exit(EXIT_RATIONALE_REFUSED)

    try:
        return validate_rationale(text)
    except RationaleRejectedError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_RATIONALE_REFUSED) from None


def _derive_clone_dest_name(url: str) -> str:
    """The directory `strata clone <url>` creates when no `dest` is given.

    `url` may be a URL (always "/"-separated) or a local filesystem path,
    which is "\\"-separated on Windows -- split on either so the derived
    name is correct regardless of which was given or which platform this
    runs on.
    """
    name = re.split(r"[/\\]", url.rstrip("/\\"))[-1]
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return name


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
    dest_path = Path(dest) if dest is not None else Path(_derive_clone_dest_name(url))

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
        _print_json(
            {
                "ok": report.ok,
                "issues": [
                    {"code": i.code, "message": i.message, "path": i.path} for i in report.issues
                ],
            }
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
        _print_json(vars(s))
        return
    out_console.print(f"[bold]{s.title}[/]  criteria v{s.criteria_version}")
    clean = "clean" if s.is_clean else "dirty"
    out_console.print(f"{s.commit_count} commits · {s.actor_count} actors · {clean}")
    out_console.print(f"{s.record_count} records · {s.search_count} searches recorded")
    for search_id in s.pending_searches:
        out_console.print(f"[yellow]![/] {search_id} has no query string recorded  (PRISMA item 7)")


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
        _print_json(actors)
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


@search_app.command("add")
def search_add(
    ctx: typer.Context,
    database: str = typer.Option(..., "--database", help="e.g. MEDLINE, Embase, PsycINFO"),
    platform: str = typer.Option(..., "--platform", help="Interface actually used, e.g. Ovid"),
    executed_by: str = typer.Option(..., "--by", help="Actor handle who ran the search"),
    search_id: str | None = typer.Option(None, "--id", help="Defaults to S-<nn>-<database>"),
    executed: str | None = typer.Option(
        None, "--executed", help="Date run YYYY-MM-DD; default today"
    ),
    query: str | None = typer.Option(None, "--query", help="The verbatim query string"),
    query_file: str | None = typer.Option(None, "--query-file", help="Read the query from a file"),
    hits: int | None = typer.Option(None, "--hits"),
    export_file: list[str] | None = _EXPORT_FILE_OPTION,
    peer_reviewed_by: str | None = typer.Option(None, "--peer-reviewed-by"),
    notes: str | None = typer.Option(None, "--notes"),
    supersedes: str | None = typer.Option(None, "--supersedes", help="Id of an earlier version"),
) -> None:
    """Record an executed search: `protocol/searches/<id>.yaml`."""
    repo = _resolve_repo(ctx)

    if query_file:
        query = Path(query_file).read_text(encoding="utf-8")
    resolved_executed = executed or date.today().isoformat()

    try:
        record = searches_mod.add_search(
            repo,
            database=database,
            platform=platform,
            executed=resolved_executed,
            executed_by=executed_by,
            search_id=search_id,
            query=query,
            hits=hits,
            export_files=list(export_file) if export_file else [],
            peer_reviewed_by=peer_reviewed_by,
            notes=notes,
            supersedes=supersedes,
        )
    except (searches_mod.SearchError, SchemaValidationError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    if record["query"] == searches_mod.PENDING_QUERY:
        out_console.print(
            f"[yellow]warning:[/] no query string recorded for {record['id']} "
            "(PRISMA item 7) — supply it before the review is finalised"
        )

    if ctx.obj["no_commit"]:
        out_console.print(f"[green]recorded[/] search {record['id']} (not committed)")
        return

    rationale = _get_rationale(
        ctx,
        repo,
        f"You recorded search {record['id']} ({record['database']} via {record['platform']}).",
    )
    commit_obj = StructuredCommit(
        op="search-add",
        scope=record["id"],
        summary=f"record search {record['id']}",
        body=rationale,
        trailers={"Op": "search-add", "Search": record["id"], "Actor": executed_by},
    )
    gitio.add(repo.root, ["protocol/searches"])
    gitio.commit(repo.root, commit_obj.message())
    out_console.print(f"[green]recorded[/] search {record['id']}")


@search_app.command("list")
def search_list(ctx: typer.Context) -> None:
    """Show all searches with dates and hit counts."""
    repo = _resolve_repo(ctx)
    records = searches_mod.list_searches(repo)
    if ctx.obj["json"]:
        _print_json(records)
        return
    if not records:
        out_console.print("no searches recorded yet — `strata search add`")
        return
    for s in records:
        is_pending = s["query"] == searches_mod.PENDING_QUERY
        pending = " [yellow]! no query recorded[/]" if is_pending else ""
        hits = s.get("hits")
        hits_str = f"{hits} hits" if hits is not None else "hits unknown"
        out_console.print(f"{s['id']:<20} {s['database']:<14} {s['executed']}  {hits_str}{pending}")


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
