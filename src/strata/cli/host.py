"""`strata host`: run and administer a hosted instance (openspec:cli#hosted-instance-commands).

Argument handling and output only; the instance itself is `strata.hosted`, its web application
`strata.web.hosted`. Every command here works on instance state under the data directory and none
writes an account, membership or secret into a review repository. A password or a secret is never
taken from the command line (where it would land in shell history and process listings): it is
read from a prompt, standard input, or a named environment variable.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.hosted.instance import Instance, InstanceError, default_data_dir
from strata.hosted.secrets import SecretError
from strata.hosted.syncloop import SyncLoop

EXIT_GENERIC = 1
EXIT_USAGE = 2

err_console = Console(stderr=True)
out_console = Console()

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


def _json(ctx: typer.Context) -> bool:
    root = ctx.find_root()
    return bool((root.obj or {}).get("json"))


def _print_json(value: object) -> None:
    out_console.print(json.dumps(value), soft_wrap=True, markup=False, highlight=False)


def _fail(message: str, code: int = EXIT_USAGE) -> typer.Exit:
    # Not wrapped: a path or a command in the message must stay whole to be copied.
    err_console.print(f"[red]error:[/] {message}", markup=True, highlight=False, soft_wrap=True)
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
        )
    except (InstanceError, SecretError) as exc:
        raise _fail(str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - e.g. the remote is not a strata review
        raise _fail(f"could not add {project_id}: {exc}", EXIT_GENERIC) from None
    if _json(ctx):
        _print_json({"id": project.id, "title": project.title, "remote": project.remote})
        return
    how = f"cloned from {project.remote}" if project.remote else "initialised"
    out_console.print(f"[green]added[/] project {project.id} ({how})")


@project_app.command("list")
def project_list(ctx: typer.Context, data: Path | None = _DATA_OPTION) -> None:
    """List projects with their remote and last-sync status."""
    instance = _instance(data)
    loop = SyncLoop(instance)
    rows = []
    for project in instance.list_projects():
        view = loop.status(project.id).as_view()
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
            }
        )
    if _json(ctx):
        _print_json(rows)
        return
    if not rows:
        out_console.print("no projects yet; add one with `strata host project add`")
    for row in rows:
        state = (
            "no remote"
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
    import time

    for row in rows:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(row["ts"])))  # type: ignore[arg-type]
        out_console.print(
            f"{when}\t{row['username']}\t{row['client']}\t{row['method']}\t{row['outcome']}",
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
        membership = members_mod.add_member(instance, project, username, actor=actor, role=role)
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
    if not members_mod.remove_member(instance, project, username):
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
    label: str = typer.Option("mcp", "--label", help="What the token is for"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Create an API token for a user's MCP client; shown once, stored only as a hash."""
    instance = _instance(data)
    try:
        token = accounts.create_api_token(instance.store, username, label=label)
    except accounts.AccountError as exc:
        raise _fail(str(exc)) from None
    if _json(ctx):
        _print_json({"username": username, "label": label, "token": token})
        return
    out_console.print(f"API token for {username} ({label}); it is not shown again:", markup=False)
    out_console.print(token, markup=False, highlight=False)


@token_app.command("revoke")
def token_revoke(
    username: str,
    label: str | None = typer.Option(None, "--label", help="Only the tokens with this label"),
    data: Path | None = _DATA_OPTION,
) -> None:
    """Revoke a user's API tokens."""
    instance = _instance(data)
    count = accounts.revoke_api_tokens(instance.store, username, label=label)
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
