"""`strata host`: run and administer a hosted instance (openspec:cli#hosted-instance-commands).

Argument handling and output only; the instance itself is `strata.hosted`, its web application
`strata.web.hosted`. Every command here works on instance state under the data directory and none
writes an account, membership or secret into a review repository. A password or a secret is never
taken from the command line (where it would land in shell history and process listings): it is
read from a prompt, standard input, or a named environment variable.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape

from strata.hosted import accounts, audit
from strata.hosted import members as members_mod
from strata.hosted.instance import (
    HostKeyReport,
    Instance,
    InstanceError,
    ProjectUnavailable,
    default_data_dir,
)
from strata.hosted.secrets import SecretError
from strata.hosted.syncloop import SyncLoop

EXIT_GENERIC = 1
EXIT_USAGE = 2

# Never wrapped: what these commands print (invitation links, tokens, paths, commands) is copied
# and pasted, and a line break inside one breaks it.
err_console = Console(stderr=True, soft_wrap=True)
out_console = Console(soft_wrap=True)

host_app = typer.Typer(
    name="host",
    help="Run and administer a hosted strata instance (openspec:hosted-deployment).",
    invoke_without_command=True,
)
project_app = typer.Typer(name="project", help="Projects on this instance.", no_args_is_help=True)
user_app = typer.Typer(name="user", help="Local accounts.", no_args_is_help=True)
member_app = typer.Typer(name="member", help="Project memberships.", no_args_is_help=True)
token_app = typer.Typer(name="token", help="API tokens (remote MCP).", no_args_is_help=True)
secret_app = typer.Typer(name="secret", help="Instance secrets.", no_args_is_help=True)
host_app.add_typer(project_app, name="project")
host_app.add_typer(user_app, name="user")
host_app.add_typer(member_app, name="member")
host_app.add_typer(token_app, name="token")
host_app.add_typer(secret_app, name="secret")

_DATA_HELP = "The instance's data directory (default: $STRATA_DATA or /data)"


_DATA_OPTION = typer.Option(None, "--data", help=_DATA_HELP, envvar="STRATA_DATA")
_NAMES_ARGUMENT = typer.Argument(None, help="Also say where these names would come from")
_HOST_KEY_OPTION = typer.Option(
    None,
    "--host-key",
    help="Pin the remote's SSH host key: a known_hosts line, as `ssh-keyscan -t ed25519 HOST` "
    "prints it (repeat for more than one key), instead of trusting it on first use",
)


def _json(ctx: typer.Context) -> bool:
    root = ctx.find_root()
    return bool((root.obj or {}).get("json"))


def _print_json(value: object) -> None:
    out_console.print(json.dumps(value), soft_wrap=True, markup=False, highlight=False)


def _fail(message: str, code: int = EXIT_USAGE) -> typer.Exit:
    err_console.print(f"[red]error:[/] {message}", markup=True, highlight=False)
    return typer.Exit(code)


def _instance(data: Path | None, *, initialised: bool = True) -> Instance:
    instance = Instance(data or default_data_dir())
    if initialised:
        try:
            instance.require_initialised()
        except InstanceError as exc:
            raise _fail(str(exc)) from None
    return instance


def _read_password(env: str, prompt: str) -> str:
    supplied = os.environ.get(env)
    if supplied:
        return supplied
    if not sys.stdin.isatty():
        line = sys.stdin.readline().rstrip("\n")
        if line:
            return line
        raise _fail(f"no password: set {env}, pipe one on standard input, or use --invite")
    return str(typer.prompt(prompt, hide_input=True, confirmation_prompt=True))


def _operator() -> str:
    """Who an audit entry names for a change made at the command line: an administrator at a shell
    is known to the instance only by the account they are logged in to the machine with."""
    try:
        name = getpass.getuser()
    except (KeyError, OSError):  # a container user with no passwd entry
        name = f"uid {os.getuid()}"
    return f"command line ({name})"


def _invitation_url(instance: Instance, token: str) -> str:
    base = (instance.settings.public_url or "https://<public-url>").rstrip("/")
    return f"{base}/invite/{token}"


# --------------------------------------------------------------------------------- running


@host_app.callback()
def host(
    ctx: typer.Context,
    data: Path | None = _DATA_OPTION,
    public_url: str | None = typer.Option(
        None,
        "--public-url",
        envvar="STRATA_PUBLIC_URL",
        help="The https:// URL people use to reach the instance (default: instance.toml's)",
    ),
    bind: str = typer.Option(
        "127.0.0.1", "--bind", help="Address to listen on (0.0.0.0 in a container)"
    ),
    port: int = typer.Option(8000, "--port", help="Port to listen on"),
    trusted_proxy: str = typer.Option(
        "127.0.0.1",
        "--trusted-proxy",
        envvar="STRATA_TRUSTED_PROXY",
        help="Address(es) of the TLS-terminating proxy whose X-Forwarded-* headers are believed",
    ),
    insecure_local_testing: bool = typer.Option(
        False,
        "--insecure-local-testing",
        help="Accept plain HTTP and issue sessions over it: only to try an instance locally",
    ),
) -> None:
    """Run the hosted instance (with no subcommand), or administer it."""
    if ctx.invoked_subcommand is not None:
        return
    from strata.web.hosted import HostedConfigError, HostedServer, run_hosted
    from strata.web.security import parse_public_url

    instance = _instance(data)
    raw = public_url or instance.settings.public_url
    if not raw:
        raise _fail(
            "the instance needs its public URL: pass --public-url or set it in instance.toml"
        )
    try:
        parsed = parse_public_url(raw)
        server = HostedServer(instance, public_url=parsed, allow_plain_http=insecure_local_testing)
    except (ValueError, HostedConfigError, InstanceError) as exc:
        raise _fail(str(exc)) from None
    if insecure_local_testing:
        err_console.print(
            "[yellow]warning:[/] --insecure-local-testing: sessions are issued over plain HTTP; "
            "never use this for an instance other people reach"
        )
    out_console.print(
        f"[green]strata host[/] serving {len(instance.list_projects())} project(s) at "
        f"{parsed.origin} (listening on {bind}:{port})"
    )
    # A project with a symbolic link is refused on its own; the instance starts without it.
    for refusal in instance.unavailable_projects():
        err_console.print(f"[yellow]warning:[/] {escape(str(refusal))}")
    run_hosted(server, bind=bind, port=port, trusted_proxies=trusted_proxy)


@host_app.command("init")
def init_command(
    ctx: typer.Context,
    data: Path | None = _DATA_OPTION,
    public_url: str | None = typer.Option(None, "--public-url", envvar="STRATA_PUBLIC_URL"),
    admin: str = typer.Option("admin", "--admin", help="User name of the first administrator"),
    admin_name: str | None = typer.Option(None, "--admin-name", help="Their display name"),
    admin_email: str | None = typer.Option(None, "--admin-email"),
    invite: bool = typer.Option(
        False, "--invite", help="Print an invitation link instead of asking for a password"
    ),
) -> None:
    """Initialise instance state and the first administrator."""
    instance = _instance(data, initialised=False)
    already = instance.is_initialised()
    if public_url:
        from strata.web.security import parse_public_url

        try:
            parse_public_url(public_url)
        except ValueError as exc:
            raise _fail(str(exc)) from None
    instance.initialise(public_url=public_url)
    if already and accounts.list_users(instance.store):
        out_console.print(f"instance at {instance.data_dir} is already initialised")
        return
    password = None if invite else _read_password("STRATA_ADMIN_PASSWORD", "Administrator password")
    try:
        accounts.add_user(
            instance.store, admin, display_name=admin_name, email=admin_email,
            password=password, admin=True,
        )  # fmt: skip
    except accounts.AccountError as exc:
        raise _fail(str(exc)) from None
    payload: dict[str, Any] = {"data": str(instance.data_dir), "admin": admin}
    if invite:
        payload["invitation"] = _invitation_url(
            instance, accounts.create_invitation(instance.store, admin)
        )
    if _json(ctx):
        _print_json(payload)
        return
    out_console.print(
        f"[green]initialised[/] instance at {instance.data_dir}; administrator {admin}"
    )
    if invite:
        out_console.print(f"invitation (valid for 7 days): {payload['invitation']}")


# -------------------------------------------------------------------------------- projects


def _host_key_payload(report: HostKeyReport | None) -> dict[str, Any]:
    return {
        "host": report.host if report else None,
        "pinned": report.pinned if report else False,
        "keys": [
            {"type": k.key_type, "fingerprint": k.fingerprint, "line": k.line}
            for k in (report.keys if report else [])
        ],
    }


def _print_host_key(report: HostKeyReport | None, project_id: str, *, first_clone: bool) -> None:
    """What the operator is told about the SSH host key a project's remote is trusted with."""
    if report is None:
        return
    keys = "\n".join(f"  {k.key_type} {k.fingerprint}" for k in report.keys)
    if report.pinned:
        out_console.print(
            f"host key pinned for {report.host}: ssh will believe only\n{keys}", markup=False
        )
    elif report.keys:
        when = "accepted on first use" if first_clone else "trusted on first use (not pinned)"
        out_console.print(f"host key for {report.host} {when}:\n{keys}", markup=False)
        out_console.print(
            "Compare this fingerprint with the one the git host publishes. If it differs, "
            "someone may be in the way: pin the right key with "
            f"`strata host project host-key {project_id} --host-key '<known_hosts line>'`.",
            markup=False,
        )


@project_app.command("add")
def project_add(
    ctx: typer.Context,
    project_id: str = typer.Argument(..., help="Short id, used in URLs (e.g. spacing)"),
    remote: str | None = typer.Option(None, "--remote", help="Clone this review's git remote"),
    credential: str | None = typer.Option(
        None,
        "--credential",
        help="KIND:SECRET -- ssh-key:<secret> (deploy key) or token:<secret> (HTTPS token)",
    ),
    credential_user: str | None = typer.Option(
        None, "--credential-user", help="User name sent with an HTTPS token"
    ),
    host_key: list[str] | None = _HOST_KEY_OPTION,
    title: str | None = typer.Option(None, "--title"),
    actor: str | None = typer.Option(None, "--actor", help="First actor of a new review"),
    actor_name: str | None = typer.Option(None, "--actor-name"),
    actor_email: str | None = typer.Option(None, "--actor-email"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Add a project by cloning its remote, or initialise a new review."""
    instance = _instance(data)
    kind = secret = None
    if credential is not None:
        kind, _, secret = credential.partition(":")
        if not secret:
            raise _fail("--credential takes KIND:SECRET, e.g. ssh-key:spacing-deploy-key")
    try:
        project = instance.add_project(
            project_id,
            remote=remote,
            credential_kind=kind,
            credential_secret=secret,
            credential_username=credential_user,
            title=title,
            actor_handle=actor,
            actor_name=actor_name,
            actor_email=actor_email,
            host_keys=host_key,
        )
    except (InstanceError, SecretError) as exc:
        raise _fail(str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - e.g. the remote is not a strata review
        raise _fail(f"could not add {project_id}: {exc}", EXIT_GENERIC) from None
    report = instance.host_key_report(project.id)
    if _json(ctx):
        payload: dict[str, Any] = {
            "id": project.id, "title": project.title, "remote": project.remote,
        }  # fmt: skip
        if report is not None:  # only where the instance chose a host key to trust
            payload["host_key"] = _host_key_payload(report)
        _print_json(payload)
        return
    how = f"cloned from {project.remote}" if project.remote else "initialised"
    out_console.print(f"[green]added[/] project {project.id} ({how})")
    _print_host_key(report, project.id, first_clone=True)


@project_app.command("list")
def project_list(ctx: typer.Context, data: Path | None = _DATA_OPTION) -> None:
    """List projects with their remote and last-sync status."""
    instance = _instance(data)
    loop = SyncLoop(instance)
    rows = []
    for project in instance.list_projects():
        view = loop.status(project.id).as_view()
        links = instance.symlinks_in(project.id)  # reads only: listing changes nothing
        rows.append(
            {
                "id": project.id,
                "title": project.title,
                "remote": project.remote,
                "members": len(members_mod.members_of(instance, project.id)),
                "last_sync": view["last_success"],
                "last_error": view["last_error"],
                "conflicts": view["conflicts"],
                "push_pending": view["push_pending"],
                "unavailable": str(ProjectUnavailable(project.id, links)) if links else None,
                "links": links,
            }
        )
    if _json(ctx):
        _print_json(rows)
        return
    if not rows:
        out_console.print("no projects yet; add one with `strata host project add`")
    for row in rows:
        state = (
            f"unavailable: symbolic link at {row['links'][0]}"
            if row["unavailable"]
            else "no remote"
            if not row["remote"]
            else "conflict waiting for a lead"
            if row["conflicts"]
            else f"last sync failed: {row['last_error']}"
            if row["last_error"]
            else f"last synced {row['last_sync'] or 'never'}"
        )
        out_console.print(
            f"{row['id']}\t{row['title']}\t{row['members']} member(s)\t{row['remote'] or '-'}\t"
            f"{state}",
            markup=False,
            highlight=False,
        )
        if row["unavailable"]:
            out_console.print(f"  {row['unavailable']}", markup=False, highlight=False)


@project_app.command("host-key")
def project_host_key(
    ctx: typer.Context,
    project_id: str,
    host_key: list[str] | None = _HOST_KEY_OPTION,
    clear: bool = typer.Option(False, "--clear", help="Go back to trusting the key on first use"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Show, pin or unpin the SSH host key a project's remote is trusted with."""
    instance = _instance(data)
    if clear and host_key:
        raise _fail("give --host-key to pin a key or --clear to remove the pin, not both")
    try:
        if host_key:
            instance.set_host_keys(project_id, host_key)
        elif clear:
            instance.set_host_keys(project_id, None)
        elif instance.get_project(project_id) is None:
            instance.set_host_keys(project_id, None)  # says there is no such project
        report = instance.host_key_report(project_id)
    except InstanceError as exc:
        raise _fail(str(exc)) from None
    if _json(ctx):
        _print_json({"project": project_id, **_host_key_payload(report)})
        return
    if clear:
        out_console.print(
            f"pin removed: {project_id} goes back to trust on first use", markup=False
        )
    if report is None:
        out_console.print(
            f"{project_id}: no host key is pinned or recorded here: its remote is not reached "
            "with a deploy key over SSH, so ssh uses the machine's own known_hosts (or the "
            "remote is https). Pin one with --host-key if the remote is SSH.",
            markup=False,
        )
    else:
        _print_host_key(report, project_id, first_clone=False)
        if not report.keys:
            out_console.print(
                f"no key recorded yet for {report.host}: the first connection will trust the key "
                "the host shows",
                markup=False,
            )


# ---------------------------------------------------------------------------------- users


@user_app.command("add")
def user_add(
    ctx: typer.Context,
    username: str,
    name: str | None = typer.Option(None, "--name", help="Display name"),
    email: str | None = typer.Option(None, "--email"),
    admin: bool = typer.Option(False, "--admin", help="Make them an instance administrator"),
    invite: bool = typer.Option(
        False, "--invite", help="Print an invitation link instead of setting a password"
    ),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Create a local account."""
    instance = _instance(data)
    password = None if invite else _read_password("STRATA_PASSWORD", f"Password for {username}")
    try:
        accounts.add_user(
            instance.store, username, display_name=name, email=email, password=password,
            admin=admin,
        )  # fmt: skip
    except accounts.AccountError as exc:
        raise _fail(str(exc)) from None
    link = (
        _invitation_url(instance, accounts.create_invitation(instance.store, username))
        if invite
        else None
    )
    if _json(ctx):
        _print_json({"username": username, "invitation": link})
        return
    out_console.print(f"[green]added[/] account {username}")
    if link:
        out_console.print(f"invitation (valid for 7 days): {link}", markup=False)


@user_app.command("invite")
def user_invite(ctx: typer.Context, username: str, data: Path | None = _DATA_OPTION) -> None:
    """Issue a new invitation link for an existing account (to reset a password)."""
    instance = _instance(data)
    try:
        link = _invitation_url(instance, accounts.create_invitation(instance.store, username))
    except accounts.AccountError as exc:
        raise _fail(str(exc)) from None
    if _json(ctx):
        _print_json({"username": username, "invitation": link})
        return
    out_console.print(f"invitation for {username} (valid for 7 days): {link}", markup=False)


@user_app.command("disable")
def user_disable(username: str, data: Path | None = _DATA_OPTION) -> None:
    """Disable an account: it cannot sign in, and its sessions and API tokens end now."""
    instance = _instance(data)
    try:
        accounts.disable_user(instance.store, username)
    except accounts.AccountError as exc:
        raise _fail(str(exc)) from None
    out_console.print(f"disabled {username}")


@user_app.command("enable")
def user_enable(username: str, data: Path | None = _DATA_OPTION) -> None:
    """Re-enable a disabled account."""
    instance = _instance(data)
    try:
        accounts.enable_user(instance.store, username)
    except accounts.AccountError as exc:
        raise _fail(str(exc)) from None
    out_console.print(f"enabled {username}")


@user_app.command("list")
def user_list(ctx: typer.Context, data: Path | None = _DATA_OPTION) -> None:
    """List accounts (never their credentials)."""
    instance = _instance(data)
    rows = [
        {
            "username": u.username,
            "name": u.display_name,
            "admin": u.is_admin,
            "disabled": u.disabled,
            "password": u.has_password,
        }
        for u in accounts.list_users(instance.store)
    ]
    if _json(ctx):
        _print_json(rows)
        return
    for row in rows:
        flags = ", ".join(
            f for f, on in (("admin", row["admin"]), ("disabled", row["disabled"])) if on
        )
        out_console.print(f"{row['username']}\t{row['name']}\t{flags}", markup=False)


@host_app.command("signins")
def signins(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Show the sign-in audit log, newest first."""
    instance = _instance(data)
    rows = accounts.signin_log(instance.store, limit=limit)
    if _json(ctx):
        _print_json(rows)
        return
    for row in rows:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(row["ts"])))  # type: ignore[arg-type]
        out_console.print(
            f"{when}\t{row['username']}\t{row['client']}\t{row['method']}\t{row['outcome']}",
            markup=False,
        )


@host_app.command("audit")
def audit_log(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Show who granted or changed access (memberships and API tokens), newest first."""
    instance = _instance(data)
    rows = audit.entries(instance.store, limit=limit)
    if _json(ctx):
        _print_json(rows)
        return
    for row in rows:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(row["ts"])))  # type: ignore[arg-type]
        out_console.print(
            f"{when}\t{row['by']}\t{row['action']}\t{row['project'] or '-'}\t"
            f"{row['subject'] or '-'}\t{row['detail']}",
            markup=False,
        )


# ------------------------------------------------------------------------------- members


@member_app.command("add")
def member_add(
    ctx: typer.Context,
    project: str,
    username: str,
    actor: str = typer.Option(..., "--actor", help="The actor handle in the project's strata.toml"),
    role: str = typer.Option(..., "--role", help=f"One of: {', '.join(members_mod.ROLES)}"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Map a user to an actor and role in a project."""
    instance = _instance(data)
    try:
        membership = members_mod.add_member(
            instance, project, username, actor=actor, role=role, by=_operator()
        )
    except InstanceError as exc:
        raise _fail(str(exc)) from None
    if _json(ctx):
        _print_json(membership.__dict__)
        return
    out_console.print(f"{username} is {actor} ({role}) in {project}", markup=False, highlight=False)


@member_app.command("remove")
def member_remove(project: str, username: str, data: Path | None = _DATA_OPTION) -> None:
    """Remove a user's membership of a project."""
    instance = _instance(data)
    if not members_mod.remove_member(instance, project, username, by=_operator()):
        raise _fail(f"{username} is not a member of {project}")
    out_console.print(f"removed {username} from {project}", markup=False)


@member_app.command("list")
def member_list(ctx: typer.Context, project: str, data: Path | None = _DATA_OPTION) -> None:
    """List a project's members."""
    instance = _instance(data)
    rows = [m.__dict__ for m in members_mod.members_of(instance, project)]
    if _json(ctx):
        _print_json(rows)
        return
    for row in rows:
        out_console.print(f"{row['username']}\t{row['actor']}\t{row['role']}", markup=False)


# -------------------------------------------------------------------------------- tokens


@token_app.command("add")
def token_add(
    ctx: typer.Context,
    username: str,
    project: str = typer.Option(
        ..., "--project", help="The one project the token reads (the user must be a member)"
    ),
    days: int = typer.Option(
        accounts.DEFAULT_TOKEN_DAYS, "--days", help="How many days until the token expires"
    ),
    label: str = typer.Option("mcp", "--label", help="What the token is for"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Create an API token for a user's MCP client; shown once, stored only as a hash.

    A token reads one project and expires, so one that leaks gives a stranger one review for a
    while rather than every review its owner is in.
    """
    instance = _instance(data)
    try:
        token = members_mod.issue_api_token(
            instance, username, project, label=label, days=days, by=_operator()
        )
    except (accounts.AccountError, InstanceError) as exc:
        raise _fail(str(exc)) from None
    found = accounts.api_token(instance.store, token)
    expires = found.expires if found is not None else None
    until = time.strftime("%Y-%m-%d", time.gmtime(expires)) if expires is not None else "never"
    if _json(ctx):
        _print_json(
            {
                "username": username, "label": label, "project": project, "days": days,
                "expires": until, "token": token,
            }
        )  # fmt: skip
        return
    out_console.print(
        f"API token for {username} ({label}), for the project {project}, expires {until}; "
        "it is not shown again:",
        markup=False,
    )
    out_console.print(token, markup=False, highlight=False)


@token_app.command("revoke")
def token_revoke(
    username: str,
    label: str | None = typer.Option(None, "--label", help="Only the tokens with this label"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Revoke a user's API tokens."""
    instance = _instance(data)
    count = accounts.revoke_api_tokens(instance.store, username, label=label, by=_operator())
    out_console.print(f"revoked {count} token(s)")


# ------------------------------------------------------------------------------- secrets


@secret_app.command("set")
def secret_set(
    name: str,
    from_env: str | None = typer.Option(
        None, "--from-env", help="Read the value from this environment variable"
    ),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Store a secret encrypted at rest (a deploy key, a token, an OIDC client secret).

    The value is read from standard input (a deploy key can be piped in: `strata host secret set
    spacing-key < id_ed25519`), from --from-env, or from a hidden prompt; never from the command
    line.
    """
    instance = _instance(data)
    if from_env is not None:
        value = os.environ.get(from_env, "")
    elif not sys.stdin.isatty():
        value = sys.stdin.read()
    else:
        value = str(typer.prompt(f"Value of {name}", hide_input=True))
    try:
        instance.secrets.put(name, value.strip("\n"))
    except SecretError as exc:
        raise _fail(str(exc)) from None
    out_console.print(f"stored secret {name} (encrypted)")


@secret_app.command("list")
def secret_list(
    ctx: typer.Context,
    names: list[str] = _NAMES_ARGUMENT,
    data: Path | None = _DATA_OPTION,
) -> None:
    """List stored secret names (never values), and where any named one comes from."""
    instance = _instance(data)
    rows = [{"name": n, "source": "stored"} for n in instance.secrets.stored_names()]
    for name in names or []:
        if not any(r["name"] == name for r in rows):
            rows.append({"name": name, "source": instance.secrets.source(name) or "missing"})
    if _json(ctx):
        _print_json(rows)
        return
    for row in rows:
        out_console.print(f"{row['name']}\t{row['source']}", markup=False)


@secret_app.command("delete")
def secret_delete(name: str, data: Path | None = _DATA_OPTION) -> None:
    """Delete a stored secret."""
    instance = _instance(data)
    if not instance.secrets.delete(name):
        raise _fail(f"there is no stored secret called {name!r}")
    out_console.print(f"deleted secret {name}")
