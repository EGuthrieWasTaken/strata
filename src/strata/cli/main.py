"""The `strata` command-line interface.

Per docs/spec/12-architecture.md §2, invariant 3: this module contains no
domain logic. Every command is a thin adapter that parses arguments, calls
into `strata.core`/`strata.gitio`, and formats the result — the same service
layer the (future) web UI will call.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json as json_mod
import re
import shutil
import sys
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from strata import __version__, gitio
from strata.core import actor as actor_mod
from strata.core import doctor as doctor_mod
from strata.core import filters as filters_mod
from strata.core import init as init_mod
from strata.core import logcmd as logcmd_mod
from strata.core import manifest as manifest_mod
from strata.core import provenance as provenance_mod
from strata.core import records as records_mod
from strata.core import status as status_mod
from strata.core import verify as verify_mod
from strata.core.commit import RationaleRejectedError, StructuredCommit, validate_rationale
from strata.core.hooks import validate_commit_message_trailers
from strata.core.repo import Repo, RepoNotFoundError, SchemaTooNewError, open_repo
from strata.core.validate import SchemaValidationError
from strata.dedup import engine as engine_mod
from strata.ingest import pipeline as pipeline_mod
from strata.mcpserver import server as mcp_server_mod
from strata.protocol import adjudication as adjudication_mod
from strata.protocol import audit as audit_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import irr as irr_mod
from strata.protocol import pool as pool_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.protocol import searches as searches_mod
from strata.web import security as web_security
from strata.web import server as web_server_mod

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_NOT_REPO = 3
EXIT_VALIDATION = 4
EXIT_CONFLICT = 5
EXIT_SCHEMA_TOO_NEW = 6
EXIT_RATIONALE_REFUSED = 7
EXIT_GUARDRAIL = 8

# A repeatable list-typed typer.Option/Argument default must live at module
# scope, not inline in a signature, or ruff's flake8-bugbear B008 flags it.
_EXPORT_FILE_OPTION = typer.Option(None, "--export-file", help="May be repeated")
_IMPORT_FILES_ARGUMENT = typer.Argument(..., help="One or more export files to import")
_MARK_OPTION = typer.Option(
    None, "--mark", help="Force record(s) stale (manual reason) instead of re-screening"
)

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
records_app = typer.Typer(
    name="records", help="List and inspect bibliographic records.", no_args_is_help=True
)
criteria_app = typer.Typer(
    name="criteria", help="Manage inclusion/exclusion criteria.", no_args_is_help=True
)
internal_app = typer.Typer(name="internal", help="Internal hook entry points.", hidden=True)
app.add_typer(actor_app, name="actor")
app.add_typer(search_app, name="search")
app.add_typer(records_app, name="records")
app.add_typer(criteria_app, name="criteria")
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


def _prompt_and_validate_rationale(ctx: typer.Context, context_lines: str) -> str:
    """Elicit and validate a rationale, unconditionally (shared by `_get_rationale`
    and `_get_required_rationale` — see those for when each applies)."""
    why_file = ctx.obj.get("why_file")
    why = ctx.obj.get("why")

    text: str | None
    if why_file:
        text = Path(why_file).read_text(encoding="utf-8")
    elif why:
        text = why
    elif sys.stdin.isatty():
        out_console.print(context_lines)
        text = typer.prompt("Why? (this goes in the permanent record)")
    else:
        err_console.print(
            "[red]error:[/] a rationale is required; "
            "pass --why or --why-file in a non-interactive context"
        )
        raise typer.Exit(EXIT_RATIONALE_REFUSED)

    try:
        return validate_rationale(text)
    except RationaleRejectedError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_RATIONALE_REFUSED) from None


def _get_rationale(ctx: typer.Context, repo: Repo, context_lines: str) -> str | None:
    """Elicit a commit rationale per docs/spec/04-git-integration.md §2.3.

    Returns `None` when `git.require_rationale` is false and no rationale was
    supplied. Exits with `EXIT_RATIONALE_REFUSED` when one is required but
    unavailable (non-interactive, no `--why`/`--why-file`) or rejected by
    `validate_rationale` (empty, stop-listed, or too short).
    """
    require = bool(repo.config.get("git", {}).get("require_rationale", True))
    if not require and not ctx.obj.get("why_file") and not ctx.obj.get("why"):
        return None
    return _prompt_and_validate_rationale(ctx, context_lines)


def _get_required_rationale(ctx: typer.Context, repo: Repo, context_lines: str) -> str:
    """Like `_get_rationale`, but the rationale is required unconditionally,
    regardless of `git.require_rationale` — for operations the specification
    itself requires a rationale for with no config escape hatch: criteria
    changes (docs/spec/06-workflow-screening.md §3.2's "Why did you make this
    change?" prompt) and adjudications (§8: "A rationale is REQUIRED for
    adjudications").
    """
    del repo  # kept for signature symmetry with `_get_rationale`; not consulted
    return _prompt_and_validate_rationale(ctx, context_lines)


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


def _parse_map_option(raw: str) -> dict[str, str]:
    """`--map title=Article Title,doi=DOI` -> `{"title": "Article Title", "doi": "DOI"}`.

    docs/spec/05-workflow-import.md §2.2's own example uses exactly this
    comma-separated `field=Column Name` syntax; a column name containing a
    literal comma isn't expressible this way, a known limitation.
    """
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            raise typer.BadParameter(f"--map entry {pair!r} is not of the form field=Column")
        field_name, column = pair.split("=", 1)
        mapping[field_name.strip()] = column.strip()
    return mapping


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
        _print_json(dataclasses.asdict(s))
        return
    out_console.print(f"[bold]{s.title}[/]  criteria v{s.criteria_version}")
    clean = "clean" if s.is_clean else "dirty"
    out_console.print(f"{s.commit_count} commits · {s.actor_count} actors · {clean}")
    out_console.print(f"{s.record_count} records · {s.search_count} searches recorded")
    for search_id in s.pending_searches:
        out_console.print(f"[yellow]![/] {search_id} has no query string recorded  (PRISMA item 7)")
    for stage in s.stages:
        out_console.print(
            f"\n[bold]{stage.stage.upper()}[/]  {stage.total} records"
            f"    {stage.resolved} resolved · {stage.unscreened} unscreened · "
            f"{stage.partial} partial"
        )
        if stage.conflicts:
            out_console.print(f"  {stage.conflicts} conflicts                strata adjudicate")
        if stage.stale:
            out_console.print(f"  {stage.stale} STALE                    strata rescreen")
    if s.next_action:
        out_console.print(f"\n[bold]NEXT[/]  {s.next_action}")


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


def _commit_manifest_op(
    ctx: typer.Context, repo: Repo, *, op: str, scope: str, summary: str, trailers: dict[str, str]
) -> None:
    """Commit a `strata.toml`-only change (docs/spec/04-git-integration.md
    §2.1: every mutating command produces exactly one commit)."""
    if ctx.obj["no_commit"]:
        out_console.print(f"[green]{summary}[/] (not committed)")
        return
    rationale = _get_rationale(ctx, repo, f"You {summary}.")
    commit_obj = StructuredCommit(
        op=op, scope=scope, summary=summary, body=rationale, trailers=trailers
    )
    gitio.add(repo.root, ["strata.toml"])
    gitio.commit(repo.root, commit_obj.message())


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
    _commit_manifest_op(
        ctx,
        repo,
        op="actor-add",
        scope=handle,
        summary=f"add actor {handle}",
        trailers={"Op": "actor-add", "Actor": handle, "Role": role},
    )
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
    _commit_manifest_op(
        ctx,
        repo,
        op="actor-deactivate",
        scope=handle,
        summary=f"deactivate actor {handle}",
        trailers={"Op": "actor-deactivate", "Actor": handle},
    )
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


@app.command("import")
def import_command(
    ctx: typer.Context,
    files: list[str] = _IMPORT_FILES_ARGUMENT,
    by: str = typer.Option(..., "--by", help="Actor handle who ran the import"),
    search_id: str | None = typer.Option(
        None, "--search", help="Id of the search that produced this export"
    ),
    via: str | None = typer.Option(
        None, "--via", help="citation-searching | website | organisation | registry | contact"
    ),
    fmt: str | None = typer.Option(None, "--format", help="Override automatic format detection"),
    map_option: str | None = typer.Option(
        None,
        "--map",
        help="CSV/TSV column mapping, e.g. title=Article Title,author=Authors,doi=DOI",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Parse and report without writing anything"
    ),
) -> None:
    """Import one or more bibliographic exports: copy raw, parse, assign ids, commit.

    Each file is its own import (docs/spec/02-repository-format.md §2:
    `imports/<id>/`) and, unless `--dry-run`/`--no-commit`, its own commit —
    a failure partway through a multi-file import leaves every earlier file's
    import already committed rather than the tree half-written and dirty.
    """
    repo = _resolve_repo(ctx)
    exit_code = EXIT_OK
    results = []
    mapping = _parse_map_option(map_option) if map_option else None

    for file in files:
        try:
            outcome = pipeline_mod.import_file(
                repo,
                file,
                imported_by=by,
                search_id=search_id,
                via=via,
                fmt=fmt,
                mapping=mapping,
                dry_run=dry_run,
            )
        except pipeline_mod.ImportPipelineError as exc:
            exit_code = EXIT_USAGE
            if ctx.obj["json"]:
                results.append({"file": file, "error": str(exc)})
            else:
                err_console.print(f"[red]error:[/] {file}: {exc}")
            continue

        if ctx.obj["json"]:
            results.append({"file": file, **dataclasses.asdict(outcome)})

        if outcome.already_imported:
            if not ctx.obj["json"]:
                out_console.print(
                    f"[yellow]already imported[/] {file} as {outcome.import_id} — no changes made"
                )
            continue

        if not ctx.obj["json"]:
            verb = "would import" if dry_run else "imported"
            out_console.print(
                f"[green]{verb}[/] {file} as {outcome.import_id}: "
                f"{outcome.records_created} new, {outcome.existing_ids_appended} matched "
                f"existing, {outcome.rows_rejected} rejected"
            )
            for row in outcome.nondeterministic_rows:  # pragma: no cover - see pipeline.py
                out_console.print(
                    f"[yellow]warning:[/] row {row} had no stable identifier (assigned a random id)"
                )

        if dry_run or ctx.obj["no_commit"]:
            continue

        rationale = _get_rationale(ctx, repo, f"You imported {file} as {outcome.import_id}.")
        commit_obj = StructuredCommit(
            op="import",
            scope=outcome.import_id,
            summary=f"import {Path(file).name}",
            body=rationale,
            trailers={"Op": "import", "Import": outcome.import_id, "Actor": by},
        )
        gitio.add(repo.root, ["imports", "records", "events"])
        gitio.commit(repo.root, commit_obj.message())

    if ctx.obj["json"]:
        _print_json(results)
    raise typer.Exit(exit_code)


def _author_display(record: dict[str, Any]) -> str:
    names = []
    for author in record.get("author") or []:
        if isinstance(author, dict):
            names.append(author.get("family") or author.get("literal") or "")
        else:
            names.append(str(author))
    return ", ".join(n for n in names if n)


def _source_label(record: dict[str, Any]) -> str:
    sources = record.get("strata", {}).get("sources") or []
    if not sources:
        return "manual"
    return str(sources[-1].get("database") or sources[-1].get("platform") or "manual")


def _render_review_pair(
    index: int,
    total: int,
    candidate: engine_mod.ReviewCandidate,
    record_a: dict[str, Any],
    record_b: dict[str, Any],
) -> str:
    header = f"Pair {index} of {total}"
    lines = [f"{header:<50} score {candidate.result.score:.2f}"]
    if candidate.doi_conflict:
        lines.append("DOIs differ -- flagged for human judgement (doi-conflict)")
    lines.append("")
    for label, record in (("A", record_a), ("B", record_b)):
        year = ((record.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        authors = _author_display(record)
        if authors and year:
            byline = f"{authors} ({year})"
        else:
            byline = authors or (str(year) if year else "")
        lines.append(f"  {label}  {record['id']}     [{_source_label(record)}]")
        if byline:
            lines.append(f"     {byline}")
        lines.append(f"     {record.get('title', '')}")
    f = candidate.result.features
    lines.append(
        f"     title {f['title']:.2f} | authors {f['author']:.2f} | year {f['year']:.2f} "
        f"| journal {f['journal']:.2f} | locator {f['locator']:.2f}"
    )
    lines.append("")
    lines.append("  [m] merge   [k] keep both   [s] skip   [?] help")
    return "\n".join(lines)


def _commit_domain_op(
    ctx: typer.Context,
    repo: Repo,
    *,
    op: str,
    scope: str | None,
    summary: str,
    by: str,
    extra_trailers: dict[str, str] | None = None,
) -> None:
    if ctx.obj["no_commit"]:
        return
    rationale = _get_rationale(ctx, repo, f"You {summary}.")
    trailers = {"Op": op, "Actor": by, **(extra_trailers or {})}
    commit_obj = StructuredCommit(
        op=op, scope=scope, summary=summary, body=rationale, trailers=trailers
    )
    gitio.add(repo.root, ["records", "events", "derived"])
    gitio.commit(repo.root, commit_obj.message())


_UNDO_OPTION = typer.Option(("", ""), "--undo", help="CANONICAL_ID ABSORBED_ID: reverse one merge")


@app.command("dedup")
def dedup_command(
    ctx: typer.Context,
    by: str = typer.Option(..., "--by", help="Actor handle running dedup"),
    review: bool = typer.Option(False, "--review", help="Interactively work the review queue"),
    strict: bool = typer.Option(False, "--strict", help="Force both thresholds to 1.0"),
    undo: tuple[str, str] = _UNDO_OPTION,
) -> None:
    """Find and auto-merge obvious duplicates; `--review` walks the rest interactively."""
    repo = _resolve_repo(ctx)

    if undo != ("", ""):
        canonical_id, absorbed_id = undo
        engine_mod.undo_merge(repo, canonical_id=canonical_id, absorbed_id=absorbed_id, actor=by)
        _commit_domain_op(
            ctx,
            repo,
            op="dedup-unmerge",
            scope=canonical_id,
            summary="undid a merge",
            by=by,
            extra_trailers={"Restored": absorbed_id},
        )
        out_console.print(f"[green]restored[/] {absorbed_id}")
        return

    outcome = engine_mod.run_dedup(repo, actor=by, strict=strict)

    if ctx.obj["json"]:
        _print_json(
            {
                "candidate_pairs_considered": outcome.candidate_pairs_considered,
                "auto_merged": outcome.auto_merged,
                "review_queue": [
                    {
                        "a": c.record_a,
                        "b": c.record_b,
                        "score": c.result.score,
                        "doi_conflict": c.doi_conflict,
                    }
                    for c in outcome.review_queue
                ],
                "blocking_warnings": outcome.blocking_warnings,
            }
        )
    else:
        out_console.print(
            f"{outcome.candidate_pairs_considered} candidate pair(s); "
            f"{len(outcome.auto_merged)} auto-merged; {len(outcome.review_queue)} pending review"
        )
        for w in outcome.blocking_warnings:
            out_console.print(f"[yellow]warning:[/] {w}")

    if outcome.auto_merged:
        _commit_domain_op(
            ctx,
            repo,
            op="dedup",
            scope=None,
            summary=f"auto-merged {len(outcome.auto_merged)} duplicate pair(s)",
            by=by,
        )

    if not review or not outcome.review_queue:
        return

    records = records_mod.index_by_id(records_mod.read_records(repo))
    total = len(outcome.review_queue)
    for index, candidate in enumerate(outcome.review_queue, start=1):
        record_a, record_b = records[candidate.record_a], records[candidate.record_b]
        while True:
            out_console.print(_render_review_pair(index, total, candidate, record_a, record_b))
            choice = typer.prompt("Decision", default="s").strip().lower()
            if choice in ("?", "help"):
                out_console.print(
                    "m = merge now; k = keep both (never asked again); "
                    "s = skip (asked again next run)"
                )
                continue
            if choice == "m":
                engine_mod.apply_review_decision(
                    repo,
                    record_a_id=candidate.record_a,
                    record_b_id=candidate.record_b,
                    result=candidate.result,
                    decision="merge",
                    actor=by,
                )
                _commit_domain_op(
                    ctx,
                    repo,
                    op="dedup",
                    scope=candidate.record_a,
                    summary="merged a duplicate after review",
                    by=by,
                    extra_trailers={"Absorbed": candidate.record_b},
                )
                out_console.print("[green]merged[/]")
            elif choice == "k":
                engine_mod.apply_review_decision(
                    repo,
                    record_a_id=candidate.record_a,
                    record_b_id=candidate.record_b,
                    result=candidate.result,
                    decision="distinct",
                    actor=by,
                )
                _commit_domain_op(
                    ctx,
                    repo,
                    op="dedup-distinct",
                    scope=candidate.record_a,
                    summary="kept a pair distinct after review",
                    by=by,
                    extra_trailers={"Other": candidate.record_b},
                )
                out_console.print("[yellow]kept both[/]")
            else:
                out_console.print("[dim]skipped -- will be asked again next time[/]")
            break


def _resolve_record_id(repo: Repo, record_id: str) -> str:
    """`<id>` may be any unambiguous prefix (docs/spec/10-cli.md §1); exits
    with a clear error, not a traceback, for zero or multiple matches."""
    try:
        return records_mod.resolve_id_prefix(repo, record_id)
    except (records_mod.RecordNotFoundError, records_mod.AmbiguousRecordIdError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None


def _record_year(record: dict[str, Any]) -> int | None:
    parts = ((record.get("issued") or {}).get("date-parts")) or [[None]]
    return parts[0][0] if parts else None


def _csl_view(record: dict[str, Any]) -> dict[str, Any]:
    """The record without strata's internal `strata` bookkeeping block --
    what a citation tool wants from `--format csl`."""
    return {k: v for k, v in record.items() if k != "strata"}


def _apply_record_filter(records: list[dict[str, Any]], filter_expr: str) -> list[dict[str, Any]]:
    """Shared `--filter` evaluation (docs/spec/10-cli.md §3), used by `records list`,
    `screen`, and `assign`. Exits with `EXIT_USAGE` on a bad expression or a field
    that can't be evaluated, rather than raising past the CLI boundary."""
    try:
        ast = filters_mod.parse(filter_expr)
    except filters_mod.FilterSyntaxError as exc:
        err_console.print(f"[red]error:[/] invalid --filter: {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    matched = []
    for record in records:
        try:
            if filters_mod.evaluate(ast, records_mod.record_field_resolver(record)):
                matched.append(record)
        except filters_mod.FilterEvaluationError as exc:
            err_console.print(f"[red]error:[/] --filter failed on record {record['id']}: {exc}")
            raise typer.Exit(EXIT_USAGE) from None
    return matched


@records_app.command("list")
def records_list(
    ctx: typer.Context,
    filter_expr: str | None = typer.Option(
        None, "--filter", help="Filter expression, docs/spec/10-cli.md §3"
    ),
    fmt: str = typer.Option("tsv", "--format", help="tsv | json | csl"),
    all_records: bool = typer.Option(
        False, "--all", help="Include absorbed duplicates (excluded by default)"
    ),
) -> None:
    """List records; `--filter` narrows them, `--format` controls the output shape."""
    if fmt not in ("tsv", "json", "csl"):
        err_console.print(f"[red]error:[/] --format must be tsv, json, or csl, got {fmt!r}")
        raise typer.Exit(EXIT_USAGE)

    repo = _resolve_repo(ctx)
    records = records_mod.read_records(repo)
    if not all_records:
        records = [r for r in records if r.get("strata", {}).get("canonical", True)]

    if filter_expr:
        records = _apply_record_filter(records, filter_expr)

    if fmt == "json":
        _print_json(records)
    elif fmt == "csl":
        _print_json([_csl_view(r) for r in records])
    else:
        # Rich's Console expands literal tabs to aligned spaces even with
        # soft_wrap=True (verified: it's tab-stop rendering, not wrapping) --
        # exactly wrong for a format whose entire point is real tab bytes a
        # script can split on. Bypass it and write directly to stdout.
        print("id\tyear\tauthors\ttitle")
        for record in records:
            year = _record_year(record)
            title = record.get("title", "")
            print(f"{record['id']}\t{year or ''}\t{_author_display(record)}\t{title}")


@records_app.command("show")
def records_show(ctx: typer.Context, record_id: str) -> None:
    """Full record: metadata, sources, and dedup/provenance flags."""
    repo = _resolve_repo(ctx)
    resolved_id = _resolve_record_id(repo, record_id)
    record = records_mod.get_record(repo, resolved_id)
    assert record is not None  # resolve_id_prefix only returns ids that exist

    if ctx.obj["json"]:
        _print_json(record)
        return

    strata_block = record.get("strata", {})
    year = _record_year(record)
    byline = _author_display(record)
    out_console.print(f"[bold]{resolved_id}[/]  [{_source_label(record)}]")
    if byline or year:
        out_console.print(f"{byline} ({year})" if byline and year else byline or str(year))
    out_console.print(record.get("title") or "")
    locator = record.get("container-title") or ""
    if record.get("volume"):
        locator += f", {record['volume']}"
    if record.get("issue"):
        locator += f"({record['issue']})"
    if record.get("page"):
        locator += f", {record['page']}"
    if locator:
        out_console.print(locator)
    if record.get("DOI"):
        out_console.print(f"DOI: {record['DOI']}")
    if record.get("abstract"):
        out_console.print(f"\n{record['abstract']}")
    out_console.print(f"\ncanonical: {strata_block.get('canonical', True)}")
    if strata_block.get("absorbed"):
        out_console.print(f"absorbed: {', '.join(strata_block['absorbed'])}")
    out_console.print("sources:")
    for source in strata_block.get("sources", []):
        out_console.print(f"  {source}")


@app.command("why")
def why_command(ctx: typer.Context, record_id: str) -> None:
    """Full provenance for a record: search, import, amendments, and dedup history."""
    repo = _resolve_repo(ctx)
    resolved_id = _resolve_record_id(repo, record_id)
    entries = provenance_mod.build_provenance(repo, resolved_id)

    if ctx.obj["json"]:
        _print_json(
            [{"kind": e.kind, "ts": e.ts, "actor": e.actor, "detail": e.detail} for e in entries]
        )
        return

    if not entries:
        out_console.print(f"[yellow]no recorded provenance for {resolved_id}[/]")
        return

    out_console.print(f"[bold]{resolved_id}[/]")
    for entry in entries:
        ts = f" {entry.ts}" if entry.ts else ""
        actor = f" by {entry.actor}" if entry.actor else ""
        out_console.print(f"\n[bold]{entry.kind.upper()}[/]{ts}{actor}")
        for key, value in entry.detail.items():
            out_console.print(f"  {key}: {value}")


@app.command("fix")
def fix_command(
    ctx: typer.Context,
    record_id: str,
    field: str = typer.Option(..., "--field", help="One of records_mod.EDITABLE_STRING_FIELDS"),
    value: str = typer.Option(..., "--value", help="The corrected value"),
    by: str = typer.Option(..., "--by", help="Actor handle making the correction"),
) -> None:
    """Correct a metadata field, recording the change as a `record-amend` event."""
    repo = _resolve_repo(ctx)
    resolved_id = _resolve_record_id(repo, record_id)

    try:
        old, new = records_mod.amend_field(
            repo, record_id=resolved_id, field=field, value=value, actor=by
        )
    except records_mod.FixFieldError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    if ctx.obj["json"]:
        _print_json({"record": resolved_id, "field": field, "old": old, "new": new})
    else:
        out_console.print(f"[green]fixed[/] {resolved_id}.{field}: {old!r} -> {new!r}")

    _commit_domain_op(ctx, repo, op="fix", scope=resolved_id, summary=f"corrected {field}", by=by)


def _split_stages(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def _commit_criteria_op(
    ctx: typer.Context,
    repo: Repo,
    *,
    op: str,
    criterion_id: str,
    summary: str,
    by: str,
    rationale: str,
) -> None:
    # Regenerated regardless of --no-commit: a criteria change can make
    # decisions stale even when the caller doesn't want a commit yet.
    pool_mod.regenerate_all(repo)
    if ctx.obj["no_commit"]:
        return
    commit_obj = StructuredCommit(
        op=op,
        scope=criterion_id,
        summary=summary,
        body=rationale,
        trailers={"Op": op, "Criterion": criterion_id, "Actor": by},
    )
    gitio.add(repo.root, ["protocol/criteria.yaml", "events/criteria", "derived"])
    gitio.commit(repo.root, commit_obj.message())


@criteria_app.command("add")
def criteria_add(
    ctx: typer.Context,
    kind: str = typer.Option(..., "--kind", help="inclusion | exclusion"),
    label: str = typer.Option(..., "--label"),
    definition: str = typer.Option(..., "--definition"),
    applies_at: str = typer.Option(..., "--applies-at", help="Comma-separated stages"),
    by: str = typer.Option(..., "--by", help="Actor handle making the change"),
    criterion_id: str | None = typer.Option(None, "--id"),
) -> None:
    """Add a criterion. A criterion added behaves as `tightened` (docs/spec/06 §3.2)."""
    repo = _resolve_repo(ctx)
    rationale = _get_required_rationale(
        ctx, repo, f"You are adding a new {kind} criterion: {label!r}."
    )
    try:
        criterion = criteria_mod.add_criterion(
            repo,
            kind=kind,  # type: ignore[arg-type]
            label=label,
            definition=definition,
            applies_at=_split_stages(applies_at),
            actor=by,
            rationale=rationale,
            criterion_id=criterion_id,
        )
    except (criteria_mod.CriteriaError, SchemaValidationError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    version = criteria_mod.read_criteria_doc(repo)["version"]
    if ctx.obj["json"]:
        _print_json(criterion)
    else:
        out_console.print(f"[green]added[/] {criterion['id']} (criteria v{version})")

    _commit_criteria_op(
        ctx,
        repo,
        op="criteria-add",
        criterion_id=criterion["id"],
        summary=f"add criterion {criterion['id']}",
        by=by,
        rationale=rationale,
    )


@criteria_app.command("edit")
def criteria_edit(
    ctx: typer.Context,
    criterion_id: str,
    direction: str = typer.Option(
        ..., "--direction", help="tightened | loosened | both | editorial"
    ),
    by: str = typer.Option(..., "--by", help="Actor handle making the change"),
    definition: str | None = typer.Option(None, "--definition"),
    label: str | None = typer.Option(None, "--label"),
    applies_at: str | None = typer.Option(None, "--applies-at", help="Comma-separated stages"),
) -> None:
    """Edit a criterion; MUST classify the change's direction (docs/spec/06 §3.2)."""
    repo = _resolve_repo(ctx)
    rationale = _get_required_rationale(ctx, repo, f"You are editing {criterion_id} ({direction}).")
    try:
        updated = criteria_mod.edit_criterion(
            repo,
            criterion_id,
            direction=direction,  # type: ignore[arg-type]
            actor=by,
            rationale=rationale,
            label=label,
            definition=definition,
            applies_at=_split_stages(applies_at) if applies_at is not None else None,
        )
    except (criteria_mod.CriteriaError, SchemaValidationError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    version = criteria_mod.read_criteria_doc(repo)["version"]
    if ctx.obj["json"]:
        _print_json(updated)
    else:
        out_console.print(f"[green]edited[/] {criterion_id} (criteria v{version}, {direction})")

    _commit_criteria_op(
        ctx,
        repo,
        op="criteria-edit",
        criterion_id=criterion_id,
        summary=f"edit criterion {criterion_id} ({direction})",
        by=by,
        rationale=rationale,
    )


@criteria_app.command("retire")
def criteria_retire(
    ctx: typer.Context, criterion_id: str, by: str = typer.Option(..., "--by")
) -> None:
    """Retire a criterion; behaves as `loosened` (docs/spec/06 §3.2)."""
    repo = _resolve_repo(ctx)
    rationale = _get_required_rationale(ctx, repo, f"You are retiring {criterion_id}.")
    try:
        criteria_mod.retire_criterion(repo, criterion_id, actor=by, rationale=rationale)
    except criteria_mod.CriteriaError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    version = criteria_mod.read_criteria_doc(repo)["version"]
    if ctx.obj["json"]:
        _print_json({"id": criterion_id, "status": "retired"})
    else:
        out_console.print(f"[yellow]retired[/] {criterion_id} (criteria v{version})")

    _commit_criteria_op(
        ctx,
        repo,
        op="criteria-retire",
        criterion_id=criterion_id,
        summary=f"retire criterion {criterion_id}",
        by=by,
        rationale=rationale,
    )


@criteria_app.command("list")
def criteria_list_cmd(
    ctx: typer.Context,
    at: str | None = typer.Option(None, "--at", help="Filter to criteria applying at this stage"),
    version: int | None = typer.Option(
        None, "--version", help="Reconstruct the set as of version N"
    ),
) -> None:
    repo = _resolve_repo(ctx)
    criteria = criteria_mod.list_criteria(repo, at=at, version=version)
    if ctx.obj["json"]:
        _print_json(criteria)
        return
    if not criteria:
        out_console.print("no criteria recorded yet -- `strata criteria add`")
        return
    for c in criteria:
        status = "" if c["status"] == "active" else " [dim](retired)[/]"
        out_console.print(f"{c['id']:<8} {c['kind']:<10} {c['label']}{status}")


@criteria_app.command("diff")
def criteria_diff_cmd(ctx: typer.Context, v1: int, v2: int) -> None:
    """Show what changed between two criteria versions."""
    repo = _resolve_repo(ctx)
    try:
        deltas = criteria_mod.diff_versions(repo, v1, v2)
    except criteria_mod.CriteriaError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    if ctx.obj["json"]:
        _print_json(deltas)
        return
    if not deltas:
        out_console.print(f"no criteria changes between v{v1} and v{v2}")
        return
    for d in deltas:
        out_console.print(f"{d['id']:<8} {d['origin']:<8} {d['direction']:<10} {d['label']}")


def _resolve_filter_ids(repo: Repo, filter_expr: str) -> set[str]:
    """Canonical record ids matching `--filter`, per docs/spec/10-cli.md §3."""
    records = [
        r for r in records_mod.read_records(repo) if r.get("strata", {}).get("canonical", True)
    ]
    return {r["id"] for r in _apply_record_filter(records, filter_expr)}


_DECISION_KEYS = {"i": "include", "e": "exclude", "m": "maybe"}


def _parse_criteria_numbers(raw: str, active_criteria: list[dict[str, Any]]) -> list[str]:
    """`1,3` -> the ids of the 1st and 3rd listed criteria (docs/spec/06 §7's
    "digits 1-9 cite criteria"). Out-of-range numbers are reported and skipped
    rather than aborting the whole citation."""
    ids: list[str] = []
    for token in raw.replace(",", " ").split():
        try:
            n = int(token)
        except ValueError:
            out_console.print(f"[yellow]warning:[/] ignoring non-numeric criterion {token!r}")
            continue
        if not (1 <= n <= len(active_criteria)):
            out_console.print(f"[yellow]warning:[/] no criterion numbered {n}")
            continue
        ids.append(active_criteria[n - 1]["id"])
    return ids


def _render_screen_record(
    index: int,
    total: int,
    stage: str,
    record: dict[str, Any],
    active_criteria: list[dict[str, Any]],
) -> str:
    year = _record_year(record)
    authors = _author_display(record)
    lines = [f"{stage}  record {index + 1} of {total}", ""]
    lines.append(record.get("title") or "(no title)")
    byline = " · ".join(
        p for p in (authors, record.get("container-title"), str(year) if year else "") if p
    )
    if byline:
        lines.append(byline)
    lines.append("")
    lines.append(record.get("abstract") or "[yellow](no abstract)[/]")
    if active_criteria:
        lines.append("")
        lines.append("Criteria:")
        for i, c in enumerate(active_criteria, start=1):
            lines.append(f"  {i}  {c['id']}  {c['label']}")
    return "\n".join(lines)


@app.command("screen")
def screen_command(
    ctx: typer.Context,
    stage: str,
    by: str = typer.Option(..., "--by", help="Actor handle doing the screening"),
    filter_expr: str | None = typer.Option(None, "--filter", help="Narrow the queue"),
    limit: int | None = typer.Option(None, "--limit", help="Screen at most N records"),
    decisions_file: str | None = typer.Option(
        None, "--decisions", help="TSV of record_id/decision/criteria/note (docs/spec/10 §5)"
    ),
) -> None:
    """Open the screening queue for `stage`, or bulk-import decisions with `--decisions`."""
    repo = _resolve_repo(ctx)

    if decisions_file:
        text = Path(decisions_file).read_text(encoding="utf-8")
        try:
            envelopes = screening_mod.import_decisions_tsv(repo, stage=stage, text=text, actor=by)
        except screening_mod.ScreeningError as exc:
            err_console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(EXIT_USAGE) from None
        if ctx.obj["json"]:
            _print_json({"stage": stage, "recorded": len(envelopes)})
        else:
            out_console.print(f"[green]recorded[/] {len(envelopes)} decision(s) for {stage}")
        if envelopes:
            pool_mod.regenerate_all(repo)
            _commit_domain_op(
                ctx,
                repo,
                op="screen-import",
                scope=stage,
                summary=f"imported {len(envelopes)} {stage} decisions",
                by=by,
            )
        return

    only_ids = _resolve_filter_ids(repo, filter_expr) if filter_expr else None
    try:
        queue = screening_mod.stage_queue(repo, stage, by, only_ids=only_ids)
    except screening_mod.ScreeningError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    if limit is not None:
        queue = queue[:limit]

    if not queue:
        out_console.print(f"[green]nothing to screen[/] at {stage} for {by}")
        return

    records = records_mod.index_by_id(records_mod.read_records(repo))
    active_criteria = [
        c for c in criteria_mod.list_criteria(repo, at=stage) if c["status"] == "active"
    ]

    decided = 0
    last_decided_index: int | None = None
    index = 0
    while index < len(queue):
        record_id = queue[index]
        out_console.print(
            _render_screen_record(index, len(queue), stage, records[record_id], active_criteria)
        )
        choice = typer.prompt("[i]nclude [e]xclude [m]aybe [s]kip [u]ndo [q]uit", default="s")
        choice = choice.strip().lower()
        if choice == "q":
            break
        if choice == "s":
            index += 1
            continue
        if choice == "u":
            if last_decided_index is None:
                out_console.print("[yellow]nothing to undo yet[/]")
                continue
            index = last_decided_index
            last_decided_index = None
            continue
        if choice not in _DECISION_KEYS:
            out_console.print(f"[yellow]unrecognised choice {choice!r}[/]")
            continue

        decision = _DECISION_KEYS[choice]
        cited: list[str] = []
        if choice == "e" and active_criteria:
            raw = typer.prompt("Cite criteria (comma-separated numbers)", default="")
            cited = _parse_criteria_numbers(raw, active_criteria)
        note = typer.prompt("Note (optional)", default="") or None

        try:
            screening_mod.record_screen_decision(
                repo,
                stage=stage,
                record_id=record_id,
                decision=decision,  # type: ignore[arg-type]
                actor=by,
                cited=cited,
                note=note,
            )
        except screening_mod.ScreeningError as exc:
            out_console.print(f"[red]error:[/] {exc}")
            continue

        decided += 1
        last_decided_index = index
        index += 1

    if decided:
        pool_mod.regenerate_all(repo)
        _commit_domain_op(
            ctx,
            repo,
            op="screen",
            scope=stage,
            summary=f"screened {decided} {stage} record(s)",
            by=by,
        )
    if ctx.obj["json"]:
        _print_json({"stage": stage, "decided": decided})
    else:
        out_console.print(f"[green]done[/] -- {decided} decision(s) recorded")


@app.command("assign")
def assign_command(
    ctx: typer.Context,
    stage: str,
    actors: str = typer.Option(..., "--actors", help="Comma-separated actor handles"),
    by: str = typer.Option(..., "--by", help="Actor handle recording the assignment"),
    filter_expr: str | None = typer.Option(None, "--filter", help="Assign only matching records"),
) -> None:
    """Assign reviewers to records at `stage` (all canonical records by default)."""
    repo = _resolve_repo(ctx)
    actor_list = [a.strip() for a in actors.split(",") if a.strip()]
    if filter_expr:
        record_ids = _resolve_filter_ids(repo, filter_expr)
    else:
        record_ids = {
            r["id"]
            for r in records_mod.read_records(repo)
            if r.get("strata", {}).get("canonical", True)
        }

    try:
        screening_mod.assign_reviewers(
            repo,
            stage=stage,
            actors=actor_list,
            record_ids=sorted(record_ids),
            actor=by,
            filter_expr=filter_expr,
        )
    except screening_mod.ScreeningError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    out_console.print(
        f"[green]assigned[/] {len(record_ids)} record(s) at {stage} to {', '.join(actor_list)}"
    )
    _commit_domain_op(
        ctx,
        repo,
        op="assign",
        scope=stage,
        summary=f"assigned {len(record_ids)} {stage} record(s)",
        by=by,
        extra_trailers={"Actors": ",".join(actor_list)},
    )


def _render_rescreen_record(
    index: int,
    total: int,
    stage: str,
    record: dict[str, Any],
    stale: rescreen_mod.StaleRecord,
    active_criteria: list[dict[str, Any]],
) -> str:
    lines = [f"{stage}  STALE {index + 1} of {total}  ({stale.reason})", ""]
    lines.append(record.get("title") or "(no title)")
    lines.append("")
    prior_criteria = ", ".join(stale.prior_criteria) or "(none cited)"
    lines.append(f"Your previous decision: {stale.prior_decision.upper()}  citing {prior_criteria}")
    lines.append(f"Now stale because: {stale.reason}")
    if active_criteria:
        lines.append("")
        lines.append("Criteria:")
        for i, c in enumerate(active_criteria, start=1):
            lines.append(f"  {i}  {c['id']}  {c['label']}")
    return "\n".join(lines)


@app.command("rescreen")
def rescreen_command(
    ctx: typer.Context,
    stage: str | None = typer.Option(None, "--stage", help="Restrict to one stage"),
    by: str = typer.Option(..., "--by", help="Actor handle doing the re-screening"),
    mark: list[str] | None = _MARK_OPTION,
) -> None:
    """Open the stale queue: docs/spec/06-workflow-screening.md §6."""
    repo = _resolve_repo(ctx)
    stages = [stage] if stage else screening_mod.configured_stages(repo)

    if mark:
        rationale = _get_required_rationale(
            ctx, repo, f"You are manually marking {len(mark)} record(s) stale."
        )
        for record_id in mark:
            for s in stages:
                rescreen_mod.mark_manual_stale(
                    repo, stage=s, record_id=record_id, actor=by, rationale=rationale
                )
        pool_mod.regenerate_all(repo)
        out_console.print(f"[yellow]marked[/] {len(mark)} record(s) stale")
        _commit_domain_op(
            ctx,
            repo,
            op="rescreen-mark",
            scope=stage,
            summary=f"manually marked {len(mark)} record(s) stale",
            by=by,
        )
        return

    queue: list[tuple[str, rescreen_mod.StaleRecord]] = []
    for s in stages:
        try:
            queue.extend((s, item) for item in rescreen_mod.rescreen_queue(repo, s, by))
        except rescreen_mod.RescreenError as exc:
            err_console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(EXIT_USAGE) from None

    if not queue:
        out_console.print(f"[green]nothing to rescreen[/] for {by}")
        return

    records = records_mod.index_by_id(records_mod.read_records(repo))
    decided = 0
    index = 0
    while index < len(queue):
        s, stale = queue[index]
        record = records.get(stale.record_id)
        if record is None:
            index += 1
            continue
        active_criteria = [
            c for c in criteria_mod.list_criteria(repo, at=s) if c["status"] == "active"
        ]
        out_console.print(
            _render_rescreen_record(index, len(queue), s, record, stale, active_criteria)
        )
        choice = typer.prompt(
            "[i]nclude [e]xclude [m]aybe [k]eep previous [s]kip [q]uit", default="s"
        )
        choice = choice.strip().lower()
        if choice == "q":
            break
        if choice == "s":
            index += 1
            continue

        if choice == "k":
            decision: str = stale.prior_decision
            cited = list(stale.prior_criteria)
        elif choice in _DECISION_KEYS:
            decision = _DECISION_KEYS[choice]
            cited = []
            if choice == "e" and active_criteria:
                raw = typer.prompt("Cite criteria (comma-separated numbers)", default="")
                cited = _parse_criteria_numbers(raw, active_criteria)
        else:
            out_console.print(f"[yellow]unrecognised choice {choice!r}[/]")
            continue

        try:
            screening_mod.record_screen_decision(
                repo,
                stage=s,
                record_id=stale.record_id,
                decision=decision,  # type: ignore[arg-type]
                actor=by,
                cited=cited,
            )
        except screening_mod.ScreeningError as exc:
            out_console.print(f"[red]error:[/] {exc}")
            continue

        decided += 1
        index += 1

    if decided:
        pool_mod.regenerate_all(repo)
        _commit_domain_op(
            ctx,
            repo,
            op="rescreen",
            scope=stage,
            summary=f"re-screened {decided} stale record(s)",
            by=by,
        )
    if ctx.obj["json"]:
        _print_json({"decided": decided})
    else:
        out_console.print(f"[green]done[/] -- {decided} decision(s) recorded")


def _render_conflict(
    index: int, total: int, stage: str, record: dict[str, Any], opinions: dict[str, Any]
) -> str:
    lines = [f"Conflict {index + 1} of {total}                {stage}", ""]
    lines.append(record.get("title") or "(no title)")
    lines.append("")
    for actor, event in sorted(opinions.items()):
        body = event["body"]
        date = event.get("ts", "")[:10]
        detail = body["decision"].upper()
        lines.append(f"{actor:<10} {detail:<10} {date}")
        if body.get("criteria"):
            lines.append(f"           citing {', '.join(body['criteria'])}")
        if body.get("note"):
            lines.append(f'           "{body["note"]}"')
    lines.append("")
    lines.append("[i] include   [e] exclude   [d] discuss   [s] skip   [q] quit")
    return "\n".join(lines)


@app.command("adjudicate")
def adjudicate_command(
    ctx: typer.Context,
    stage: str | None = typer.Option(None, "--stage", help="Restrict to one stage"),
    by: str = typer.Option(..., "--by", help="Actor handle adjudicating"),
) -> None:
    """Resolve screening conflicts: docs/spec/06-workflow-screening.md §8."""
    repo = _resolve_repo(ctx)
    if not adjudication_mod.is_adjudicator(repo, by):
        err_console.print(
            f"[red]error:[/] {by!r} is not an adjudicator for this review "
            "(screening.adjudicators or role 'adjudicator'/'lead')"
        )
        raise typer.Exit(EXIT_GUARDRAIL)
    stages = [stage] if stage else screening_mod.configured_stages(repo)

    queue: list[tuple[str, str]] = []
    for s in stages:
        try:
            queue.extend((s, record_id) for record_id in adjudication_mod.conflict_queue(repo, s))
        except adjudication_mod.AdjudicationError as exc:
            err_console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(EXIT_USAGE) from None

    if not queue:
        out_console.print("[green]no conflicts[/] to adjudicate")
        return

    records = records_mod.index_by_id(records_mod.read_records(repo))
    decided = 0
    index = 0
    while index < len(queue):
        s, record_id = queue[index]
        record = records.get(record_id)
        if record is None:
            index += 1
            continue
        state = screening_mod.resolve_record_state(repo, s, record_id)
        active_criteria = [
            c for c in criteria_mod.list_criteria(repo, at=s) if c["status"] == "active"
        ]
        out_console.print(_render_conflict(index, len(queue), s, record, state.opinions))
        choice = typer.prompt("Decision", default="s").strip().lower()

        if choice == "q":
            break
        if choice == "s":
            index += 1
            continue
        if choice == "d":
            text = typer.prompt("Note")
            adjudication_mod.record_discussion(
                repo, stage=s, record_id=record_id, actor=by, text=text
            )
            index += 1
            continue
        if choice not in ("i", "e"):
            out_console.print(f"[yellow]unrecognised choice {choice!r}[/]")
            continue

        decision = "include" if choice == "i" else "exclude"
        cited: list[str] = []
        if choice == "e" and active_criteria:
            raw = typer.prompt("Cite criteria (comma-separated numbers)", default="")
            cited = _parse_criteria_numbers(raw, active_criteria)
        rationale = _get_required_rationale(
            ctx, repo, f"You are adjudicating {record_id} at {s} as {decision}."
        )
        try:
            adjudication_mod.record_adjudication(
                repo,
                stage=s,
                record_id=record_id,
                decision=decision,  # type: ignore[arg-type]
                actor=by,
                rationale=rationale,
                cited=cited,
            )
        except adjudication_mod.AdjudicationError as exc:
            out_console.print(f"[red]error:[/] {exc}")
            continue

        decided += 1
        index += 1

    if decided:
        pool_mod.regenerate_all(repo)
        _commit_domain_op(
            ctx,
            repo,
            op="adjudicate",
            scope=stage,
            summary=f"adjudicated {decided} conflict(s)",
            by=by,
        )
    if ctx.obj["json"]:
        _print_json({"decided": decided})
    else:
        out_console.print(f"[green]done[/] -- {decided} conflict(s) resolved")


@app.command("audit")
def audit_command(
    ctx: typer.Context,
    criteria: bool = typer.Option(
        False, "--criteria", help="Sample past exclusions for criterion-citation review"
    ),
    sample: int = typer.Option(20, "--sample", help="Sample size"),
    seed: int | None = typer.Option(None, "--seed", help="Reproduce a specific sample"),
) -> None:
    """Re-present a random sample of past exclusions for verification (docs/spec/06 §4.3)."""
    if not criteria:
        err_console.print("[red]error:[/] strata audit currently only supports --criteria")
        raise typer.Exit(EXIT_USAGE)

    repo = _resolve_repo(ctx)
    sampled, used_seed = audit_mod.sample_exclusions(repo, sample_size=sample, seed=seed)

    if ctx.obj["json"]:
        _print_json(
            {
                "seed": used_seed,
                "items": [
                    {
                        "record": item.record_id,
                        "stage": item.stage,
                        "actor": item.actor,
                        "criteria": list(item.criteria),
                        "note": item.note,
                    }
                    for item in sampled
                ],
            }
        )
        return

    if not sampled:
        out_console.print("no exclusion decisions recorded yet to audit")
        return

    records = records_mod.index_by_id(records_mod.read_records(repo))
    out_console.print(
        f"Sampling {len(sampled)} exclusion(s) (seed {used_seed}; "
        f"rerun with --seed {used_seed} to reproduce)"
    )
    for item in sampled:
        record = records.get(item.record_id)
        title = record.get("title") if record else "(unknown record)"
        criteria_list = ", ".join(item.criteria) or "(none)"
        out_console.print(
            f"\n{item.record_id}  {item.stage}  excluded by {item.actor} citing {criteria_list}"
        )
        out_console.print(f"  {title}")
        if item.note:
            out_console.print(f'  note: "{item.note}"')


@app.command("irr")
def irr_command(
    ctx: typer.Context,
    stage: str | None = typer.Option(None, "--stage", help="Restrict to one stage"),
) -> None:
    """Inter-rater reliability, over independent first opinions (docs/spec/02 §6.5).

    Read-only with respect to the event log: recomputes and rewrites
    `derived/irr.json` on disk, but does not commit -- the next mutating
    screening command's commit (or a manual commit) picks the file up, same
    as any other derived view.
    """
    repo = _resolve_repo(ctx)
    stages = [stage] if stage else screening_mod.configured_stages(repo)

    all_pairs: list[irr_mod.PairIrr] = []
    for s in stages:
        try:
            all_pairs.extend(irr_mod.compute_stage_irr(repo, s))
        except irr_mod.IrrError as exc:
            err_console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(EXIT_USAGE) from None
    irr_mod.regenerate_irr_json(repo)

    if ctx.obj["json"]:
        _print_json(
            [
                {
                    "stage": p.stage,
                    "actor_a": p.actor_a,
                    "actor_b": p.actor_b,
                    "n": p.n,
                    "excluded_maybe": p.excluded_maybe,
                    "table": p.table,
                    "raw_agreement": p.raw_agreement,
                    "kappa": p.kappa,
                    "pabak": p.pabak,
                }
                for p in all_pairs
            ]
        )
        return

    if not all_pairs:
        out_console.print("no reviewer pairs with overlapping first opinions yet")
        return
    for p in all_pairs:
        out_console.print(
            f"{p.stage:<16} {p.actor_a} x {p.actor_b}   n={p.n}   "
            f"agreement={p.raw_agreement:.2f}   kappa={p.kappa:.2f}   pabak={p.pabak:.2f}"
        )


@app.command("serve")
def serve_command(
    ctx: typer.Context,
    port: int = typer.Option(0, "--port", help="Port to bind (0 = OS-assigned ephemeral port)"),
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Bind address; a non-loopback host requires --token"
    ),
    token: str | None = typer.Option(
        None, "--token", help="Fixed session token (required with a non-loopback --host)"
    ),
    actor: str | None = typer.Option(
        None, "--actor", help="Screen as this actor; required if more than one is configured"
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Do not automatically open a browser"
    ),
    inactivity_timeout: float = typer.Option(
        web_security.DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
        "--inactivity-timeout",
        help="Seconds of inactivity before the server exits (docs/spec/11 §7)",
    ),
) -> None:
    """Start the local web UI (docs/spec/11-web-ui.md)."""
    repo = _resolve_repo(ctx)

    try:
        resolved_actor = web_server_mod.resolve_actor(repo, actor)
        session_token = web_server_mod.resolve_token(host, token)
    except web_server_mod.ServeConfigError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    if not web_server_mod.is_loopback_host(host):
        err_console.print(
            f"[yellow]warning:[/] binding to {host!r} exposes this server beyond this machine "
            "-- only do this on a network you trust"
        )

    resolved_port = port or web_server_mod.pick_ephemeral_port(host)
    params = web_server_mod.ServeParams(
        repo_root=repo.root,
        actor=resolved_actor,
        host=host,
        port=resolved_port,
        session_token=session_token,
        inactivity_timeout=inactivity_timeout,
    )
    url = web_server_mod.opened_url(params)
    out_console.print(f"[green]strata serve[/] listening on {url}  (actor: {resolved_actor})")
    if not no_browser:
        webbrowser.open(url)

    asyncio.run(web_server_mod.serve_until_idle_or_interrupted(params))


@app.command("mcp")
def mcp_command(ctx: typer.Context) -> None:
    """Run the local, read-only MCP server over stdio (docs/spec/15-roadmap.md, M2.1).

    Exposes status/why/log/records/criteria-diff/impact-preview as MCP tools --
    nothing that writes. Spawned by an MCP-aware client (Claude Code, Claude
    Desktop, or any other) against this repository, the same way the client
    would spawn any other local stdio server, e.g. `strata -C <path> mcp`."""
    repo = _resolve_repo(ctx)
    mcp_server_mod.create_mcp_server(repo_root=repo.root).run(transport="stdio")


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
