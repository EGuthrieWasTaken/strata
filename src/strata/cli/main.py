"""The `strata` command-line interface.

Per openspec:architecture#presentation-layers-contain-no-domain-logic: this module contains no
domain logic. Every command is a thin adapter that parses arguments, calls
into `strata.core`/`strata.gitio`, and formats the result — the same service
layer the (future) web UI will call.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json as json_mod
import re
import shutil
import sys
import webbrowser
from collections.abc import Callable, Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from strata import __version__, gitio
from strata.analysis import engine as analysis_engine
from strata.analysis import guardrails as analysis_guardrails
from strata.analysis import plots as analysis_plots
from strata.analysis import rows as analysis_rows
from strata.analysis import run as analysis_run
from strata.analysis import spec as analysis_mod_spec
from strata.ci import amendment as ci_amendment_mod
from strata.ci import comment as ci_comment_mod
from strata.ci import workflows as ci_workflows
from strata.core import actor as actor_mod
from strata.core import diffcmd as diffcmd_mod
from strata.core import doctor as doctor_mod
from strata.core import fieldedit as fieldedit_mod
from strata.core import ids as ids_mod
from strata.core import init as init_mod
from strata.core import logcmd as logcmd_mod
from strata.core import manifest as manifest_mod
from strata.core import merge as merge_mod
from strata.core import operations as ops_mod
from strata.core import provenance as provenance_mod
from strata.core import records as records_mod
from strata.core import status as status_mod
from strata.core import sync as sync_mod
from strata.core import verify as verify_mod
from strata.core.commit import RationaleRejectedError, StructuredCommit, validate_rationale
from strata.core.hooks import validate_commit_message_trailers
from strata.core.repo import (
    LockTimeoutError,
    Repo,
    RepoNotFoundError,
    SchemaTooNewError,
    open_repo,
    repo_lock,
)
from strata.core.validate import SchemaValidationError
from strata.dedup import engine as engine_mod
from strata.extract import export as export_mod
from strata.extract import reconcile as reconcile_mod
from strata.extract import records as extraction_records_mod
from strata.extract import rob as rob_mod
from strata.extract import schema as extraction_schema_mod
from strata.ingest import pipeline as pipeline_mod
from strata.ingest.enrich import unpaywall as unpaywall_mod
from strata.integrations.reference_manager import ReferenceManagerError
from strata.integrations.zotero import connect as zotero_connect
from strata.integrations.zotero import operations as zotero_ops
from strata.integrations.zotero import retrieval as zotero_retrieval
from strata.mcpserver import server as mcp_server_mod
from strata.protocol import adjudication as adjudication_mod
from strata.protocol import audit as audit_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import irr as irr_mod
from strata.protocol import pool as pool_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod
from strata.protocol import searches as searches_mod
from strata.protocol import studies as studies_mod
from strata.report import bibliography as bibliography_mod
from strata.report import checklist as checklist_mod
from strata.report import counts as counts_mod
from strata.report import facts as facts_mod
from strata.report import flow as flow_mod
from strata.report import package as package_mod
from strata.report import sections as sections_mod
from strata.stats import models as models_mod
from strata.stats import robust as robust_mod
from strata.web import security as web_security
from strata.web import server as web_server_mod
from strata.web import uploads as web_uploads

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
_LOCATOR_OPTION = typer.Option(None, "--locator", help="kind=value (doi, pmid, ...); repeatable")
_GROUP_OPTION = typer.Option(None, "--group", help="Report id to group; repeat per report")
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
export_app = typer.Typer(
    name="export", help="Export data for analysis elsewhere.", no_args_is_help=True
)
ci_app = typer.Typer(
    name="ci",
    help="Helpers the review-repository CI workflow uses.",
    no_args_is_help=True,
)
zotero_app = typer.Typer(
    name="zotero",
    help="Optional: link a review to Zotero (it holds the documents, strata holds the decisions).",
    no_args_is_help=True,
)
internal_app = typer.Typer(name="internal", help="Internal hook entry points.", hidden=True)
app.add_typer(actor_app, name="actor")
app.add_typer(search_app, name="search")
app.add_typer(records_app, name="records")
app.add_typer(criteria_app, name="criteria")
app.add_typer(export_app, name="export")
app.add_typer(ci_app, name="ci")
app.add_typer(zotero_app, name="zotero")
app.add_typer(internal_app, name="internal")

err_console = Console(stderr=True)
out_console = Console()


def _print_json(value: object) -> None:
    """Print a `--json` payload verbatim: no word-wrap, no markup/highlight
    interpretation of its content. `--json` output is a stable, versioned
    contract (openspec:cli); Rich's default `print` would otherwise
    wrap long lines and treat a literal `[...]` in the data as a markup tag.
    """
    out_console.print(json_mod.dumps(value), soft_wrap=True, markup=False, highlight=False)


def _print_version_and_exit(value: bool) -> None:
    if value:
        out_console.print(f"strata {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    show_version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version_and_exit,
        is_eager=True,
        help="Show the version and exit",
    ),
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


def _warn_lock_reclaimed(previous_holder: int | None) -> None:
    """Say so when this run took a lock its last holder died holding (it stopped mid-write)."""
    if previous_holder is not None:
        err_console.print(
            f"[yellow]warning:[/] the repository lock was left by process {previous_holder}, which "
            "is no longer running; it may have stopped part-way through a write. This run carried "
            "on; `strata verify` checks that nothing was left half-done."
        )


def _lock_busy(exc: LockTimeoutError) -> NoReturn:
    err_console.print(f"[red]error:[/] {exc}")
    raise typer.Exit(EXIT_GENERIC)


def _read_supplied_rationale(ctx: typer.Context) -> str | None:
    """The unvalidated text given with `--why-file` (first) or `--why`, else `None`."""
    why_file = ctx.obj.get("why_file")
    if why_file:
        try:
            return Path(why_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            err_console.print(f"[red]error:[/] cannot read --why-file {why_file}: {exc}")
            raise typer.Exit(EXIT_RATIONALE_REFUSED) from None
    return ctx.obj.get("why") or None


def _refuse_missing_rationale() -> NoReturn:
    err_console.print(
        "[red]error:[/] a rationale is required; "
        "pass --why or --why-file in a non-interactive context"
    )
    raise typer.Exit(EXIT_RATIONALE_REFUSED)


def _validate_or_exit(text: str | None) -> str:
    try:
        return validate_rationale(text)
    except RationaleRejectedError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_RATIONALE_REFUSED) from None


def _prompt_and_validate_rationale(ctx: typer.Context, context_lines: str) -> str:
    """Elicit and validate a rationale, unconditionally (shared by `_get_rationale`
    and `_get_required_rationale` — see those for when each applies)."""
    text = _read_supplied_rationale(ctx)
    if text is None:
        if not sys.stdin.isatty():
            _refuse_missing_rationale()
        out_console.print(context_lines)
        text = typer.prompt("Why? (this goes in the permanent record)")
    return _validate_or_exit(text)


def _rationale_required(repo: Repo) -> bool:
    return ops_mod.rationale_required(repo)


def _get_rationale(ctx: typer.Context, repo: Repo, context_lines: str) -> str | None:
    """Elicit a commit rationale per openspec:git-integration#eliciting-the-rationale.

    Returns `None` when `git.require_rationale` is false and no rationale was
    supplied. Exits with `EXIT_RATIONALE_REFUSED` when one is required but
    unavailable (non-interactive, no `--why`/`--why-file`) or rejected by
    `validate_rationale` (empty, stop-listed, or too short).
    """
    if not _rationale_required(repo) and not ctx.obj.get("why_file") and not ctx.obj.get("why"):
        return None
    return _prompt_and_validate_rationale(ctx, context_lines)


def _preflight_rationale(
    ctx: typer.Context,
    repo: Repo,
    *,
    always: bool = False,
    needed: Callable[[], bool] | None = None,
) -> None:
    """Refuse, before anything is written, a command whose rationale cannot be obtained.

    `_get_rationale` runs at commit time, after the domain operation has written its
    files, so a refusal there (openspec:git-integration#eliciting-the-rationale: exit
    code 7) would leave the working tree dirty with nothing committed. Call this ahead
    of the first write in every mutating command, or mutating branch of one. It checks
    only what is knowable up front:

    - a rationale given with `--why`/`--why-file` is validated now, so a rejected one
      (empty, stop-listed, too short) also stops before the work;
    - with none given and stdin not a TTY, a required rationale exits with
      `EXIT_RATIONALE_REFUSED`.

    An interactive run is left alone: it prompts after the work, where the prompt can
    say what was done. `always` is for operations that need a rationale whatever
    `git.require_rationale` says, and even with `--no-commit`, because it is recorded in
    the event itself (criteria changes, adjudications, study decisions); see
    `_get_required_rationale`. Otherwise `--no-commit` needs none.

    A command that commits only if its work finds something to record (`dedup` that
    merges nothing, `import` of a file already imported) can pass `needed`, a check
    that writes nothing. It runs only when the refusal is otherwise due, so a run
    that supplies a rationale or can prompt for one pays nothing, and a rerun that has
    nothing to commit is not refused for want of a rationale it would never use.
    """
    if ctx.obj["no_commit"] and not always:
        return
    supplied = _read_supplied_rationale(ctx)
    if supplied is not None:
        _validate_or_exit(supplied)
        return
    if (
        (always or _rationale_required(repo))
        and not sys.stdin.isatty()
        and (needed is None or needed())
    ):
        _refuse_missing_rationale()


def _get_required_rationale(ctx: typer.Context, repo: Repo, context_lines: str) -> str:
    """Like `_get_rationale`, but the rationale is required unconditionally,
    regardless of `git.require_rationale` — for operations the specification
    itself requires a rationale for with no config escape hatch: criteria
    changes (openspec:criteria-management#declaring-the-direction-of-a-change's "Why did you make
    this
    change?" prompt) and adjudications (openspec:adjudication: "A rationale is REQUIRED for
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
    """`--map title=Article Title,doi=DOI`; the syntax itself is `ingest`'s."""
    try:
        return pipeline_mod.parse_mapping(raw)
    except pipeline_mod.MappingSyntaxError as exc:
        raise typer.BadParameter(f"--map {exc}") from None


@app.command()
def init(
    ctx: typer.Context,
    path: str = typer.Argument(".", help="Directory to create the repository in"),
    title: str | None = typer.Option(None, "--title"),
    remote: str | None = typer.Option(None, "--remote"),
    actor_handle: str | None = typer.Option(None, "--actor", help="Your actor handle"),
    actor_name: str | None = typer.Option(None, "--actor-name"),
    actor_email: str | None = typer.Option(None, "--actor-email"),
    ci: bool = typer.Option(
        False, "--ci", help="Also install the GitHub Actions workflow that checks pull requests"
    ),
    ci_ref: str | None = typer.Option(
        None, "--ci-ref", help="With --ci: the strata tag, branch or commit the checks run from"
    ),
    methodologist: str | None = typer.Option(
        None,
        "--methodologist",
        help="With --ci: GitHub login asked to review a change to the criteria",
    ),
) -> None:
    """Create a repository: layout, strata.toml, .gitattributes, hooks, merge drivers, commit.

    With --ci the repository also gets .github/workflows/strata.yml, which runs `strata verify`,
    comments what a pull request does to the review, and labels changes to the criteria
    (openspec:review-repository-ci).
    """
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

    if (ci_ref or methodologist) and not ci:
        err_console.print("[red]error:[/] --ci-ref and --methodologist only apply with --ci")
        raise typer.Exit(EXIT_USAGE)
    extra_files = (
        {
            ci_workflows.CALLER_PATH: ci_workflows.caller_workflow(
                ref=ci_ref, methodologist=methodologist
            )
        }
        if ci
        else None
    )

    root = Path(path).resolve()
    try:
        init_mod.init_repository(
            root,
            title=title,
            actor_handle=actor_handle,
            actor_name=actor_name,
            actor_email=actor_email,
            remote=remote,
            extra_files=extra_files,
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
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Regenerate derived files that drifted; other problems are only reported",
    ),
) -> None:
    """Validate the whole repository."""
    repo = _resolve_repo(ctx)
    report = verify_mod.verify_repository(repo, fast=fast)
    regenerated: list[str] = []
    if fix:
        drifted = [i.path for i in report.issues if i.code == "E_DERIVED_DRIFT" and i.path]
        if drifted:
            try:
                with repo_lock(repo):
                    pool_mod.regenerate_all(repo)
            except LockTimeoutError as exc:
                _lock_busy(exc)
            regenerated = drifted
            report = verify_mod.verify_repository(repo, fast=fast)
    if ctx.obj["json"]:
        _print_json(
            {
                "ok": report.ok,
                **({"regenerated": regenerated} if fix else {}),
                "issues": [
                    {"code": i.code, "message": i.message, "path": i.path, "severity": i.severity}
                    for i in report.issues
                ],
            }
        )
    else:
        for path in regenerated:
            out_console.print(f"[green]regenerated[/] {path}")
        if regenerated:
            out_console.print("commit the regenerated files to keep them")
        for issue in report.issues:
            loc = f" ({issue.path})" if issue.path else ""
            colour = "yellow" if issue.severity == "warning" else "red"
            err_console.print(f"[{colour}]{issue.code}[/]{loc}: {issue.message}")
        if report.ok:
            out_console.print("[green]ok[/] — repository is valid")
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
    if s.retrieval is not None and s.retrieval.sought:
        r = s.retrieval
        out_console.print(
            f"\n[bold]RETRIEVAL[/]  {r.sought} reports sought    {r.retrieved} retrieved · "
            f"{r.outstanding} outstanding · {r.not_retrieved} not retrieved"
        )
        if r.outstanding:
            out_console.print("  strata retrieve")
    if s.extraction is not None:
        e = s.extraction
        out_console.print(
            f"\n[bold]EXTRACTION[/]  {e.studies} studies    {e.complete} complete · "
            f"{len(e.missing)} missing values"
        )
        for study_id, names in list(e.missing.items())[:10]:
            out_console.print(f"  {study_id}  missing: {', '.join(names)}")
        if len(e.missing) > 10:
            out_console.print(
                f"  ... and {len(e.missing) - 10} more  (strata extract --missing --list)"
            )
        if e.reconcile:
            out_console.print(
                f"  {e.reconcile} to reconcile             strata extract --reconcile"
            )
        elif e.missing:
            out_console.print("  strata extract --missing")
    if s.analyses:
        out_console.print("\n[bold]ANALYSES[/]")
        for a in s.analyses:
            note = {
                "stale-data": "[yellow]stale: its data changed[/]  strata analyze " + a.id,
                "stale-tool": "[yellow]stale: the tool changed[/]  strata analyze " + a.id,
                "missing": "not run yet  strata analyze " + a.id,
            }.get(a.state, a.state)
            out_console.print(f"  {a.id} ({a.label})  {note}")
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


def _fmt_estimate(summary: dict[str, Any] | None) -> str:
    if summary is None or summary.get("estimate") is None:
        return "n/a"
    scale = summary.get("scale") or ""
    text = f"{scale} = {summary['estimate']:.2f}"
    if summary.get("ci_lb") is not None:
        text += f" [{summary['ci_lb']:.2f}, {summary['ci_ub']:.2f}]"
    return text


@app.command("diff")
def diff_command(
    ctx: typer.Context,
    revisions: str = typer.Argument(..., metavar="<ref>..<ref>", help="e.g. v1-protocol..HEAD"),
) -> None:
    """Domain-level diff: criteria, records, pools, included studies and pooled estimates."""
    repo = _resolve_repo(ctx)
    try:
        base, head = diffcmd_mod.parse_range(revisions)
        result = diffcmd_mod.diff_refs(repo, base, head)
    except diffcmd_mod.DiffError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    if ctx.obj["json"]:
        _print_json(result.to_json())
        return
    v1, v2 = result.criteria_versions
    counts = result.criteria_deltas
    parts = [f"{n} {name}" for name, n in counts.items() if n]
    out_console.print(
        f"[bold]Criteria:[/]  v{v1} -> v{v2}" + (f"  ({', '.join(parts)})" if parts else "")
    )
    (i1, i2), (d1, d2) = result.records_identified, result.duplicates
    out_console.print(
        f"[bold]Records:[/]   {i1} -> {i2}  ({i2 - i1:+d} identified, {d2 - d1:+d} duplicates)"
    )
    for pool in result.pools:
        out_console.print(
            f"[bold]Pool:[/]      {pool.before} -> {pool.after} at {pool.stage}  "
            f"(+{pool.entered} entered, -{pool.left} left)"
        )
    out_console.print(f"[bold]Included:[/]  {result.studies[0]} -> {result.studies[1]} studies")
    for change in result.analyses:
        old, new = change.before, change.after
        if change.status == "unchanged":
            out_console.print(f"[bold]{change.analysis}:[/]  unchanged  {_fmt_estimate(new)}")
        elif change.status == "added":
            out_console.print(f"[bold]{change.analysis}:[/]  new  {_fmt_estimate(new)}")
        elif change.status == "removed":
            out_console.print(f"[bold]{change.analysis}:[/]  removed (was {_fmt_estimate(old)})")
        else:
            assert old is not None and new is not None
            out_console.print(
                f"[bold]{change.analysis}:[/]  {_fmt_estimate(old)} -> {_fmt_estimate(new)}"
            )
            i2a, i2b = old.get("I2"), new.get("I2")
            het = f"I2 = {i2a:.0f}% -> {i2b:.0f}%,  " if i2a is not None and i2b is not None else ""
            out_console.print(
                f"{' ' * (len(change.analysis) + 2)}  {het}"
                f"k = {old.get('k_studies')} -> {new.get('k_studies')}"
            )


def _commit_manifest_op(
    ctx: typer.Context, repo: Repo, *, op: str, scope: str, summary: str, trailers: dict[str, str]
) -> None:
    """Commit a `strata.toml`-only change (
    openspec:git-integration#one-operation-one-commit: every mutating command produces exactly one
    commit)."""
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
    _preflight_rationale(ctx, repo)
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
    _preflight_rationale(ctx, repo)
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
    _preflight_rationale(ctx, repo)

    if query_file:
        query = Path(query_file).read_text(encoding="utf-8")
    resolved_executed = executed or date.today().isoformat()

    written: dict[str, dict[str, Any]] = {}

    def say_what_was_recorded(recorded: ops_mod.SearchRecorded) -> None:
        written["record"] = recorded.record
        _warn_lock_reclaimed(recorded.lock_reclaimed_from)
        if recorded.query_pending:
            out_console.print(
                f"[yellow]warning:[/] no query string recorded for {recorded.record['id']} "
                "(PRISMA item 7) — supply it before the review is finalised"
            )

    def ask_why() -> str | None:
        record = written["record"]
        return _get_rationale(
            ctx,
            repo,
            f"You recorded search {record['id']} ({record['database']} via {record['platform']}).",
        )

    try:
        recorded = ops_mod.record_search(
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
            commit=not ctx.obj["no_commit"],
            rationale=ask_why,
            on_written=say_what_was_recorded,
        )
    except (searches_mod.SearchError, SchemaValidationError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    except LockTimeoutError as exc:
        _lock_busy(exc)

    if not recorded.committed:
        out_console.print(f"[green]recorded[/] search {recorded.record['id']} (not committed)")
        return
    out_console.print(f"[green]recorded[/] search {recorded.record['id']}")


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


def _import_one(
    ctx: typer.Context,
    repo: Repo,
    file: str,
    results: list[dict[str, Any]],
    *,
    imported_by: str,
    search_id: str | None,
    via: str | None,
    fmt: str | None,
    mapping: dict[str, str] | None,
    sheet: str | None,
    dry_run: bool,
) -> None:
    """One file of `strata import`: the shared operation, plus what this command says about it."""
    written: dict[str, pipeline_mod.ImportOutcome] = {}

    def say_what_happened(result: ops_mod.ImportResult) -> None:
        outcome = result.outcome
        written["outcome"] = outcome
        _warn_lock_reclaimed(result.lock_reclaimed_from)
        if ctx.obj["json"]:
            results.append({"file": file, **dataclasses.asdict(outcome)})
        if outcome.already_imported:
            if not ctx.obj["json"]:
                out_console.print(
                    f"[yellow]already imported[/] {file} as {outcome.import_id} — no changes made"
                )
            return
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

    def ask_why() -> str | None:
        return _get_rationale(ctx, repo, f"You imported {file} as {written['outcome'].import_id}.")

    ops_mod.import_file(
        repo,
        file,
        imported_by=imported_by,
        search_id=search_id,
        via=via,
        fmt=fmt,
        mapping=mapping,
        sheet=sheet,
        dry_run=dry_run,
        commit=not ctx.obj["no_commit"],
        rationale=ask_why,
        on_written=say_what_happened,
    )


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
    fmt: str | None = typer.Option(
        None,
        "--format",
        help="Override format detection: csl-json | ris | bibtex | medline | endnote-xml | "
        "csv | tsv | xlsx | citation-list",
    ),
    sheet: str | None = typer.Option(
        None, "--sheet", help="For .xlsx: the sheet name or position (default: the first sheet)"
    ),
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

    Each file is its own import (openspec:repository-format#directory-layout:
    `imports/<id>/`) and, unless `--dry-run`/`--no-commit`, its own commit —
    a failure partway through a multi-file import leaves every earlier file's
    import already committed rather than the tree half-written and dirty.
    """
    repo = _resolve_repo(ctx)
    exit_code = EXIT_OK
    results: list[dict[str, Any]] = []
    mapping = _parse_map_option(map_option) if map_option else None

    if not dry_run:
        _preflight_rationale(
            ctx,
            repo,
            needed=lambda: ops_mod.would_import_anything(
                repo,
                files,
                imported_by=by,
                search_id=search_id,
                via=via,
                fmt=fmt,
                mapping=mapping,
                sheet=sheet,
            ),
        )

    for file in files:
        try:
            _import_one(
                ctx,
                repo,
                file,
                results,
                imported_by=by,
                search_id=search_id,
                via=via,
                fmt=fmt,
                mapping=mapping,
                sheet=sheet,
                dry_run=dry_run,
            )
        except pipeline_mod.ImportPipelineError as exc:
            exit_code = EXIT_USAGE
            if ctx.obj["json"]:
                results.append({"file": file, "error": str(exc)})
            else:
                err_console.print(f"[red]error:[/] {file}: {exc}")
        except LockTimeoutError as exc:
            _lock_busy(exc)

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
    ops_mod.commit_domain_work(
        repo,
        op=op,
        scope=scope,
        summary=summary,
        actor=by,
        extra_trailers=extra_trailers,
        commit=not ctx.obj["no_commit"],
        rationale=lambda: _get_rationale(ctx, repo, f"You {summary}."),
    )


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

    def would_commit() -> bool:
        preview = engine_mod.preview_dedup(repo, strict=strict)  # writes nothing
        return bool(preview.auto_merged) or (review and bool(preview.review_queue))

    _preflight_rationale(ctx, repo, needed=None if undo != ("", "") else would_commit)

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
    """`<id>` may be any unambiguous prefix (openspec:cli); exits
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


def _apply_record_filter(
    records: list[dict[str, Any]], filter_expr: str, repo: Repo | None = None
) -> list[dict[str, Any]]:
    """Shared `--filter` evaluation (openspec:filter-language), used by `records list`,
    `screen`, and `assign`. Exits with `EXIT_USAGE` on a bad expression or a field
    that can't be evaluated, rather than raising past the CLI boundary."""
    try:
        return ops_mod.filter_records(records, filter_expr, repo)
    except ops_mod.FilterError as exc:
        _refuse_filter(exc)


def _refuse_filter(exc: ops_mod.FilterError) -> NoReturn:
    if exc.record_id is None:
        err_console.print(f"[red]error:[/] invalid --filter: {exc.detail}")
    else:
        err_console.print(f"[red]error:[/] --filter failed on record {exc.record_id}: {exc.detail}")
    raise typer.Exit(EXIT_USAGE)


def _resolve_filter_ids(repo: Repo, filter_expr: str) -> set[str]:
    """Canonical record ids matching `--filter`, per openspec:filter-language."""
    try:
        return set(ops_mod.matching_record_ids(repo, filter_expr))
    except ops_mod.FilterError as exc:
        _refuse_filter(exc)


@records_app.command("list")
def records_list(
    ctx: typer.Context,
    filter_expr: str | None = typer.Option(
        None, "--filter", help="Filter expression, openspec:filter-language"
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
        records = _apply_record_filter(records, filter_expr, repo)

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
    field: str = typer.Option(
        ..., "--field", help="The field to correct (title, author, year, DOI, ...)"
    ),
    value: str = typer.Option(
        ...,
        "--value",
        help="The corrected value (authors: 'Family, Given; Family, Given'; a date: YYYY-MM-DD)",
    ),
    by: str = typer.Option(..., "--by", help="Actor handle making the correction"),
) -> None:
    """Correct a metadata field, recording the change as a `record-amend` event.

    Plain-text fields (title, journal, DOI, ...), `author` and the date (`year`, or `issued` for a
    full date) can be corrected. An empty value removes the field. A DOI, PMID, PMCID or ISBN is
    stored as an import would store it, and a value the record already has changes nothing. A
    correction that changes how the record is identified keeps its id, and an export carrying the
    corrected value is then matched to it.
    """
    repo = _resolve_repo(ctx)
    resolved_id = _resolve_record_id(repo, record_id)
    try:
        changes = records_mod.preview_amendment(
            repo, record_id=resolved_id, field=field, value=value
        )
    except fieldedit_mod.FixFieldError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    _preflight_rationale(ctx, repo, needed=lambda: changes)

    def say_what_was_fixed(amended: ops_mod.RecordAmended) -> None:
        _warn_lock_reclaimed(amended.lock_reclaimed_from)
        old_text = fieldedit_mod.format_field_value(amended.field, amended.old)
        new_text = fieldedit_mod.format_field_value(amended.field, amended.new)
        if ctx.obj["json"]:
            payload: dict[str, Any] = {
                "record": resolved_id,
                "field": field,
                "old": amended.old,
                "new": amended.new,
            }
            if amended.alias:
                payload["alias"] = amended.alias
            if amended.shares_identity_with:
                payload["shares_identity_with"] = amended.shares_identity_with
            _print_json(payload)
        elif not amended.changed:
            out_console.print(f"unchanged {resolved_id}.{field} is already {new_text!r}")
        else:
            out_console.print(
                f"[green]fixed[/] {resolved_id}.{field}: {old_text!r} -> {new_text!r}"
            )
            if amended.shares_identity_with:
                err_console.print(
                    f"[yellow]warning:[/] {resolved_id} is now identified as "
                    f"{amended.shares_identity_with}; run `strata dedup` to merge them"
                )
            elif amended.alias:
                out_console.print(
                    "the record keeps its id; an export carrying the corrected value now matches it"
                )

    try:
        ops_mod.amend_record(
            repo,
            record_id=resolved_id,
            field=field,
            value=value,
            actor=by,
            commit=not ctx.obj["no_commit"],
            rationale=lambda: _get_rationale(ctx, repo, f"You corrected {field}."),
            on_written=say_what_was_fixed,
        )
    except fieldedit_mod.FixFieldError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    except LockTimeoutError as exc:
        _lock_busy(exc)


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
    """Add a criterion. A criterion added behaves as `tightened`
    (openspec:criteria-management#declaring-the-direction-of-a-change)."""
    repo = _resolve_repo(ctx)
    rationale = _get_required_rationale(
        ctx, repo, f"You are adding a new {kind} criterion: {label!r}."
    )

    def say_what_was_added(added: ops_mod.CriterionAdded) -> None:
        _warn_lock_reclaimed(added.lock_reclaimed_from)
        if ctx.obj["json"]:
            _print_json(added.criterion)
        else:
            out_console.print(
                f"[green]added[/] {added.criterion['id']} (criteria v{added.version})"
            )

    try:
        ops_mod.add_criterion(
            repo,
            kind=kind,
            label=label,
            definition=definition,
            applies_at=_split_stages(applies_at),
            actor=by,
            rationale=rationale,
            criterion_id=criterion_id,
            commit=not ctx.obj["no_commit"],
            on_written=say_what_was_added,
        )
    except (criteria_mod.CriteriaError, SchemaValidationError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    except LockTimeoutError as exc:
        _lock_busy(exc)


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
    """Edit a criterion; MUST classify the change's direction
    (openspec:criteria-management#declaring-the-direction-of-a-change)."""
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
    """Retire a criterion; behaves as `loosened`
    (openspec:criteria-management#declaring-the-direction-of-a-change)."""
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


_DECISION_KEYS = {"i": "include", "e": "exclude", "m": "maybe"}


def _parse_criteria_numbers(raw: str, active_criteria: list[dict[str, Any]]) -> list[str]:
    """`1,3` -> the ids of the 1st and 3rd listed criteria
    (openspec:screening#screening-surface-contract's
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
    full_text_note: str | None = None,
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
    if full_text_note:
        lines.append("")
        lines.append(full_text_note)
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
        None, "--decisions", help="TSV of record_id/decision/criteria/note"
    ),
) -> None:
    """Open the screening queue for `stage`, or bulk-import decisions with `--decisions`."""
    repo = _resolve_repo(ctx)

    if decisions_file:
        _preflight_rationale(ctx, repo)
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
    _preflight_rationale(ctx, repo)

    records = records_mod.index_by_id(records_mod.read_records(repo))
    active_criteria = [
        c for c in criteria_mod.list_criteria(repo, at=stage) if c["status"] == "active"
    ]

    full_text_notes = (
        _zotero_full_text_notes(ctx, repo, queue)
        if stage != screening_mod.configured_stages(repo)[0]
        else {}
    )

    decided = 0
    last_decided_index: int | None = None
    index = 0
    while index < len(queue):
        record_id = queue[index]
        out_console.print(
            _render_screen_record(
                index,
                len(queue),
                stage,
                records[record_id],
                active_criteria,
                full_text_notes.get(record_id),
            )
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
    _preflight_rationale(ctx, repo)

    written: dict[str, int] = {}

    def say_what_was_assigned(assigned: ops_mod.ReviewersAssigned) -> None:
        written["count"] = assigned.record_count
        _warn_lock_reclaimed(assigned.lock_reclaimed_from)
        out_console.print(
            f"[green]assigned[/] {assigned.record_count} record(s) at {stage} "
            f"to {', '.join(assigned.actors)}"
        )

    try:
        ops_mod.assign_reviewers(
            repo,
            stage=stage,
            actors=actors.split(","),
            actor=by,
            filter_expr=filter_expr,
            commit=not ctx.obj["no_commit"],
            rationale=lambda: _get_rationale(
                ctx, repo, f"You assigned {written['count']} {stage} record(s)."
            ),
            on_written=say_what_was_assigned,
        )
    except ops_mod.FilterError as exc:
        _refuse_filter(exc)
    except screening_mod.ScreeningError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    except LockTimeoutError as exc:
        _lock_busy(exc)


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
    """Open the stale queue: openspec:staleness."""
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
    _preflight_rationale(ctx, repo)

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
    """Resolve screening conflicts: openspec:adjudication."""
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
    # Each adjudication carries its own rationale in the event, so one is needed whatever
    # `git.require_rationale` says; fail now rather than after earlier decisions are recorded.
    _preflight_rationale(ctx, repo, always=True)

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


def _parse_locator_options(raw: list[str] | None) -> dict[str, str] | None:
    """`--locator doi=10.1/x --locator pmid=123` -> `{"doi": "10.1/x", "pmid": "123"}`."""
    if not raw:
        return None
    locator: dict[str, str] = {}
    for item in raw:
        kind, sep, value = item.partition("=")
        if (
            not sep
            or not value.strip()
            or kind not in ("doi", "pmid", "pmcid", "arxiv", "isbn", "url")
        ):
            raise typer.BadParameter(
                f"--locator {item!r} must look like doi=..., pmid=..., pmcid=..., arxiv=..., "
                "isbn=... or url=..."
            )
        locator[kind] = value.strip()
    return locator


def _render_report(
    index: int,
    total: int,
    report: str,
    record: dict[str, Any],
    zotero: zotero_retrieval.ZoteroDocument | None = None,
) -> str:
    journal = record.get("container-title") or ""
    lines = [f"{report}  {records_mod.short_citation(record)}  {journal}".rstrip()]
    for kind, label in (("DOI", "doi"), ("PMID", "pmid"), ("URL", "url")):
        if record.get(kind):
            lines.append(f"  {label}:{record[kind]}")
    if zotero is not None and zotero.state != "unlinked":
        lines.append(f"  Zotero: {_zotero_state_text(zotero)}")
    lines.append("")
    lines.append(f"({index + 1} of {total})")
    menu = (
        "[f] I have the file   [u] open DOI in browser   [i] interlibrary loan requested\n"
        "[n] not retrievable   [s] skip   [q] quit"
    )
    if zotero is not None and zotero.attachment_present:
        menu = (
            "[o] open in Zotero   [z] record it as retrieved from Zotero\n"
            "[f] I have the file   [u] open DOI in browser   [i] interlibrary loan requested\n"
            "[n] not retrievable   [s] skip   [q] quit"
        )
    lines.append(escape(menu))  # the key letters are in [brackets], which Rich would read as tags
    return "\n".join(lines)


def _zotero_state_text(document: zotero_retrieval.ZoteroDocument) -> str:
    return {
        "pdf": "PDF attachment present",
        "files": "attachment present (not a PDF)",
        "none": "in the library, no file attached",
        "stale": "full text unavailable (the item no longer exists in Zotero)",
        "unlinked": "not linked",
    }[document.state]


@app.command("retrieve")
def retrieve_command(
    ctx: typer.Context,
    by: str = typer.Option(..., "--by", help="Actor handle recording the outcome"),
    report: str | None = typer.Option(None, "--report", help="Record one outcome for this report"),
    outcome: str | None = typer.Option(
        None, "--outcome", help="retrieved | ill-requested | not-retrieved | sought"
    ),
    source: str | None = typer.Option(None, "--source", help="e.g. institutional-access"),
    version: str | None = typer.Option(
        None, "--version", help="preprint | version-of-record | ..."
    ),
    path: str | None = typer.Option(None, "--path", help="Local file path (a convenience only)"),
    locator: list[str] | None = _LOCATOR_OPTION,
    reason: str | None = typer.Option(None, "--reason", help="Why it could not be retrieved"),
    reason_text: str | None = typer.Option(None, "--reason-text", help="Required for 'other'"),
    list_only: bool = typer.Option(False, "--list", help="List outstanding reports and exit"),
    from_zotero: bool = typer.Option(
        False,
        "--zotero",
        help="With --outcome retrieved: record the document as held in Zotero, by its item key",
    ),
) -> None:
    """Work the queue of reports sought for retrieval: openspec:full-text-retrieval.

    Interactive by default. With --report and --outcome it records one outcome and exits
    (scriptable); with --list it prints the outstanding reports.

    Example: strata retrieve --by ethan --report rpt_3kq8v1r0zx2m4a7b --outcome retrieved
    --source institutional-access --version version-of-record
    """
    repo = _resolve_repo(ctx)
    records = records_mod.index_by_id(records_mod.read_records(repo))

    if report is not None:
        if outcome is None:
            err_console.print("[red]error:[/] --report needs --outcome")
            raise typer.Exit(EXIT_USAGE)
        _preflight_rationale(ctx, repo)
        zotero_ref: dict[str, str] | None = None
        if from_zotero:
            zotero_ref = _zotero_manifest_ref(ctx, repo, ids_mod.record_id_for_report(report))
            source = source or "zotero"
        try:
            outcome_recorded = ops_mod.record_retrieval(
                repo,
                report=report,
                outcome=outcome,
                actor=by,
                source=source,
                locator=_parse_locator_options(locator),
                version=version,
                reason=reason,
                reason_text=reason_text,
                path=path,
                zotero=zotero_ref,
                commit=not ctx.obj["no_commit"],
                rationale=lambda: _get_rationale(ctx, repo, f"You {outcome}: {report}."),
            )
        except retrieval_mod.RetrievalError as exc:
            err_console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(EXIT_USAGE) from None
        except LockTimeoutError as exc:
            _lock_busy(exc)
        _warn_lock_reclaimed(outcome_recorded.lock_reclaimed_from)
        if ctx.obj["json"]:
            _print_json(
                {"report": report, "status": outcome, "event": outcome_recorded.event["id"]}
            )
        else:
            out_console.print(f"[green]recorded[/] {report}: {outcome}")
        return

    queue = retrieval_mod.outstanding_reports(repo)
    counts = retrieval_mod.retrieval_counts(repo)
    zotero_found = _zotero_lookup(ctx, repo, retrieval_mod.sought_reports(repo))
    zotero_line = _zotero_header(zotero_found)
    if list_only or ctx.obj["json"]:
        items = [
            {
                "report": r,
                "record": ids_mod.record_id_for_report(r),
                "citation": records_mod.short_citation(
                    records.get(ids_mod.record_id_for_report(r), {})
                ),
                "doi": records.get(ids_mod.record_id_for_report(r), {}).get("DOI"),
                **_zotero_json(zotero_found, ids_mod.record_id_for_report(r)),
            }
            for r in queue
        ]
        if ctx.obj["json"]:
            _print_json(
                {
                    "sought": counts.sought,
                    "outstanding": counts.outstanding,
                    **(
                        {"zotero_attachments_found": zotero_found.attachments_found}
                        if zotero_found is not None and zotero_found.unavailable is None
                        else {}
                    ),
                    "reports": items,
                }
            )
        else:
            out_console.print(
                f"{counts.sought} reports sought. {counts.outstanding} outstanding.{zotero_line}"
            )
            for item in items:
                note = ""
                if "zotero" in item:
                    note = f"  [Zotero: {item['zotero']['state']}]"
                out_console.print(f"  {item['report']}  {item['citation']}{note}")
        return

    if queue:
        _preflight_rationale(ctx, repo)
    out_console.print(
        f"\n  {counts.sought} reports sought. {counts.outstanding} outstanding.{zotero_line}\n"
    )
    recorded = 0
    index = 0
    while index < len(queue):
        current = queue[index]
        record = records.get(ids_mod.record_id_for_report(current), {})
        document = (
            zotero_found.get(ids_mod.record_id_for_report(current))
            if zotero_found is not None and zotero_found.unavailable is None
            else None
        )
        out_console.print(_render_report(index, len(queue), current, record, document))
        choice = typer.prompt("Outcome", default="s").strip().lower()
        if choice == "q":
            break
        if choice == "s":
            index += 1
            continue
        if choice == "o" and document is not None and document.uri is not None:
            out_console.print(f"opening {document.uri}")
            if not webbrowser.open(document.uri):
                out_console.print(
                    "[yellow]could not open it; paste the link above into a browser[/]"
                )
            continue
        if choice == "u":
            doi = record.get("DOI")
            if doi:
                webbrowser.open(f"https://doi.org/{doi}")
            else:
                out_console.print("[yellow]no DOI on this record to open[/]")
            try:
                link = retrieval_mod.open_access_link(repo, current)
            except unpaywall_mod.EnrichmentError as exc:
                out_console.print(f"[yellow]open-access lookup failed:[/] {exc}")
            else:
                if link is not None:
                    out_console.print(f"[green]open access copy:[/] {link.url}")
            continue
        try:
            if choice == "z" and document is not None and document.attachment_present:
                entered_version = typer.prompt("Version", default="version-of-record").strip()
                retrieval_mod.record_retrieval(
                    repo,
                    report=current,
                    status="retrieved",
                    actor=by,
                    source="zotero",
                    version=entered_version,
                    zotero=document.manifest_ref,
                )
            elif choice == "f":
                entered_path = typer.prompt("Path to the file (optional)", default="").strip()
                entered_source = typer.prompt("Source", default="institutional-access").strip()
                entered_version = typer.prompt("Version", default="version-of-record").strip()
                retrieval_mod.record_retrieval(
                    repo,
                    report=current,
                    status="retrieved",
                    actor=by,
                    source=entered_source,
                    version=entered_version,
                    path=entered_path or None,
                )
            elif choice == "i":
                retrieval_mod.record_retrieval(
                    repo, report=current, status="ill-requested", actor=by
                )
            elif choice == "n":
                entered_reason = typer.prompt(
                    f"Reason ({', '.join(retrieval_mod.NOT_RETRIEVED_REASONS)})",
                    default="no-access",
                ).strip()
                entered_text = (
                    typer.prompt("What happened?").strip() if entered_reason == "other" else None
                )
                retrieval_mod.record_retrieval(
                    repo,
                    report=current,
                    status="not-retrieved",
                    actor=by,
                    reason=entered_reason,
                    reason_text=entered_text,
                )
            else:
                out_console.print(f"[yellow]unrecognised choice {choice!r}[/]")
                continue
        except retrieval_mod.RetrievalError as exc:
            out_console.print(f"[red]error:[/] {exc}")
            continue
        recorded += 1
        index += 1

    if recorded:
        pool_mod.regenerate_all(repo)
        _commit_domain_op(
            ctx, repo, op="retrieve", scope=None, summary=f"recorded {recorded} outcome(s)", by=by
        )
    out_console.print(f"[green]done[/] -- {recorded} outcome(s) recorded")


# ------------------------------------------------------------------------------------ zotero


def _zotero_connector(ctx: typer.Context, *, prompt: bool = True) -> zotero_ops.Connector:
    """Connections to Zotero for one command.

    A key is asked for (hidden) only on an interactive terminal, only when the Web API is the one
    needed, and only when there is a keychain to keep it in; it is never typed in to be thrown away
    and never written anywhere but that keychain (openspec:zotero-integration).
    """

    def prompt_key() -> str | None:
        if ctx.obj["json"] or not sys.stdin.isatty():
            return None
        return str(
            typer.prompt(
                "Zotero API key (kept in your keychain, never in the repository)", hide_input=True
            )
        )

    def connector(preference: str, need_write: bool) -> zotero_connect.Connection:
        return zotero_connect.connect(
            preference, need_write=need_write, prompt_key=prompt_key if prompt else None
        )

    return connector


def _zotero_notices(notices: Sequence[str]) -> None:
    for notice in notices:
        err_console.print(f"[yellow]note:[/] {notice}")


@contextlib.contextmanager
def _zotero_errors() -> Iterator[None]:
    """Report what can go wrong with a `zotero` command as an error and an exit code."""
    try:
        yield
    except LockTimeoutError as exc:
        _lock_busy(exc)
    except RationaleRejectedError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_RATIONALE_REFUSED) from None
    except (
        zotero_ops.ZoteroOperationError,
        pipeline_mod.ImportPipelineError,
        records_mod.RecordNotFoundError,
        records_mod.AmbiguousRecordIdError,
        SchemaValidationError,
    ) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    except ReferenceManagerError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_GENERIC) from None


def _zotero_rationale(ctx: typer.Context, repo: Repo, context: str) -> ops_mod.RationaleSource:
    """The rationale for an operation that works out, after reading Zotero, whether it has
    anything to commit: the text given with `--why` (checked now), a prompt on a terminal, or
    nothing, in which case the operation refuses before writing if it has something to record."""
    supplied = _read_supplied_rationale(ctx)
    if supplied is not None:
        return _validate_or_exit(supplied)
    if sys.stdin.isatty():
        return lambda: _get_rationale(ctx, repo, context)
    return None


def _zotero_lookup(
    ctx: typer.Context, repo: Repo, reports: Sequence[str]
) -> zotero_retrieval.DocumentLookup | None:
    """Where the full texts of some reports are in Zotero, or `None` if the review is not linked.

    Never fails the command: a Zotero that cannot be reached is said once, and the work carries on.
    """
    lookup = zotero_retrieval.lookup(
        repo,
        [ids_mod.record_id_for_report(r) for r in reports],
        connector=_zotero_connector(ctx, prompt=False),
    )
    if lookup is not None:
        _zotero_notices(lookup.notices)
        if lookup.unavailable is not None:
            err_console.print(
                f"[yellow]note:[/] Zotero could not be asked about full texts "
                f"({lookup.unavailable}); carrying on without it"
            )
    return lookup


def _zotero_header(lookup: zotero_retrieval.DocumentLookup | None) -> str:
    if lookup is None:
        return ""
    if lookup.unavailable is not None:
        return " Zotero: not reachable."
    return f" Zotero: {lookup.attachments_found} attachments found."


def _zotero_json(lookup: zotero_retrieval.DocumentLookup | None, record_id: str) -> dict[str, Any]:
    if lookup is None or lookup.unavailable is not None:
        return {}
    document = lookup.get(record_id)
    return {
        "zotero": {
            "state": document.state,
            "item_key": document.ref.key if document.ref is not None else None,
        }
    }


def _zotero_manifest_ref(ctx: typer.Context, repo: Repo, record_id: str) -> dict[str, str]:
    """The Zotero item to record for `--zotero`, or an error saying why there is none."""
    lookup = zotero_retrieval.lookup(
        repo, [record_id], connector=_zotero_connector(ctx, prompt=False)
    )
    if lookup is None:
        err_console.print(
            "[red]error:[/] --zotero needs a Zotero link; run `strata zotero link` first"
        )
        raise typer.Exit(EXIT_USAGE)
    if lookup.unavailable is not None:
        err_console.print(f"[red]error:[/] Zotero could not be asked: {lookup.unavailable}")
        raise typer.Exit(EXIT_GENERIC)
    document = lookup.get(record_id)
    ref = document.manifest_ref
    if not document.attachment_present or ref is None:
        err_console.print(
            f"[red]error:[/] Zotero has no attachment for this report "
            f"({_zotero_state_text(document)}); nothing to record"
        )
        raise typer.Exit(EXIT_USAGE)
    return ref


def _zotero_full_text_notes(
    ctx: typer.Context, repo: Repo, record_ids: Sequence[str]
) -> dict[str, str]:
    """A line per record on where its full text is in Zotero, for screening at a full-text stage.

    Whatever is wrong with Zotero or a link only changes the line; it never stops a decision being
    recorded (openspec:zotero-integration#identity-mapping).
    """
    lookup = zotero_retrieval.lookup(
        repo, list(record_ids), connector=_zotero_connector(ctx, prompt=False)
    )
    if lookup is None:
        return {}
    _zotero_notices(lookup.notices)
    if lookup.unavailable is not None:
        err_console.print(
            f"[yellow]note:[/] Zotero could not be asked about full texts "
            f"({lookup.unavailable}); screening carries on without it"
        )
        return {}
    notes: dict[str, str] = {}
    for record_id, document in lookup.documents.items():
        if document.state in ("pdf", "files"):
            notes[record_id] = (
                f"Full text: {_zotero_state_text(document)} in Zotero "
                f"(strata zotero open {record_id})"
            )
        elif document.state == "none":
            notes[record_id] = "Full text: in Zotero, but no file is attached"
        elif document.state == "stale":
            notes[record_id] = "[yellow]Full text unavailable:[/] its Zotero item no longer exists"
    return notes


def _citation_of(csl: dict[str, Any]) -> str:
    return f"{records_mod.short_citation(csl)}  {csl.get('title') or ''}".strip()


@zotero_app.command("link")
def zotero_link_command(
    ctx: typer.Context,
    by: str = typer.Option(..., "--by", help="Actor handle linking the review"),
    library: str | None = typer.Option(
        None, "--library", help="users/<id> or groups/<id>; asked for if there is a choice"
    ),
    web: bool = typer.Option(
        False,
        "--web",
        help="Use the Web API (needs an API key) so included studies can be pushed to Zotero",
    ),
) -> None:
    """Link this review to a Zotero library and map the records it already has to its items.

    Uses Zotero's local API when the desktop app offers it (no key, nothing leaves this computer),
    and the Web API otherwise. Records are matched to items by DOI, then PMID, then title, year and
    first author; an item that matches nothing is listed, never forced onto the nearest record. An
    API key is kept only in your operating system's keychain, or read from $STRATA_ZOTERO_API_KEY.
    """
    repo = _resolve_repo(ctx)

    def choose(libraries: Sequence[Any]) -> str:
        if ctx.obj["json"] or not sys.stdin.isatty():
            return ""
        for number, lib in enumerate(libraries, start=1):
            out_console.print(f"  {number}  {lib.library}  {lib.name}")
        picked = typer.prompt("Library number", default="1").strip()
        return str(libraries[int(picked) - 1].library) if picked.isdigit() else ""

    with _zotero_errors():
        result = zotero_ops.link(
            repo,
            actor=by,
            connector=_zotero_connector(ctx),
            library=library,
            web=web,
            choose_library=choose,
            commit=not ctx.obj["no_commit"],
            rationale=_zotero_rationale(ctx, repo, "You linked this review to Zotero."),
        )
    _zotero_notices(result.notices)
    _warn_lock_reclaimed(result.lock_reclaimed_from)
    report = result.report
    if ctx.obj["json"]:
        _print_json(
            {
                "library": result.library,
                "transport": result.transport,
                "write": result.write,
                "write_note": result.write_note,
                "rows_written": result.rows_written,
                "matched": len(report.matched),
                "ambiguous": [
                    {"item": a.item.ref.key, "via": a.via, "records": list(a.record_ids)}
                    for a in report.ambiguous
                ],
                "candidates": [
                    {
                        "item": c.item.ref.key,
                        "records": [
                            {"record": x.record_id, "score": round(x.score, 3)}
                            for x in c.candidates
                        ],
                    }
                    for c in report.candidates
                ],
                "unmatched": [i.ref.key for i in report.unmatched],
                "committed": result.committed,
            }
        )
        return
    how = "the local API" if result.transport == "local" else "the Web API"
    out_console.print(f"[green]linked[/] {result.library} through {how}")
    if result.write_note:
        out_console.print(f"  [yellow]{result.write_note}[/]")
    total = (
        len(report.matched) + len(report.ambiguous) + len(report.candidates) + len(report.unmatched)
    )
    out_console.print(
        f"  matched {len(report.matched)} of {total} library items to records "
        f"({result.rows_written} new or updated links)"
    )
    for ambiguous in report.ambiguous:
        out_console.print(
            f"  [yellow]ambiguous[/] {ambiguous.item.ref.key} {_citation_of(ambiguous.item.csl)}: "
            f"{len(ambiguous.record_ids)} records share its {ambiguous.via} "
            f"({', '.join(ambiguous.record_ids)}); not linked"
        )
    for candidate in report.candidates:
        best = candidate.candidates[0]
        out_console.print(
            f"  [yellow]possible match, not linked[/] {candidate.item.ref.key} "
            f"{_citation_of(candidate.item.csl)} -> {best.record_id} (score {best.score:.2f}); "
            "check them, then `strata fix` or `strata dedup` as needed"
        )
    for item in report.unmatched:
        out_console.print(
            f"  not in this review: {item.ref.key} {_citation_of(item.csl)} "
            "(`strata zotero pull` brings it in)"
        )


@zotero_app.command("pull")
def zotero_pull_command(
    ctx: typer.Context,
    collection: str = typer.Option(..., "--collection", help="A Zotero collection, by name or key"),
    by: str = typer.Option(..., "--by", help="Actor handle running the pull"),
    search_id: str | None = typer.Option(
        None, "--search", help="Id of the recorded search whose results the collection holds"
    ),
    via: str | None = typer.Option(
        None,
        "--via",
        help="For a hand-built collection: citation-searching | website | organisation | "
        "registry | contact",
    ),
) -> None:
    """Pull a Zotero collection as an import source.

    Exactly one of --search (the collection holds the results of a recorded database search) and
    --via (a hand-built collection, counted by PRISMA as another method) is required. The
    collection's name and the day it was pulled are kept for the PRISMA report. Items already
    linked to a record correct it where Zotero's bibliographic metadata differs, each correction a
    `record-amend` event; no screening decision ever crosses.
    """
    repo = _resolve_repo(ctx)
    with _zotero_errors():
        result = zotero_ops.pull(
            repo,
            actor=by,
            connector=_zotero_connector(ctx),
            collection=collection,
            search_id=search_id,
            via=via,
            commit=not ctx.obj["no_commit"],
            rationale=_zotero_rationale(ctx, repo, f"You pulled {collection!r} from Zotero."),
        )
    _zotero_notices(result.notices)
    _warn_lock_reclaimed(result.lock_reclaimed_from)
    corrected = [a for a in result.amendments if a.changed]
    if ctx.obj["json"]:
        _print_json(
            {
                "collection": result.collection.name,
                "key": result.collection.key,
                "items": result.items_pulled,
                "already_linked": result.already_linked,
                "records_created": result.records_created,
                "existing_records_appended": result.existing_records_appended,
                "links_written": result.rows_written,
                "import": result.import_id,
                "corrected": [
                    {"record": a.record_id, "field": a.field, "old": a.old, "new": a.new}
                    for a in corrected
                ],
                "rejected": [{"line": r.line, "error": r.error} for r in result.rejected],
                "unmatched": [i.ref.key for i in result.unmatched],
                "ambiguous": [i.item.ref.key for i in result.ambiguous],
                "vanished": list(result.vanished),
                "committed": result.committed,
            }
        )
        return
    out_console.print(
        f"[green]pulled[/] {result.items_pulled} items from {result.collection.name!r}: "
        f"{result.records_created} new records, {result.existing_records_appended} matched "
        f"records already in the review, {result.already_linked} already linked, "
        f"{len(corrected)} correction(s)"
    )
    if result.import_id:
        out_console.print(f"  import {result.import_id}")
    for amendment in corrected[:20]:
        out_console.print(
            f"  corrected {amendment.record_id} {amendment.field}: "
            f"{amendment.old!r} -> {amendment.new!r}"
        )
    if len(corrected) > 20:
        out_console.print(f"  ... and {len(corrected) - 20} more (see `strata why <record>`)")
    for rejected in result.rejected:
        out_console.print(f"  [yellow]not imported[/] item {rejected.line}: {rejected.error}")
    for item in result.unmatched:
        out_console.print(f"  [yellow]not linked[/] {item.ref.key} {_citation_of(item.csl)}")
    for ambiguous in result.ambiguous:
        out_console.print(
            f"  [yellow]ambiguous[/] {ambiguous.item.ref.key}: "
            f"{', '.join(ambiguous.record_ids)} share its {ambiguous.via}; not linked"
        )
    for key in result.vanished:
        out_console.print(
            f"  [yellow]skipped[/] {key}: it is linked to a record that is no longer in the review"
        )


@zotero_app.command("push")
def zotero_push_command(
    ctx: typer.Context,
    collection: str = typer.Option(..., "--collection", help="A Zotero collection, by name or key"),
    by: str = typer.Option(..., "--by", help="Actor handle running the push"),
    set_name: str = typer.Option("included", "--set", help="Which records to push: included"),
) -> None:
    """Put the included studies in a Zotero collection, so you can cite them while writing.

    Creates Zotero items for studies Zotero lacks and adds the ones it has to the collection. It
    never deletes anything, never changes an item it did not create beyond adding it to the
    collection, and refuses (item by item) any item edited in Zotero since strata last saw it: pull
    first. Needs a link made with --web and an API key that can write.
    """
    repo = _resolve_repo(ctx)
    with _zotero_errors():
        result = zotero_ops.push(
            repo,
            actor=by,
            connector=_zotero_connector(ctx),
            set_name=set_name,
            collection=collection,
            commit=not ctx.obj["no_commit"],
            rationale=_zotero_rationale(
                ctx, repo, f"You pushed the {set_name} studies to {collection!r} in Zotero."
            ),
        )
    _zotero_notices(result.notices)
    _warn_lock_reclaimed(result.lock_reclaimed_from)
    problems = [o for o in result.outcomes if o.status in ("refused", "stale", "failed")]
    if ctx.obj["json"]:
        _print_json(
            {
                "collection": collection,
                "created": result.count("created"),
                "added": result.count("added"),
                "unchanged": result.count("unchanged"),
                "problems": [
                    {"record": o.record_id, "status": o.status, "detail": o.detail}
                    for o in problems
                ],
                "committed": result.committed,
            }
        )
    else:
        out_console.print(
            f"[green]pushed[/] to {collection!r}: {result.count('created')} created, "
            f"{result.count('added')} added, {result.count('unchanged')} already there"
        )
        for outcome in problems:
            detail = f": {outcome.detail}" if outcome.detail else ""
            out_console.print(f"  [yellow]{outcome.status}[/] {outcome.record_id}{detail}")
    if problems:
        raise typer.Exit(EXIT_CONFLICT)


@zotero_app.command("status")
def zotero_status_command(ctx: typer.Context) -> None:
    """Which records are linked to Zotero, which are not, and which links have gone stale."""
    repo = _resolve_repo(ctx)
    with _zotero_errors():
        report = zotero_ops.status(repo, connector=_zotero_connector(ctx, prompt=False))
    _zotero_notices(report.notices)
    if ctx.obj["json"]:
        _print_json(
            {
                "library": report.library,
                "records": report.records,
                "mapped": report.mapped,
                "unmapped": list(report.unmapped),
                "stale": (
                    None
                    if report.stale is None
                    else [{"record": r, "item": k} for r, k in report.stale]
                ),
                "orphaned": list(report.orphaned),
                "unreachable": report.unreachable,
            }
        )
        return
    out_console.print(f"linked to {report.library}" + ("" if report.write else " (read-only)"))
    out_console.print(f"  {report.mapped} of {report.records} records mapped to a Zotero item")
    if report.unmapped:
        out_console.print(f"  {len(report.unmapped)} not mapped")
    if report.stale is None:
        reason = f" ({report.unreachable})" if report.unreachable else ""
        out_console.print(
            f"  [yellow]stale links not checked: Zotero could not be reached{reason}[/]"
        )
    elif report.stale:
        out_console.print(
            f"  [yellow]{len(report.stale)} stale link(s)[/] -- the item was deleted:"
        )
        for record_id, key in report.stale:
            out_console.print(f"    {record_id}  item {key}  (full text unavailable)")
    else:
        out_console.print("  no stale links")
    if report.orphaned:
        out_console.print(f"  {len(report.orphaned)} link(s) to records no longer in the review")


@zotero_app.command("open")
def zotero_open_command(
    ctx: typer.Context,
    record: str = typer.Argument(..., help="A record id, or any unambiguous prefix of one"),
    print_only: bool = typer.Option(
        False, "--print-only", help="Print the zotero:// link instead of opening it"
    ),
) -> None:
    """Open a record's PDF (or, with no PDF, its item) in Zotero."""
    repo = _resolve_repo(ctx)
    with _zotero_errors():
        record_id = records_mod.resolve_id_prefix(repo, record)
        target = zotero_ops.open_target(
            repo, record_id, connector=_zotero_connector(ctx, prompt=False)
        )
    if ctx.obj["json"]:
        _print_json({"record": target.record_id, "kind": target.kind, "uri": target.uri})
        return
    out_console.print(target.uri, soft_wrap=True, markup=False, highlight=False)
    if not print_only and not webbrowser.open(target.uri):
        err_console.print("[yellow]note:[/] could not launch Zotero from here; use the link above")


def _render_study_record(report: str, record: dict[str, Any]) -> str:
    lines = [f"{report}  {records_mod.short_citation(record)}", f"  {record.get('title') or ''}"]
    if record.get("DOI"):
        lines.append(f"  doi:{record['DOI']}")
    abstract = (record.get("abstract") or "").strip()
    if abstract:
        lines.append(f"  {abstract[:300]}{'...' if len(abstract) > 300 else ''}")
    return "\n".join(lines)


@app.command("studies")
def studies_command(
    ctx: typer.Context,
    by: str | None = typer.Option(None, "--by", help="Actor handle recording the decision"),
    list_only: bool = typer.Option(False, "--list", help="Show the counts and suggestions only"),
    group: list[str] | None = _GROUP_OPTION,
    study: str | None = typer.Option(None, "--study", help="With --group: redefine this study"),
    split: str | None = typer.Option(None, "--split", help="Report id to split into studies"),
    into: int = typer.Option(2, "--into", help="With --split: how many studies"),
) -> None:
    """Group reports into studies and split multi-study reports: openspec:study-grouping.

    Suggestions (shared trial registration, shared authors and sample, follow-up language,
    mutual citation) are shown with their evidence and never applied automatically. Every
    grouping and splitting decision needs a rationale (--why).

    Example: strata --why "Same trial, 12-month follow-up" studies --by ethan \\
        --group rpt_3kq8v1r0zx2m4a7b --group rpt_9m2f4t7c1x8a5d6e
    """
    repo = _resolve_repo(ctx)
    included = studies_mod.included_reports(repo)
    records = records_mod.index_by_id(records_mod.read_records(repo))

    def record_of(report: str) -> dict[str, Any]:
        return records.get(ids_mod.record_id_for_report(report), {})

    if group or split:
        if not by:
            err_console.print("[red]error:[/] --by is required to record a decision")
            raise typer.Exit(EXIT_USAGE)
        rationale = _get_required_rationale(ctx, repo, "You are recording a study decision.")
        try:
            if group:
                recorded_decision = ops_mod.group_reports(
                    repo,
                    reports=group,
                    actor=by,
                    rationale=rationale,
                    study=study,
                    commit=not ctx.obj["no_commit"],
                )
            else:
                assert split is not None
                recorded_decision = ops_mod.split_report(
                    repo,
                    report=split,
                    parts=into,
                    actor=by,
                    rationale=rationale,
                    commit=not ctx.obj["no_commit"],
                )
        except studies_mod.StudyError as exc:
            err_console.print(f"[red]error:[/] {exc}")
            raise typer.Exit(EXIT_USAGE) from None
        except LockTimeoutError as exc:
            _lock_busy(exc)
        _warn_lock_reclaimed(recorded_decision.lock_reclaimed_from)
        if ctx.obj["json"]:
            _print_json({"event": recorded_decision.event["id"], **recorded_decision.event["body"]})
        else:
            out_console.print(f"[green]recorded[/] {recorded_decision.summary}")
        return

    current = studies_mod.study_map(repo, reports=included)
    found = studies_mod.suggestions(repo)
    header = f"{len(included)} included reports -> {len(current.members)} studies"
    if ctx.obj["json"] or list_only:
        if ctx.obj["json"]:
            _print_json(
                {
                    "reports": len(included),
                    "studies": len(current.members),
                    "groupings": [
                        {"reports": list(g.reports), "evidence": list(g.evidence)}
                        for g in found.groupings
                    ],
                    "splits": [
                        {"report": s.report, "parts": s.parts, "evidence": s.evidence}
                        for s in found.splits
                    ],
                }
            )
        else:
            out_console.print(header)
            for g in found.groupings:
                out_console.print(f"  suggested grouping: {' + '.join(g.reports)}")
                for line in g.evidence:
                    out_console.print(f"    {line}")
            for s in found.splits:
                out_console.print(f"  suggested split: {s.report} into {s.parts} ({s.evidence})")
        return

    if not by:
        err_console.print("[red]error:[/] --by is required to work the suggestions interactively")
        raise typer.Exit(EXIT_USAGE)
    if found.groupings or found.splits:
        # Grouping and splitting need a rationale whatever `git.require_rationale` says
        # (`--group`/`--split` above), and which a session will do is not known up front.
        _preflight_rationale(ctx, repo, always=True)
    out_console.print(f"\n  {header}\n")
    decided = 0
    for g in found.groupings:
        out_console.print("  Suggested grouping (shared trial registration, sample, or authors):")
        for report in g.reports:
            out_console.print(f"    {report}  {records_mod.short_citation(record_of(report))}")
        for line in g.evidence:
            out_console.print(f"      {line}")
        while True:
            choice = typer.prompt("[g] group  [k] keep separate  [?] show both  [s] skip  [q] quit")
            choice = choice.strip().lower()
            if choice == "?":
                for report in g.reports:
                    out_console.print(_render_study_record(report, record_of(report)))
                continue
            break
        if choice == "q":
            break
        if choice == "g":
            rationale = _get_required_rationale(ctx, repo, f"You are grouping {len(g.reports)}.")
            studies_mod.group_reports(repo, reports=list(g.reports), actor=by, rationale=rationale)
            decided += 1
        elif choice == "k":
            studies_mod.dismiss_suggestion(
                repo, reports=list(g.reports), actor=by, kind="keep-separate"
            )
            decided += 1
    else:
        for s in found.splits:
            out_console.print(f"  Suggested split: {s.report} reports {s.parts} studies")
            out_console.print(
                f"    {records_mod.short_citation(record_of(s.report))}: {s.evidence!r}"
            )
            choice = typer.prompt("[s] split  [k] keep as one  [?] skip  [q] quit").strip().lower()
            if choice == "q":
                break
            if choice == "s":
                rationale = _get_required_rationale(ctx, repo, f"You are splitting {s.report}.")
                studies_mod.split_report(
                    repo, report=s.report, parts=s.parts, actor=by, rationale=rationale
                )
                decided += 1
            elif choice == "k":
                studies_mod.dismiss_suggestion(
                    repo, reports=[s.report], actor=by, kind="keep-as-one"
                )
                decided += 1

    if decided:
        _commit_domain_op(
            ctx, repo, op="studies", scope=None, summary=f"{decided} study decision(s)", by=by
        )
    out_console.print(f"[green]done[/] -- {decided} decision(s) recorded")


@export_app.command("effects")
def export_effects_command(
    ctx: typer.Context,
    fmt: str = typer.Option("csv", "--format", help="csv | tsv | xlsx | rds | json"),
    out: str | None = typer.Option(None, "--out", help="Write here instead of standard output"),
) -> None:
    """One row per effect, with study-level and effect-level moderators joined, for outside
    analysis: openspec:data-extraction#exporting-effects-for-outside-analysis.

    The columns include `study_id`, `effect_id`, `yi` and `vi`, so the CSV loads straight into
    `metafor::rma(yi, vi, data = read.csv("effects.csv"))`. xlsx and rds are binary and need --out.

    Example: strata export effects --format csv --out effects.csv
    """
    repo = _resolve_repo(ctx)
    if fmt not in export_mod.FORMATS:
        err_console.print(f"[red]error:[/] --format must be one of {', '.join(export_mod.FORMATS)}")
        raise typer.Exit(EXIT_USAGE)
    if fmt in ("xlsx", "rds") and not out:
        err_console.print(f"[red]error:[/] --format {fmt} is binary; give --out FILE")
        raise typer.Exit(EXIT_USAGE)
    try:
        table = export_mod.effect_table(repo, extras=_export_extras(repo))
        payload = export_mod.render(table, fmt)
    except (export_mod.ExportError, extraction_schema_mod.ExtractionSchemaError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    if out:
        Path(out).write_bytes(payload)
        message = f"wrote {len(table.rows)} effect(s) to {out}"
        if ctx.obj["json"]:
            _print_json({"effects": len(table.rows), "columns": table.columns, "path": out})
        else:
            out_console.print(f"[green]{message}[/]")
    else:
        sys.stdout.write(payload.decode("utf-8"))


@export_app.command("bibliography")
def export_bibliography_command(
    ctx: typer.Context,
    fmt: str = typer.Option("csl", "--format", help="bibtex | csl | ris"),
    set_name: str = typer.Option(
        "included", "--set", help="included | excluded-at-fulltext | all-screened | not-retrieved"
    ),
    out: str | None = typer.Option(None, "--out", help="Write here instead of standard output"),
) -> None:
    """A bibliography of one set of records: openspec:manuscript-generation#bibliography-export.

    CSL-JSON feeds pandoc directly (`pandoc --citeproc --bibliography=included.json`); the
    `excluded-at-fulltext` set is the appendix of studies excluded at full-text screening.

    Example: strata export bibliography --format ris --set excluded-at-fulltext --out excluded.ris
    """
    repo = _resolve_repo(ctx)
    try:
        text = bibliography_mod.render(repo, fmt=fmt, set_name=set_name)
    except bibliography_mod.BibliographyError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    count = len(bibliography_mod.record_ids(repo, set_name))
    if out:
        Path(out).write_text(text, encoding="utf-8", newline="\n")
        if ctx.obj["json"]:
            _print_json({"records": count, "set": set_name, "format": fmt, "path": out})
        else:
            out_console.print(f"[green]wrote {count} record(s) to {out}[/]")
    else:
        sys.stdout.write(text)


@export_app.command("package")
def export_package_command(
    ctx: typer.Context,
    out: str = typer.Option(..., "--out", help="The archive to write (a .zip)"),
) -> None:
    """The reproducibility package for PRISMA item 27: search strategies, criteria and their
    history, the decision log, extraction data, analysis specifications and results, the data
    licence, and a README naming the commit. It contains no full texts.

    Example: strata export package --out supplement.zip
    """
    repo = _resolve_repo(ctx)
    try:
        payload = package_mod.build(repo)
    except package_mod.PackageError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    Path(out).write_bytes(payload)
    count = len(package_mod.members(repo)) + 2
    if ctx.obj["json"]:
        _print_json({"path": out, "files": count})
    else:
        out_console.print(f"[green]wrote {count} file(s) to {out}[/]")


@export_app.command("provenance")
def export_provenance_command(
    ctx: typer.Context,
    fmt: str = typer.Option("csv", "--format", help="csv | tsv | xlsx | rds | json"),
    out: str | None = typer.Option(None, "--out", help="Write here instead of standard output"),
) -> None:
    """Every extracted value with its study and source locator, one row each: the provenance table
    of openspec:data-extraction#extraction-records-and-source-locators.

    Example: strata export provenance --format tsv --out provenance.tsv
    """
    repo = _resolve_repo(ctx)
    if fmt not in export_mod.FORMATS:
        err_console.print(f"[red]error:[/] --format must be one of {', '.join(export_mod.FORMATS)}")
        raise typer.Exit(EXIT_USAGE)
    if fmt in ("xlsx", "rds") and not out:
        err_console.print(f"[red]error:[/] --format {fmt} is binary; give --out FILE")
        raise typer.Exit(EXIT_USAGE)
    try:
        table = export_mod.provenance_table(repo)
        payload = export_mod.render(table, fmt)
    except (export_mod.ExportError, extraction_schema_mod.ExtractionSchemaError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    if out:
        Path(out).write_bytes(payload)
        out_console.print(f"[green]wrote {len(table.rows)} value(s) to {out}[/]")
    else:
        sys.stdout.write(payload.decode("utf-8"))


def _export_extras(repo: Repo) -> export_mod.Extras | None:
    """Further study-level columns for the export: the risk-of-bias moderators, once assessed."""
    found = rob_mod.moderators(repo)
    if not found:
        return None
    return lambda study: dict(found.get(study, {}))


# --- extraction and risk of bias -------------------------------------------------------------

_SET_OPTION = typer.Option(None, "--set", help="NAME=VALUE ('value @ source' ok); repeatable")
_EFFECT_OPTION = typer.Option(None, "--effect", help="An effect as a JSON object; repeatable")
_ANSWER_OPTION = typer.Option(None, "--answer", help="QUESTION=ANSWER, e.g. 1.2=Y; repeatable")
_ACK_OPTION = typer.Option(None, "--ack", help="CODE=EFFECT_KEY: accept a data-quality warning")
_QUIT = ":q"


def _resolve_study(repo: Repo, text: str) -> str:
    """An included study named by its id or any unambiguous prefix of it."""
    members = studies_mod.study_map(repo).members
    if text in members:
        return text
    matches = sorted(s for s in members if s.startswith(text))
    if len(matches) == 1:
        return matches[0]
    if matches:
        err_console.print(f"[red]error:[/] {text!r} matches {len(matches)} studies")
    else:
        err_console.print(f"[red]error:[/] no included study {text!r}")
    raise typer.Exit(EXIT_USAGE)


def _study_heading(repo: Repo, study: str, records: dict[str, dict[str, Any]]) -> str:
    reports = studies_mod.study_map(repo).members.get(study, ())
    first = records.get(ids_mod.record_id_for_report(reports[0]), {}) if reports else {}
    more = f" (+{len(reports) - 1} more report(s))" if len(reports) > 1 else ""
    return f"{study}  {records_mod.short_citation(first)}{more}\n  {first.get('title') or ''}"


def _need_by(by: str | None) -> str:
    if not by:
        err_console.print("[red]error:[/] --by HANDLE is required")
        raise typer.Exit(EXIT_USAGE)
    return by


def _entry_text(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return ""
    if entry.get("not_reported"):
        text = "NR"
    else:
        value = entry.get("value")
        text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        if entry.get("unit"):
            text += f" {entry['unit']}"
        if entry.get("entered") and entry["entered"] != text:
            text += f" (entered {entry['entered']})"
    return f"{text} @ {entry['source']}" if entry.get("source") else text


def _effect_line(result: Any) -> str:
    computed = result.computed
    if computed is None:
        return "  effect size: (waiting for more inputs)"
    se = computed.vi**0.5
    return f"  effect size: {computed.measure} = {computed.yi:.3f}  (SE {se:.3f})"


def _show_warnings(result: Any) -> None:
    for warning in result.warnings:
        out_console.print(f"  [yellow]warning ({warning.code}):[/] {warning.message}")


def _extract_init(ctx: typer.Context, repo: Repo, by: str | None, overwrite: bool) -> None:
    _preflight_rationale(ctx, repo)
    try:
        schema = extraction_schema_mod.init_schema(repo, overwrite=overwrite)
    except extraction_schema_mod.ExtractionSchemaError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    names = [f["name"] for f in schema.fields]
    _commit_domain_op(
        ctx,
        repo,
        op="extract-init",
        scope=None,
        summary="drafted the coding form",
        by=by or "strata",
    )
    if ctx.obj["json"]:
        _print_json(
            {"path": "extraction/schema.yaml", "fields": names, "outcomes": schema.outcomes}
        )
    else:
        out_console.print(f"[green]created[/] extraction/schema.yaml with {len(names)} field(s):")
        out_console.print("  " + ", ".join(names))
        out_console.print("Edit it (and raise its version) to add fields; then run strata extract.")


def _extract_queue(
    ctx: typer.Context, repo: Repo, by: str | None, target: str | None, missing: bool
) -> list[str]:
    try:
        gaps = extraction_records_mod.studies_missing(repo, by)
    except extraction_schema_mod.ExtractionSchemaError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    if target:
        return [_resolve_study(repo, target)]
    if missing:
        return list(gaps)
    return sorted(studies_mod.study_map(repo).members)


def _extract_listing(ctx: typer.Context, repo: Repo, by: str | None, queue: list[str]) -> None:
    gaps = extraction_records_mod.studies_missing(repo, by)
    if ctx.obj["json"]:
        _print_json({"studies": [{"study": s, "missing": gaps.get(s, [])} for s in queue]})
        return
    records = records_mod.index_by_id(records_mod.read_records(repo))
    out_console.print(f"{len(queue)} stud{'y' if len(queue) == 1 else 'ies'}")
    for study in queue:
        gap = gaps.get(study, [])
        out_console.print(f"  {_study_heading(repo, study, records).splitlines()[0]}")
        out_console.print(f"    {'missing: ' + ', '.join(gap) if gap else 'complete'}")


def _extract_script(
    ctx: typer.Context,
    repo: Repo,
    *,
    study: str,
    by: str,
    set_values: list[str],
    effects: list[str],
    ack: list[str],
    note: str | None,
) -> None:
    """Scriptable entry: `--set NAME=VALUE`, `--effect JSON`, `--ack CODE=EFFECT_KEY --note`."""
    _preflight_rationale(ctx, repo)
    done: dict[str, Any] = {"study": study, "fields": [], "effects": [], "acknowledged": []}
    try:
        for assignment in set_values:
            name, sep, raw = assignment.partition("=")
            if not sep:
                raise extraction_records_mod.ExtractionError(
                    f"--set needs NAME=VALUE: {assignment!r}"
                )
            extraction_records_mod.set_field(
                repo, study=study, handle=by, name=name.strip(), raw=raw
            )
            done["fields"].append(name.strip())
        for text in effects:
            try:
                spec = json_mod.loads(text)
            except json_mod.JSONDecodeError as exc:
                raise extraction_records_mod.ExtractionError(
                    f"--effect is not JSON: {exc}"
                ) from None
            if not isinstance(spec, dict) or "design" not in spec or "outcome" not in spec:
                raise extraction_records_mod.ExtractionError(
                    "--effect needs a JSON object with at least outcome and design"
                )
            reserved = ("outcome", "design", "timepoint", "label", "source", "moderators")
            result = extraction_records_mod.add_effect(
                repo,
                study=study,
                handle=by,
                outcome=spec["outcome"],
                design=spec["design"],
                timepoint=spec.get("timepoint"),
                label=spec.get("label"),
                source=spec.get("source"),
                moderators=spec.get("moderators"),
                inputs={k: v for k, v in spec.items() if k not in reserved},
            )
            done["effects"].append(
                {
                    "key": extraction_records_mod.effect_key(result.effect),
                    "yi": result.computed.yi if result.computed else None,
                    "vi": result.computed.vi if result.computed else None,
                    "warnings": [{"code": w.code, "message": w.message} for w in result.warnings],
                }
            )
        for pair in ack:
            code, sep, key = pair.partition("=")
            if not sep:
                raise extraction_records_mod.ExtractionError(
                    f"--ack needs CODE=EFFECT_KEY: {pair!r}"
                )
            extraction_records_mod.acknowledge_warning(
                repo, study=study, effect=key, code=code, note=note or "", actor=by
            )
            done["acknowledged"].append({"code": code, "effect": key})
    except (ValueError, KeyError) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    _commit_domain_op(ctx, repo, op="extract", scope=study, summary="extracted data", by=by)
    if ctx.obj["json"]:
        _print_json(done)
        return
    for item in done["effects"]:
        out_console.print(f"effect {item['key']}: yi={item['yi']} vi={item['vi']}")
        for warning in item["warnings"]:
            out_console.print(f"  [yellow]warning ({warning['code']}):[/] {warning['message']}")
    out_console.print(
        f"[green]recorded[/] {len(done['fields'])} field(s), {len(done['effects'])} effect(s)"
    )


def _prompt_field(repo: Repo, study: str, by: str, spec: dict[str, Any]) -> str:
    """One field: returns 'saved', 'skipped' or 'quit'."""
    path = extraction_records_mod.working_path(repo, by, study)
    current = (extraction_records_mod.read_record(path) or {}).get("fields", {}).get(spec["name"])
    unit = f" in {spec['unit']}" if spec.get("unit") else ""
    levels = f" [{'/'.join(spec['levels'])}]" if spec.get("levels") else ""
    required = " *" if spec.get("required") else ""
    hint = f"  help: {spec['help']}" if spec.get("help") else ""
    if hint:
        out_console.print(hint)
    while True:
        shown = f" [now: {_entry_text(current)}]" if current else ""
        raw = typer.prompt(
            f"{spec.get('label') or spec['name']}{required} ({spec['type']}{unit}){levels}{shown}",
            default="",
            show_default=False,
        ).strip()
        if raw == _QUIT:
            return "quit"
        if not raw:
            return "skipped"
        try:
            entry = extraction_records_mod.set_field(
                repo, study=study, handle=by, name=spec["name"], raw=raw
            )
        except ValueError as exc:
            out_console.print(f"  [red]{exc}[/]")
            continue
        out_console.print(f"  stored: {_entry_text(entry)}")
        return "saved"


def _prompt_effect(repo: Repo, study: str, by: str) -> bool:
    """Walk through one effect with the size shown as the inputs are entered. True if saved."""
    schema = extraction_schema_mod.load_schema(repo)
    designs = schema.designs
    design = typer.prompt(
        f"Add an effect? design ({', '.join(designs)}; blank to finish)",
        default="",
        show_default=False,
    ).strip()
    if not design:
        return False
    if design not in designs:
        out_console.print(f"  [red]unknown design {design!r}[/]")
        return True
    outcome = (
        typer.prompt(f"Outcome ({', '.join(schema.outcomes)})", default=schema.outcomes[0]).strip()
        if schema.outcomes
        else typer.prompt("Outcome").strip()
    )
    timepoint = typer.prompt("Timepoint", default="", show_default=False).strip() or None
    label = typer.prompt("Label", default="", show_default=False).strip() or None
    inputs: dict[str, Any] = {}
    for name in designs[design]:
        raw = typer.prompt(f"  {name}", default="", show_default=False).strip()
        if raw:
            inputs[name] = raw
        preview = extraction_records_mod.preview_effect(
            repo, study=study, design=design, inputs=inputs, outcome=outcome
        )
        out_console.print(_effect_line(preview))
    source = typer.prompt("Source (page, table)", default="", show_default=False).strip() or None
    try:
        result = extraction_records_mod.add_effect(
            repo,
            study=study,
            handle=by,
            outcome=outcome,
            design=design,
            inputs=inputs,
            timepoint=timepoint,
            label=label,
            source=source,
        )
    except ValueError as exc:
        out_console.print(f"  [red]{exc}[/]")
        return True
    out_console.print(_effect_line(result).replace("effect size", "saved effect"))
    _show_warnings(result)
    key = extraction_records_mod.effect_key(result.effect)
    for warning in result.warnings:
        why = typer.prompt(
            f"  Acknowledge {warning.code}? note (blank to leave it open)",
            default="",
            show_default=False,
        ).strip()
        if why:
            extraction_records_mod.acknowledge_warning(
                repo, study=study, effect=key, code=warning.code, note=why, actor=by
            )
    return True


def _extract_interactive(
    ctx: typer.Context, repo: Repo, by: str, queue: list[str], *, only_missing: bool
) -> None:
    _preflight_rationale(ctx, repo)
    records = records_mod.index_by_id(records_mod.read_records(repo))
    schema = extraction_schema_mod.load_schema(repo)
    touched = 0
    for index, study in enumerate(queue, start=1):
        out_console.print(f"\n[{index}/{len(queue)}] {_study_heading(repo, study, records)}")
        path = extraction_records_mod.working_path(repo, by, study)
        have = (extraction_records_mod.read_record(path) or {}).get("fields", {})
        quit_now = False
        for spec in schema.fields:
            if only_missing and spec["name"] in have:
                continue
            outcome = _prompt_field(repo, study, by, spec)
            if outcome == "quit":
                quit_now = True
                break
            touched += outcome == "saved"
        if not quit_now:
            while _prompt_effect(repo, study, by):
                touched += 1
        if quit_now:
            break
    if touched:
        _commit_domain_op(
            ctx,
            repo,
            op="extract",
            scope=None,
            summary=f"extracted data ({touched} entries)",
            by=by,
        )
    out_console.print(f"[green]done[/] -- {touched} entr{'y' if touched == 1 else 'ies'} saved")


def _reconcile_targets(repo: Repo, target: str | None) -> list[str]:
    if target:
        return [_resolve_study(repo, target)]
    return [c.study for c in reconcile_mod.all_comparisons(repo) if c.unresolved]


def _extract_reconcile(
    ctx: typer.Context,
    repo: Repo,
    *,
    by: str | None,
    target: str | None,
    list_only: bool,
    item: str | None,
    choose: str | None,
    value: str | None,
    rationale: str | None,
    source: str | None,
) -> None:
    try:
        studies = _reconcile_targets(repo, target)
        if item is not None or choose is not None:
            if not (item and choose and len(studies) == 1):
                err_console.print(
                    "[red]error:[/] --item and --choose need one study and each other"
                )
                raise typer.Exit(EXIT_USAGE)
            _preflight_rationale(ctx, repo)
            event = reconcile_mod.resolve(
                repo,
                study=studies[0],
                reconciler=_need_by(by),
                item_id=item,
                choice=choose,
                rationale=rationale or "",
                other_value=value,
                source=source,
            )
            _commit_domain_op(
                ctx,
                repo,
                op="reconcile",
                scope=studies[0],
                summary=f"reconciled {item}",
                by=by or "",
            )
            if ctx.obj["json"]:
                _print_json({"event": event["id"], "item": item, "choice": choose})
            else:
                out_console.print(f"[green]reconciled[/] {item}: {choose}")
            return
        comparisons = [reconcile_mod.compare(repo, s) for s in studies]
    except reconcile_mod.ReconcileError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    rate = reconcile_mod.agreement_rate(comparisons)
    if list_only or ctx.obj["json"]:
        payload = {
            "agreement": rate,
            "studies": [
                {
                    "study": c.study,
                    "reviewers": c.handles,
                    "items": [
                        {
                            "id": i.id,
                            "label": i.label,
                            "agree": i.agree,
                            "resolved": i.resolved,
                            "values": i.candidates,
                            "sources": i.sources,
                        }
                        for i in c.items
                    ],
                }
                for c in comparisons
            ],
        }
        if ctx.obj["json"]:
            _print_json(payload)
        else:
            out_console.print(
                f"{rate['agreed']} of {rate['compared']} items agree ({rate['rate']:.0%})"
            )
            for c in comparisons:
                for i in c.disagreements:
                    shown = "  |  ".join(f"{h}: {i.candidates[h]}" for h in c.handles)
                    out_console.print(f"  {c.study} {i.id}: {shown}")
        return

    reconciler = _need_by(by)
    if comparisons:
        _preflight_rationale(ctx, repo)
    records = records_mod.index_by_id(records_mod.read_records(repo))
    resolved = 0
    quit_all = False
    for comparison in comparisons:
        out_console.print(f"\n{_study_heading(repo, comparison.study, records)}")
        agreed = [i for i in comparison.items if i.agree and not i.resolved]
        if agreed:
            out_console.print(f"  {len(agreed)} item(s) the reviewers agree on")
            if typer.confirm("  Accept them all?", default=True):
                resolved += reconcile_mod.accept_agreements(
                    repo, study=comparison.study, reconciler=reconciler
                )
        for current in comparison.disagreements:
            if current.resolved:
                continue
            out_console.print(f"  {current.id}  {current.label}")
            for handle in comparison.handles:
                src = f" @ {current.sources[handle]}" if current.sources.get(handle) else ""
                out_console.print(f"    {handle}: {current.candidates[handle]}{src}")
            options = [*comparison.handles, "other", "skip", "quit"]
            choice = ""
            while True:
                choice = typer.prompt(f"  Choose ({'/'.join(options)})", default="skip").strip()
                if choice == "quit":
                    break
                if choice == "skip":
                    break
                value_text = None
                if choice == "other":
                    value_text = typer.prompt("  Value (optionally 'value @ source')").strip()
                why = typer.prompt("  Rationale").strip()
                try:
                    reconcile_mod.resolve(
                        repo,
                        study=comparison.study,
                        reconciler=reconciler,
                        item_id=current.id,
                        choice=choice,
                        rationale=why,
                        other_value=value_text,
                    )
                except reconcile_mod.ReconcileError as exc:
                    out_console.print(f"  [red]{exc}[/]")
                    continue
                resolved += 1
                break
            if choice == "quit":
                quit_all = True
                break
        if quit_all:
            break
    if resolved:
        _commit_domain_op(
            ctx,
            repo,
            op="reconcile",
            scope=None,
            summary=f"reconciled {resolved} item(s)",
            by=reconciler,
        )
    out_console.print(f"[green]done[/] -- {resolved} item(s) reconciled")


@app.command("extract")
def extract_command(
    ctx: typer.Context,
    target: str | None = typer.Argument(None, help="`init`, or a study id (a prefix will do)"),
    by: str | None = typer.Option(None, "--by", help="Actor handle extracting"),
    missing: bool = typer.Option(
        False, "--missing", help="Only studies with missing required values"
    ),
    reconcile: bool = typer.Option(False, "--reconcile", help="Reconcile dual extractions"),
    list_only: bool = typer.Option(False, "--list", help="List the queue and exit"),
    overwrite: bool = typer.Option(False, "--overwrite", help="With init: replace the coding form"),
    set_values: list[str] | None = _SET_OPTION,
    effects: list[str] | None = _EFFECT_OPTION,
    ack: list[str] | None = _ACK_OPTION,
    note: str | None = typer.Option(
        None, "--note", help="With --ack: why the warning is acceptable"
    ),
    item: str | None = typer.Option(None, "--item", help="With --reconcile: the item to settle"),
    choose: str | None = typer.Option(
        None, "--choose", help="A reviewer's handle, agreement, other"
    ),
    value: str | None = typer.Option(None, "--value", help="With --choose other: the value"),
    rationale: str | None = typer.Option(None, "--rationale", help="Why this choice"),
    source: str | None = typer.Option(None, "--source", help="Source locator for the chosen value"),
) -> None:
    """Extract data from included studies: openspec:data-extraction.

    `strata extract init` drafts the coding form from the protocol's moderators and outcomes.
    `strata extract` walks the studies (`--missing`: only those lacking required values; `NR` means
    not reported; add '@ p.4' after a value for its source). With dual extraction each reviewer
    works into their own files and `--reconcile` settles the differences.

    Example: strata extract std_3kq8v1r0zx2m4a7b --by ethan --set "n_total=120 @ Table 1" \\
        --effect '{"outcome": "memory", "design": "two-group-means", "n1": 20, "m1": 5.1, ...}'
    """
    repo = _resolve_repo(ctx)
    if target == "init":
        _extract_init(ctx, repo, by, overwrite)
        return
    if reconcile:
        _extract_reconcile(
            ctx,
            repo,
            by=by,
            target=target,
            list_only=list_only,
            item=item,
            choose=choose,
            value=value,
            rationale=rationale,
            source=source,
        )
        return
    queue = _extract_queue(ctx, repo, by, target, missing)
    if set_values or effects or ack:
        if len(queue) != 1 or target is None:
            err_console.print("[red]error:[/] --set, --effect and --ack need one study")
            raise typer.Exit(EXIT_USAGE)
        _extract_script(
            ctx,
            repo,
            study=queue[0],
            by=_need_by(by),
            set_values=set_values or [],
            effects=effects or [],
            ack=ack or [],
            note=note,
        )
        return
    if list_only or ctx.obj["json"]:
        _extract_listing(ctx, repo, by, queue)
        return
    if not queue:
        out_console.print("nothing to extract")
        return
    _extract_interactive(ctx, repo, _need_by(by), queue, only_missing=missing)


def _rob_domain_listing(repo: Repo, by: str | None, study: str) -> dict[str, Any]:
    instrument = rob_mod.load_instrument(repo)
    path = rob_mod.working_path(repo, by or "", study)
    assessment = rob_mod.read_assessment(path) or {}
    domains = []
    for domain in instrument.domains:
        state = rob_mod.domain_state(instrument, assessment, domain["id"])
        domains.append(
            {
                "domain": domain["id"],
                "label": domain["label"],
                "answers": state.answers,
                "suggested": state.suggested,
                "judgement": state.judgement,
            }
        )
    overall = assessment.get("overall") or {}
    return {
        "study": study,
        "instrument": instrument.name,
        "domains": domains,
        "overall": overall.get("judgement"),
        "suggested_overall": rob_mod.overall_suggestion(instrument, assessment),
    }


def _rob_prompt_domain(repo: Repo, study: str, by: str, domain: dict[str, Any]) -> bool:
    """Walk one domain: the signalling questions the algorithm needs, then the judgement."""
    instrument = rob_mod.load_instrument(repo)
    questions = {q["id"]: q for q in domain.get("signalling_questions", [])}
    path = rob_mod.working_path(repo, by, study)
    state = rob_mod.domain_state(instrument, rob_mod.read_assessment(path), domain["id"])
    out_console.print(f"\n  Domain {domain['id']}: {domain['label']}")
    if domain.get("algorithm"):
        while state.needed is not None:
            q = questions[state.needed]
            answer = typer.prompt(
                f"    {q['id']} {q['topic']} ({'/'.join(q['options'])})", default=""
            ).strip()
            if answer == _QUIT:
                return False
            if not answer:
                break
            try:
                state = rob_mod.answer_question(
                    repo,
                    study=study,
                    handle=by,
                    domain=domain["id"],
                    question=q["id"],
                    answer=answer,
                )
            except rob_mod.RobError as exc:
                out_console.print(f"    [red]{exc}[/]")
    elif questions:
        for q in questions.values():
            answer = typer.prompt(
                f"    {q['id']} {q['topic']} ({'/'.join(q['options'])})", default=""
            ).strip()
            if answer == _QUIT:
                return False
            if answer:
                try:
                    rob_mod.answer_question(
                        repo,
                        study=study,
                        handle=by,
                        domain=domain["id"],
                        question=q["id"],
                        answer=answer,
                    )
                except rob_mod.RobError as exc:
                    out_console.print(f"    [red]{exc}[/]")
    if state.suggested:
        out_console.print(f"    the algorithm suggests: {state.suggested}")
    return _rob_prompt_judgement(
        repo, study, by, domain["id"], domain["judgements"], state.suggested
    )


def _rob_prompt_judgement(
    repo: Repo, study: str, by: str, domain: str, choices: list[str] | None, suggested: str | None
) -> bool:
    options = f" ({'/'.join(choices)})" if choices else ""
    while True:
        judgement = typer.prompt(
            f"    Judgement{options}", default=suggested or "", show_default=bool(suggested)
        ).strip()
        if judgement == _QUIT:
            return False
        if not judgement:
            return True
        justification = None
        if suggested and judgement != suggested:
            justification = typer.prompt("    Why override the suggestion?").strip()
        support = typer.prompt(
            "    Support (quote or note)", default="", show_default=False
        ).strip()
        source = typer.prompt("    Source (page, section)", default="", show_default=False).strip()
        try:
            rob_mod.record_judgement(
                repo,
                study=study,
                handle=by,
                domain=domain,
                judgement=judgement,
                support=support,
                source=source or None,
                override_justification=justification,
            )
        except rob_mod.RobError as exc:
            out_console.print(f"    [red]{exc}[/]")
            continue
        return True


def _rob_script(
    ctx: typer.Context,
    repo: Repo,
    *,
    study: str,
    by: str,
    domain: str,
    answers: list[str],
    judgement: str | None,
    support: str,
    source: str | None,
    justification: str | None,
) -> None:
    _preflight_rationale(ctx, repo)
    done: dict[str, Any] = {"study": study, "domain": domain, "answers": {}}
    try:
        state = None
        for pair in answers:
            question, sep, answer = pair.partition("=")
            if not sep:
                raise rob_mod.RobError(f"--answer needs QUESTION=ANSWER: {pair!r}")
            state = rob_mod.answer_question(
                repo,
                study=study,
                handle=by,
                domain=domain,
                question=question.strip(),
                answer=answer.strip(),
            )
            done["answers"][question.strip()] = answer.strip()
        if state is not None:
            done["suggested"] = state.suggested
            done["needed"] = state.needed
        if judgement is not None:
            event = rob_mod.record_judgement(
                repo,
                study=study,
                handle=by,
                domain=domain,
                judgement=judgement,
                support=support,
                source=source,
                override_justification=justification,
            )
            done["event"] = event["id"]
            done["judgement"] = judgement
            done["suggested"] = event["body"].get("suggested")
    except rob_mod.RobError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    _commit_domain_op(ctx, repo, op="rob", scope=study, summary=f"assessed {domain}", by=by)
    if ctx.obj["json"]:
        _print_json(done)
        return
    if done.get("suggested"):
        out_console.print(f"the algorithm suggests: {done['suggested']}")
    if done.get("needed"):
        out_console.print(f"next signalling question: {done['needed']}")
    if judgement is not None:
        out_console.print(f"[green]recorded[/] {domain}: {judgement}")


def _rob_reconcile(
    ctx: typer.Context,
    repo: Repo,
    *,
    by: str | None,
    target: str | None,
    list_only: bool,
    domain: str | None,
    choose: str | None,
    value: str | None,
    rationale: str | None,
) -> None:
    try:
        studies = (
            [_resolve_study(repo, target)]
            if target
            else [
                s
                for s in sorted(studies_mod.study_map(repo).members)
                if len(rob_mod.reviewer_handles(repo, s)) >= 2
            ]
        )
        if domain is not None or choose is not None:
            if not (domain and choose and len(studies) == 1):
                err_console.print(
                    "[red]error:[/] --domain and --choose need one study and each other"
                )
                raise typer.Exit(EXIT_USAGE)
            _preflight_rationale(ctx, repo)
            event = rob_mod.resolve(
                repo,
                study=studies[0],
                reconciler=_need_by(by),
                domain=domain,
                choice=choose,
                rationale=rationale or "",
                other_judgement=value,
            )
            _commit_domain_op(
                ctx,
                repo,
                op="rob-reconcile",
                scope=studies[0],
                summary=f"reconciled {domain}",
                by=by or "",
            )
            if ctx.obj["json"]:
                _print_json({"event": event["id"], "domain": domain, "choice": choose})
            else:
                out_console.print(f"[green]reconciled[/] {domain}: {choose}")
            return
        comparisons = {s: rob_mod.compare(repo, s) for s in studies}
    except rob_mod.RobError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    if list_only or ctx.obj["json"]:
        payload = [
            {
                "study": s,
                "items": [
                    {
                        "domain": i.domain,
                        "agree": i.agree,
                        "resolved": i.resolved,
                        "values": i.candidates,
                    }
                    for i in items
                ],
            }
            for s, items in comparisons.items()
        ]
        if ctx.obj["json"]:
            _print_json({"studies": payload})
        else:
            for s, items in comparisons.items():
                for i in items:
                    if not i.agree:
                        shown = "  |  ".join(f"{h}: {v}" for h, v in i.candidates.items())
                        out_console.print(f"  {s} {i.domain}: {shown}")
        return

    reconciler = _need_by(by)
    if comparisons:
        _preflight_rationale(ctx, repo)
    resolved = 0
    quit_all = False
    for s, items in comparisons.items():
        out_console.print(f"\n{s}")
        for current in items:
            if current.resolved:
                continue
            shown = "  |  ".join(f"{h}: {v}" for h, v in current.candidates.items())
            out_console.print(f"  {current.domain} ({current.label}): {shown}")
            handles = list(current.candidates)
            choice = "agreement" if current.agree else "skip"
            why = ""
            if current.agree:
                if not typer.confirm("    Both agree. Accept?", default=True):
                    continue
                why = "Both reviewers reached the same judgement."
            else:
                options = [*handles, "other", "skip", "quit"]
                choice = typer.prompt(f"    Choose ({'/'.join(options)})", default="skip").strip()
                if choice == "quit":
                    quit_all = True
                    break
                if choice == "skip":
                    continue
            other = typer.prompt("    Judgement").strip() if choice == "other" else None
            if not current.agree:
                why = typer.prompt("    Rationale").strip()
            try:
                rob_mod.resolve(
                    repo,
                    study=s,
                    reconciler=reconciler,
                    domain=current.domain,
                    choice=choice,
                    rationale=why,
                    other_judgement=other,
                )
            except rob_mod.RobError as exc:
                out_console.print(f"    [red]{exc}[/]")
                continue
            resolved += 1
        if quit_all:
            break
    if resolved:
        _commit_domain_op(
            ctx,
            repo,
            op="rob-reconcile",
            scope=None,
            summary=f"reconciled {resolved} domain(s)",
            by=reconciler,
        )
    out_console.print(f"[green]done[/] -- {resolved} domain(s) reconciled")


@app.command("rob")
def rob_command(
    ctx: typer.Context,
    target: str | None = typer.Argument(None, help="`init`, or a study id (a prefix will do)"),
    by: str | None = typer.Option(None, "--by", help="Actor handle assessing"),
    instrument: str = typer.Option(
        "rob2", "--instrument", help="With init: " + ", ".join(rob_mod.BUILTIN_IDS)
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="With init: replace the instrument"),
    list_only: bool = typer.Option(False, "--list", help="Show the assessments and exit"),
    reconcile: bool = typer.Option(False, "--reconcile", help="Reconcile dual assessments"),
    domain: str | None = typer.Option(None, "--domain", help="A domain id, or overall"),
    answers: list[str] | None = _ANSWER_OPTION,
    judgement: str | None = typer.Option(None, "--judgement", help="The judgement for --domain"),
    support: str = typer.Option("", "--support", help="Supporting quote or note"),
    source: str | None = typer.Option(None, "--source", help="Source locator (page, section)"),
    justification: str | None = typer.Option(
        None, "--override-justification", help="Why this differs from the suggestion"
    ),
    choose: str | None = typer.Option(
        None, "--choose", help="With --reconcile: a reviewer's handle, agreement, other"
    ),
    value: str | None = typer.Option(None, "--value", help="With --choose other: the judgement"),
    rationale: str | None = typer.Option(None, "--rationale", help="Why this choice"),
) -> None:
    """Risk-of-bias assessment: openspec:risk-of-bias.

    `strata rob init --instrument rob2|rob2-adhering|robins-i|nos-cohort|nos-case-control` copies
    a built-in instrument into rob/instrument.yaml. `strata rob <study>` walks the domains: the
    signalling questions the RoB 2 algorithm needs, its suggested judgement, and your judgement
    (an override of the suggestion needs a justification).

    Example: strata rob std_3kq8v1r0zx2m4a7b --by ethan --domain D1 --answer 1.1=Y \\
        --answer 1.2=Y --answer 1.3=N --judgement low --support "Central randomisation"
    """
    repo = _resolve_repo(ctx)
    try:
        if target == "init":
            _preflight_rationale(ctx, repo)
            built = rob_mod.init_instrument(repo, instrument, overwrite=overwrite)
            _commit_domain_op(
                ctx,
                repo,
                op="rob-init",
                scope=None,
                summary=f"set up {built.name}",
                by=by or "strata",
            )
            if ctx.obj["json"]:
                _print_json({"instrument": built.name, "domains": [d["id"] for d in built.domains]})
            else:
                out_console.print(f"[green]created[/] rob/instrument.yaml ({built.name})")
            return
        if reconcile:
            _rob_reconcile(
                ctx,
                repo,
                by=by,
                target=target,
                list_only=list_only,
                domain=domain,
                choose=choose,
                value=value,
                rationale=rationale,
            )
            return
        loaded = rob_mod.load_instrument(repo)
        queue = (
            [_resolve_study(repo, target)]
            if target
            else sorted(studies_mod.study_map(repo).members)
        )
        if domain is not None:
            if len(queue) != 1 or target is None:
                err_console.print("[red]error:[/] --domain needs one study")
                raise typer.Exit(EXIT_USAGE)
            _rob_script(
                ctx,
                repo,
                study=queue[0],
                by=_need_by(by),
                domain=domain,
                answers=answers or [],
                judgement=judgement,
                support=support,
                source=source,
                justification=justification,
            )
            return
        if list_only or ctx.obj["json"]:
            listing = [_rob_domain_listing(repo, by, s) for s in queue]
            if ctx.obj["json"]:
                _print_json({"instrument": loaded.name, "studies": listing})
            else:
                records = records_mod.index_by_id(records_mod.read_records(repo))
                for entry in listing:
                    out_console.print(_study_heading(repo, entry["study"], records).splitlines()[0])
                    judged = {d["domain"]: d["judgement"] or "-" for d in entry["domains"]}
                    out_console.print("    " + "  ".join(f"{k}:{v}" for k, v in judged.items()))
            return
        reviewer = _need_by(by)
        if queue:
            _preflight_rationale(ctx, repo)
        records = records_mod.index_by_id(records_mod.read_records(repo))
        touched = 0
        for index, study in enumerate(queue, start=1):
            out_console.print(f"\n[{index}/{len(queue)}] {_study_heading(repo, study, records)}")
            go_on = True
            for spec in loaded.domains:
                go_on = _rob_prompt_domain(repo, study, reviewer, spec)
                if not go_on:
                    break
                touched += 1
            if go_on:
                assessment = rob_mod.read_assessment(rob_mod.working_path(repo, reviewer, study))
                suggested = rob_mod.overall_suggestion(loaded, assessment)
                out_console.print("\n  Overall")
                if suggested:
                    out_console.print(f"    suggested overall: {suggested}")
                go_on = _rob_prompt_judgement(
                    repo, study, reviewer, "overall", loaded.overall_judgements or None, suggested
                )
            if not go_on:
                break
        if touched:
            _commit_domain_op(
                ctx,
                repo,
                op="rob",
                scope=None,
                summary=f"assessed {touched} domain(s)",
                by=reviewer,
            )
        out_console.print(f"[green]done[/] -- {touched} domain(s) assessed")
    except rob_mod.RobError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None


# --- analysis ------------------------------------------------------------------------------


_ACK_OPTION_ANALYZE = typer.Option(None, "--ack", help="Acknowledge a named warning; repeatable")


def _analysis_targets(repo: Repo, analysis_id: str | None, run_all: bool) -> list[str]:
    available = analysis_mod_spec.list_analyses(repo)
    if run_all:
        return available
    if analysis_id:
        return [analysis_id]
    if len(available) == 1:
        return available
    listing = ", ".join(available) or "none yet (create analysis/<id>.yaml)"
    err_console.print(f"[red]error:[/] name an analysis or use --all; available: {listing}")
    raise typer.Exit(EXIT_USAGE)


def _analysis_summary(outcome: Any) -> dict[str, Any]:
    estimates = outcome.result.estimates
    first = estimates["pooled"]["coefficients"][0]
    return {
        "analysis": outcome.spec.id,
        "label": outcome.spec.label,
        "measure": outcome.spec.measure,
        "k_studies": estimates["k_studies"],
        "k_effects": estimates["k_effects"],
        "estimate": first["estimate"],
        "ci_lb": first["ci_lb"],
        "ci_ub": first["ci_ub"],
        "warnings": outcome.result.warnings,
        "forced_bypasses": outcome.run["forced_bypasses"],
        "files": outcome.written,
    }


@app.command("analyze")
def analyze_command(
    ctx: typer.Context,
    analysis_id: str | None = typer.Argument(None, help="An analysis id (analysis/<id>.yaml)"),
    run_all: bool = typer.Option(False, "--all", help="Run every analysis specification"),
    check: bool = typer.Option(
        False, "--check", help="Validate specifications and report guardrails without computing"
    ),
    force: bool = typer.Option(False, "--force", help="Bypass blocking guardrails (recorded)"),
    ack: list[str] | None = _ACK_OPTION_ANALYZE,
    plot_format: str = typer.Option("svg", "--plot-format", help="svg | pdf | png"),
) -> None:
    """Run analysis specifications and write analysis/results/<id>/.

    See openspec:analysis-specification.

    Results are written, and committed, only when you run this command. `--check` validates the
    specifications and reports guardrails without computing anything. A blocking guardrail exits
    with code 8 unless `--force` is given; the bypass is recorded in run.json.

    Example: strata analyze primary --ack exploratory
    """
    repo = _resolve_repo(ctx)
    targets = _analysis_targets(repo, analysis_id, run_all)
    unknown = sorted(set(ack or []) - set(analysis_guardrails.CODES))
    if unknown:
        err_console.print(
            f"[red]error:[/] unknown warning(s) {', '.join(unknown)}; "
            f"known: {', '.join(analysis_guardrails.CODES)}"
        )
        raise typer.Exit(EXIT_USAGE)
    if not check:
        _preflight_rationale(ctx, repo)
    summaries: list[dict[str, Any]] = []
    try:
        for target in targets:
            if check:
                spec = analysis_mod_spec.load_spec(repo, target)
                selection = analysis_rows.build_rows(repo, spec)
                warnings = analysis_engine.check_analysis(spec, selection, ack or [])
                summaries.append(
                    {
                        "analysis": target,
                        "label": spec.label,
                        "effects": len(selection.rows),
                        "candidates": selection.candidates,
                        "excluded": {k: len(v) for k, v in selection.excluded.items()},
                        "warnings": warnings,
                    }
                )
                continue
            outcome = analysis_run.run_analysis(
                repo, target, force=force, acknowledged=ack or [], plot_format=plot_format
            )
            summaries.append(_analysis_summary(outcome))
    except analysis_guardrails.BlockingGuardrail as exc:
        err_console.print(f"[red]blocked ({exc.code}):[/] {exc.message}")
        raise typer.Exit(EXIT_GUARDRAIL) from None
    except (
        analysis_mod_spec.AnalysisSpecError,
        analysis_engine.AnalysisError,
        analysis_rows.RowError,
        analysis_plots.PlotError,
        models_mod.ModelError,
        robust_mod.DependenceError,
    ) as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None

    if not check and summaries:
        _commit_domain_op(
            ctx,
            repo,
            op="analyze",
            scope=None,
            summary="ran " + ", ".join(s["analysis"] for s in summaries),
            by=_acting_handle(repo),
        )
    if ctx.obj["json"]:
        _print_json({"checked" if check else "ran": summaries})
        return
    for item in summaries:
        if check:
            out_console.print(
                f"{item['analysis']} ({item['label']}): {item['effects']} of "
                f"{item['candidates']} effects selected"
            )
        else:
            out_console.print(
                f"[green]{item['analysis']}[/] ({item['label']}): {item['measure']} "
                f"{item['estimate']:.3f} [{item['ci_lb']:.3f}, {item['ci_ub']:.3f}], "
                f"{item['k_studies']} studies, {item['k_effects']} effects"
            )
        for warning in item["warnings"]:
            if not warning["acknowledged"]:
                out_console.print(f"  [yellow]{warning['code']}[/]: {warning['message']}")
        for bypass in item.get("forced_bypasses", []):
            out_console.print(f"  [yellow]forced:[/] {bypass} (recorded in run.json)")


def _acting_handle(repo: Repo) -> str:
    """The handle recorded as the actor of an analysis run: the first active actor."""
    for actor in repo.config.get("actors", []):
        if actor.get("role") != "inactive":
            return str(actor["handle"])
    return "strata"


@app.command("prisma")
def prisma_command(
    ctx: typer.Context,
    fmt: str = typer.Option("svg", "--format", help="svg | pdf | png | json"),
    columns: str = typer.Option(
        "one", "--columns", help="one | both (other methods in a second column)"
    ),
    allow_stale: bool = typer.Option(
        False, "--allow-stale", help="Render a DRAFT even though decisions are stale"
    ),
    out: str | None = typer.Option(
        None, "--out", help="Write here (`-` for standard output); default reports/prisma.<format>"
    ),
) -> None:
    """The PRISMA 2020 flow diagram, drawn from the event log: openspec:prisma-reporting.

    Every count is derived and every reconciliation identity is asserted first (a broken one is
    E_COUNT_RECONCILE, exit code 4). While any decision is stale the command refuses (exit code 8)
    unless `--allow-stale`; the diagram is then watermarked DRAFT, as it is whenever screening is
    unfinished. The default output, reports/prisma.<format>, is committed.

    Example: strata prisma --columns both --format svg
    """
    repo = _resolve_repo(ctx)
    if fmt not in flow_mod.FORMATS:
        err_console.print(f"[red]error:[/] --format must be one of {', '.join(flow_mod.FORMATS)}")
        raise typer.Exit(EXIT_USAGE)
    if columns not in flow_mod.COLUMNS:
        err_console.print(f"[red]error:[/] --columns must be one of {', '.join(flow_mod.COLUMNS)}")
        raise typer.Exit(EXIT_USAGE)
    if fmt in ("pdf", "png") and out == "-":
        err_console.print(f"[red]error:[/] --format {fmt} is binary; give --out FILE")
        raise typer.Exit(EXIT_USAGE)
    if not out:  # --out writes elsewhere and commits nothing
        _preflight_rationale(ctx, repo)
    counts = counts_mod.compute(repo)
    counts_mod.regenerate_counts_json(repo, counts)
    try:
        counts_mod.require_reconciled(counts)
        flow_mod.require_final(counts, allow_stale=allow_stale)
        names = {str(s["id"]): str(s["database"]) for s in searches_mod.list_searches(repo)}
        if fmt == "json":
            document = flow_mod.flow_json(counts, names, columns=columns)
            payload = (json_mod.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
        else:
            payload = flow_mod.render(counts, fmt=fmt, columns=columns)
    except counts_mod.CountReconcileError as exc:
        err_console.print(f"[red]{exc.code}:[/] the counts do not close: {exc}")
        raise typer.Exit(EXIT_VALIDATION) from None
    except flow_mod.StaleDecisionsError as exc:
        err_console.print(f"[red]refused:[/] {exc}")
        raise typer.Exit(EXIT_GUARDRAIL) from None
    except flow_mod.FlowError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    if out == "-":
        sys.stdout.write(payload.decode("utf-8"))
        return
    target = Path(out) if out else repo.path("reports", f"prisma.{fmt}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    written = [str(target)]
    _, collapsed = flow_mod.collapse_reasons(counts.exclusion_reasons)
    if collapsed and fmt != "json":
        table = target.with_name("prisma-exclusion-reasons.tsv")
        table.write_text(flow_mod.reasons_table(counts), encoding="utf-8", newline="\n")
        written.append(str(table))
    if not out:
        _commit_domain_op(
            ctx, repo, op="prisma", scope=None, summary=f"drew the PRISMA flow diagram ({fmt})",
            by=_acting_handle(repo),
        )  # fmt: skip
    draft = not counts.complete
    if ctx.obj["json"]:
        _print_json({"written": written, "draft": draft, "counts": counts.to_dict()["totals"]})
        return
    out_console.print(f"[green]wrote[/] {', '.join(written)}")
    if draft:
        out_console.print(
            f"[yellow]{flow_mod.DRAFT_TEXT}[/]: the diagram is watermarked as a draft"
        )


_REPORT_EXT = {
    "md": "md",
    "html": "html",
    "docx": "docx",
    "latex": "tex",
    "csv": "csv",
    "svg": "svg",
}


@app.command("report")
def report_command(
    ctx: typer.Context,
    section: str = typer.Argument(
        ..., help="methods | results | characteristics | amendments | checklist | rob | manuscript"
    ),
    status: bool = typer.Option(False, "--status", help="checklist: how many items remain"),
    fmt: str = typer.Option(
        "md", "--format", help="md | html | docx | latex (csv for characteristics, svg for rob)"
    ),
    out: str | None = typer.Option(None, "--out", help="Write here (`-` for standard output)"),
) -> None:
    """Generate manuscript material from the repository: openspec:manuscript-generation.

    Methods and Results (and the characteristics table, the amendments, the risk-of-bias table and
    the PRISMA checklist) are drafted from what the repository records, marked with the commit
    they came from. strata does not write a Discussion or a Conclusion. Output goes to
    reports/<section>.<format> and is committed.

    Example: strata report manuscript --format docx
    """
    repo = _resolve_repo(ctx)
    name = section.lower()
    if "discussion" in name or "conclusion" in name:
        err_console.print(f"[red]refused:[/] {sections_mod.DISCUSSION_REFUSAL}")
        raise typer.Exit(EXIT_USAGE)
    if name not in sections_mod.SECTIONS:
        err_console.print(
            f"[red]error:[/] unknown report section {section!r}; "
            f"the sections are {', '.join(sections_mod.SECTIONS)}"
        )
        raise typer.Exit(EXIT_USAGE)
    allowed = (
        {"md", "html", "docx", "latex"}
        | ({"csv"} if name == "characteristics" else set())
        | ({"svg"} if name == "rob" else set())
    )
    if fmt not in allowed:
        err_console.print(
            f"[red]error:[/] --format for {name} must be one of {', '.join(sorted(allowed))}"
        )
        raise typer.Exit(EXIT_USAGE)
    if status and name != "checklist":
        err_console.print("[red]error:[/] --status applies to the checklist only")
        raise typer.Exit(EXIT_USAGE)
    if not out and not status:  # --out writes elsewhere; --status only reports (checklist)
        _preflight_rationale(ctx, repo)
    facts = facts_mod.collect(repo)
    counts_mod.regenerate_counts_json(repo, facts.counts)
    if name != "amendments":
        try:
            counts_mod.require_reconciled(facts.counts)
        except counts_mod.CountReconcileError as exc:
            err_console.print(f"[red]{exc.code}:[/] the counts do not close: {exc}")
            raise typer.Exit(EXIT_VALIDATION) from None
    if name == "checklist" and status:
        summary = checklist_mod.status(checklist_mod.build(facts))
        if ctx.obj["json"]:
            _print_json(summary)
        else:
            out_console.print(
                f"{summary['auto_filled']} auto-filled, {summary['auto_located']} auto-located, "
                f"{summary['author']} for the author (of {summary['items']} items and sub-items)"
            )
            if summary["needs_author"]:
                out_console.print("Still yours: " + ", ".join(summary["needs_author"]))
        return
    outputs: dict[str, bytes] = {}
    try:
        if name == "checklist":
            outputs["prisma-checklist.md"] = checklist_mod.render(facts).encode("utf-8")
        elif name == "rob":
            if fmt != "svg":
                outputs["rob.md"] = sections_mod.rob_markdown(repo, facts).encode("utf-8")
            plot = sections_mod.rob_svg(repo)
            if plot is not None and fmt in ("md", "svg"):
                outputs["rob-traffic-light.svg"] = plot
        elif name == "characteristics" and fmt == "csv":
            columns, rows = sections_mod.characteristics_rows(repo)
            table = "\n".join(
                "\t".join(c.replace("\t", " ").replace("\n", " ") for c in row)
                for row in [columns, *rows]
            )
            outputs["characteristics.tsv"] = (table + "\n").encode("utf-8")
        else:
            text = {
                "methods": lambda: sections_mod.methods(facts),
                "results": lambda: sections_mod.results(facts),
                "characteristics": lambda: sections_mod.characteristics_markdown(repo, facts),
                "amendments": lambda: sections_mod.amendments_section(facts),
                "manuscript": lambda: sections_mod.manuscript(facts),
            }[name]()
            outputs[f"{name}.{_REPORT_EXT[fmt]}"] = sections_mod.convert(
                text, fmt, title=str(facts.project.get("title", ""))
            )
    except sections_mod.PandocError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    if out == "-":
        if len(outputs) != 1 or fmt in ("docx",):
            err_console.print(
                "[red]error:[/] this output has more than one file or is binary; give --out FILE"
            )
            raise typer.Exit(EXIT_USAGE)
        sys.stdout.write(next(iter(outputs.values())).decode("utf-8"))
        return
    written = []
    for filename, payload in outputs.items():
        target = Path(out) if out else repo.path("reports", filename)
        if out and len(outputs) > 1:
            target = Path(out).parent / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        written.append(str(target))
    if not out:
        _commit_domain_op(
            ctx, repo, op="report", scope=name, summary=f"generated the {name} report",
            by=_acting_handle(repo),
        )  # fmt: skip
    if ctx.obj["json"]:
        _print_json({"section": name, "written": written})
        return
    out_console.print(f"[green]wrote[/] {', '.join(written)}")


@ci_app.command("amendment")
def ci_amendment(
    ctx: typer.Context,
    base: str = typer.Option(..., "--base", help="The commit the change is made against"),
    head: str = typer.Option("HEAD", "--head", help="The commit with the change"),
) -> None:
    """Did the change between two commits edit the review criteria? (JSON)

    Compares `protocol/criteria.yaml` as data, so reformatting is not an amendment. The CI
    workflow labels such a pull request `protocol-amendment`.

    Example: strata ci amendment --base origin/main --head HEAD
    """
    repo = _resolve_repo(ctx)
    try:
        found = ci_amendment_mod.detect(repo.root, base, head)
    except gitio.GitError as exc:
        err_console.print(f"[red]error:[/] {exc.stderr.strip() or exc}")
        raise typer.Exit(EXIT_GENERIC) from None
    _print_json(found.to_dict())


@ci_app.command("comment")
def ci_comment(
    base: str = typer.Argument(..., help="`strata --json status` at the base (`null` if none)"),
    head: str = typer.Argument(..., help="`strata --json status` at the head"),
    amendment: str | None = typer.Option(
        None, "--amendment", help="The JSON `strata ci amendment` printed"
    ),
    methodologist: str | None = typer.Option(
        None, "--methodologist", help="Who is asked to review a change to the criteria"
    ),
) -> None:
    """Write the pull-request comment (Markdown) from two status documents.

    Example: strata ci comment base.json head.json --amendment amendment.json
    """
    try:
        before = json_mod.loads(Path(base).read_text(encoding="utf-8"))
        after = json_mod.loads(Path(head).read_text(encoding="utf-8"))
        found = None
        if amendment is not None:
            raw = json_mod.loads(Path(amendment).read_text(encoding="utf-8"))
            found = ci_amendment_mod.Amendment(
                changed=bool(raw["changed"]),
                version_before=raw.get("version_before"),
                version_after=raw.get("version_after"),
                added=list(raw.get("added", [])),
                changed_criteria=dict(raw.get("changed_criteria", {})),
                retired=list(raw.get("retired", [])),
            )
    except (OSError, ValueError, KeyError) as exc:
        err_console.print(f"[red]error:[/] cannot read the status documents: {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    if not isinstance(after, dict):
        err_console.print("[red]error:[/] the head status is not a status document")
        raise typer.Exit(EXIT_USAGE)
    sys.stdout.write(
        ci_comment_mod.render(
            before if isinstance(before, dict) else None,
            after,
            amendment=found,
            methodologist=methodologist,
        )
    )


@app.command("sync")
def sync_command(
    ctx: typer.Context,
    by: str | None = typer.Option(
        None, "--by", help="The actor syncing (default: the first active actor)"
    ),
    resolve: str | None = typer.Option(
        None, "--resolve", help="Settle every conflicting file the same way: mine | theirs"
    ),
    no_push: bool = typer.Option(
        False, "--no-push", help="Fetch, merge and verify, but do not push"
    ),
) -> None:
    """Fetch, merge, verify and push: the one verb for sharing a review.

    See openspec:collaboration-sync. A dirty working tree is refused. Merged event files are put in
    order and re-linked, the derived views are regenerated, and the result is verified: if that
    fails, your repository is restored exactly and nothing is pushed. Two people editing the same
    criterion or file is shown as mine and theirs; settle it with `--resolve mine|theirs`, answer
    the prompts, or open an editor.

    Example: strata sync
    """
    repo = _resolve_repo(ctx)
    if resolve not in (None, "mine", "theirs"):
        err_console.print("[red]error:[/] --resolve must be mine or theirs")
        raise typer.Exit(EXIT_USAGE)
    actor = by or _acting_handle(repo)

    def ask(conflict: sync_mod.Conflict) -> str | None:
        if resolve:
            return resolve
        out_console.print(f"\n[bold]{conflict.path}[/] was edited differently by two people:")
        for line in conflict.summary or ["(the two versions differ)"]:
            out_console.print(f"  {line}")
        try:
            choice = typer.prompt("Keep [m]ine, keep [t]heirs, or open an [e]ditor?", default="")
        except (typer.Abort, EOFError):
            return None
        return {"m": "mine", "t": "theirs", "e": "editor"}.get(choice.strip().lower()[:1])

    steps: list[str] = []

    def log(message: str) -> None:
        steps.append(message)
        if not ctx.obj["json"]:
            out_console.print(f"  {message} ...")

    try:
        report = sync_mod.sync(repo, actor=actor, push=not no_push, resolver=ask, log=log)
    except sync_mod.ConflictError as exc:
        err_console.print(f"[red]conflict:[/] {exc}")
        for conflict in exc.conflicts:
            err_console.print(f"  [bold]{conflict.path}[/]")
            for line in conflict.summary:
                err_console.print(f"    {line}")
        err_console.print(
            "Nothing changed. Run `strata sync --resolve mine` or `--resolve theirs`."
        )
        raise typer.Exit(EXIT_CONFLICT) from None
    except sync_mod.VerifyFailedError as exc:
        err_console.print(f"[red]refused:[/] {exc}")
        for issue in exc.issues[:20]:
            err_console.print(f"  {issue}")
        raise typer.Exit(EXIT_VALIDATION) from None
    except sync_mod.SyncError as exc:
        err_console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(EXIT_GENERIC) from None
    if ctx.obj["json"]:
        _print_json(
            {
                "status": report.status,
                "pushed": report.pushed,
                "incoming_commits": report.incoming_commits,
                "incoming_authors": report.incoming_authors,
                "screened": {f"{a}/{s}": dict(c) for (a, s), c in sorted(report.screened.items())},
                "other_events": report.other_events,
                "relinked": [r.file for r in report.relinked],
                "auto_resolutions": report.auto_resolutions,
                "resolved_conflicts": report.resolved_conflicts,
                "new_conflicts": report.new_conflicts,
                "totals_before": report.totals_before,
                "totals_after": report.totals_after,
            }
        )
        return
    _print_sync_report(report)


def _print_sync_report(report: sync_mod.SyncReport) -> None:
    if report.incoming_commits:
        who = ", ".join(f"{n} from {a}" for a, n in sorted(report.incoming_authors.items()))
        out_console.print(
            f"\n  Incoming: {report.incoming_commits} change(s)" + (f" ({who})" if who else "")
        )
    else:
        out_console.print("\n  Nothing incoming")
    out_console.print("  What changed:")
    shown = False
    for (actor, stage), decisions in sorted(report.screened.items()):
        total = sum(decisions.values())
        split = ", ".join(f"{n} {d}" for d, n in sorted(decisions.items()))
        out_console.print(f"    {actor} screened {total} record(s) at {stage} ({split})")
        shown = True
    for name, n in sorted(report.other_events.items()):
        out_console.print(f"    {n} {name} event(s)")
        shown = True
    for key, after in report.totals_after.items():
        before = report.totals_before.get(key, after)
        if before != after:
            out_console.print(f"    {key}: {before} -> {after}")
            shown = True
    if report.new_conflicts:
        out_console.print(
            f"    [yellow]{report.new_conflicts} new screening conflict(s)[/]"
            "   run `strata adjudicate`"
        )
        shown = True
    for relink in report.relinked:
        out_console.print(
            f"    put {relink.file} in order ({relink.lines_reordered} line(s) moved, "
            f"{relink.duplicates_dropped} duplicate(s) dropped) and re-linked it"
        )
        shown = True
    for note in report.auto_resolutions:
        out_console.print(
            f"    [yellow]decided automatically:[/] {note['record']} {note['field']} "
            f"({note['reason']})"
        )
        shown = True
    for path, choice in report.resolved_conflicts:
        out_console.print(f"    kept {choice} for {path}")
        shown = True
    if not shown:
        out_console.print("    nothing in the review itself")
    out_console.print("  " + ("Pushed" if report.pushed else "Not pushed"))


@app.command("merge-regenerate", hidden=True)
def merge_regenerate_command(
    base: str = typer.Argument(...),
    ours: str = typer.Argument(...),
    theirs: str = typer.Argument(...),
    path: str = typer.Argument(""),
) -> None:
    """Merge driver for derived files: discard both sides; they are regenerated after the merge."""
    merge_mod.merge_regenerate()


@app.command("merge-records", hidden=True)
def merge_records_command(
    base: str = typer.Argument(...),
    ours: str = typer.Argument(...),
    theirs: str = typer.Argument(...),
    path: str = typer.Argument(""),
) -> None:
    """Merge driver for records/records.ndjson: a three-way merge keyed by record id."""
    root = Path.cwd()
    try:
        trust = [
            str(t).lower()
            for t in manifest_mod.load_manifest_doc(root).get("dedup", {}).get("source_trust", [])
        ]
    except (OSError, ValueError):
        trust = []
    merge_mod.merge_records_files(
        Path(base),
        Path(ours),
        Path(theirs),
        trust=trust,
        notes=root.joinpath(*merge_mod.NOTES_PATH),
    )


@app.command("audit")
def audit_command(
    ctx: typer.Context,
    criteria: bool = typer.Option(
        False, "--criteria", help="Sample past exclusions for criterion-citation review"
    ),
    sample: int = typer.Option(20, "--sample", help="Sample size"),
    seed: int | None = typer.Option(None, "--seed", help="Reproduce a specific sample"),
) -> None:
    """Re-present a random sample of past exclusions for verification
    (openspec:staleness#mitigations-for-miscited-criteria)."""
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
    """Inter-rater reliability, over independent first opinions
    (openspec:derived-views#inter-rater-reliability-view).

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
        None,
        "--token",
        envvar="STRATA_TOKEN",
        help="Fixed session token (required with a non-loopback --host); or STRATA_TOKEN",
    ),
    public_url: str | None = typer.Option(
        None,
        "--public-url",
        envvar="STRATA_PUBLIC_URL",
        help="The URL a browser uses to reach this server (a published port or a proxy); "
        "Host and Origin are then validated against it",
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
        help="Seconds of inactivity before the server exits (openspec:web-ui#localhost-security)",
    ),
    max_upload_mb: int = typer.Option(
        web_uploads.DEFAULT_MAX_UPLOAD_MB,
        "--max-upload-mb",
        help="Largest file upload the server accepts, in megabytes (openspec:web-uploads)",
    ),
) -> None:
    """Start the local web UI (openspec:web-ui)."""
    if max_upload_mb < 1:
        err_console.print("[red]error:[/] --max-upload-mb must be at least 1")
        raise typer.Exit(EXIT_USAGE)
    repo = _resolve_repo(ctx)

    try:
        resolved_actor = web_server_mod.resolve_actor(repo, actor)
        session_token = web_server_mod.resolve_token(host, token)
        parsed_public = web_security.parse_public_url(public_url) if public_url else None
    except (web_server_mod.ServeConfigError, ValueError) as exc:
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
        public_url=parsed_public,
        max_upload_mb=max_upload_mb,
    )
    url = web_server_mod.opened_url(params)
    out_console.print(f"[green]strata serve[/] listening on {url}  (actor: {resolved_actor})")
    if not no_browser:
        webbrowser.open(url)

    asyncio.run(web_server_mod.serve_until_idle_or_interrupted(params))


@app.command("mcp")
def mcp_command(ctx: typer.Context) -> None:
    """Run the local, read-only MCP server over stdio (openspec:mcp-server).

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
