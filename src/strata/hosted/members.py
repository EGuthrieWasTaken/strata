"""Memberships and roles: openspec:hosted-deployment#membership-maps-users-to-actors.

A user acts in a project only through a membership, which names exactly one actor handle declared
in that project's `strata.toml` and a role. Users are not actors: the same person can be `ethan`
in one review and `eguthrie` in another, and an instance administrator has no role in any review
unless a lead gives them one. Within a project an actor belongs to at most one user, so every
event and commit made for a user carries their own handle.

Roles are `strata.toml`'s (`lead`, `screener`, `extractor`, `adjudicator`, `observer`). What each
may do on a hosted instance, checked on every request before it reaches a screen:

| Role        | May                                                                          |
|-------------|------------------------------------------------------------------------------|
| observer    | read                                                                         |
| screener    | read, screen and re-screen, correct a record                                 |
| extractor   | read, extract data and judge risk of bias, record full-text retrieval,       |
|             | correct a record                                                             |
| adjudicator | read, screen and re-screen, adjudicate, correct a record                     |
| lead        | everything, including criteria, searches and imports, deduplication,         |
|             | assignment, study grouping, members and sync conflicts                       |

An action the table does not name is the lead's alone.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from strata.core import agents as agents_mod
from strata.core.actor import VALID_ROLES
from strata.core.repo import open_repo
from strata.hosted import accounts, audit
from strata.hosted.instance import Instance, InstanceError

ROLES = tuple(sorted(VALID_ROLES - {"inactive"}))

READ = "read"
SCREEN = "screen"
ADJUDICATE = "adjudicate"
EXTRACT = "extract"
RETRIEVE = "retrieve"
FIX_RECORD = "fix-record"
LEAD = "lead"  # anything else: criteria, imports, dedup, assignment, studies, members, conflicts

_CAPABILITIES: dict[str, frozenset[str]] = {
    "observer": frozenset({READ}),
    "screener": frozenset({READ, SCREEN, FIX_RECORD}),
    "extractor": frozenset({READ, EXTRACT, RETRIEVE, FIX_RECORD}),
    "adjudicator": frozenset({READ, SCREEN, ADJUDICATE, FIX_RECORD}),
}

#: Which capability a request inside a project needs, by its method and the first segment of its
#: path. Reads need `READ`, except the adjudication queue, which shows both sides of a conflict.
_WRITE_CAPABILITY = {
    "screen": SCREEN,
    "rescreen": SCREEN,
    "session": SCREEN,  # ending a screening session commits one's own pending decisions
    "adjudicate": ADJUDICATE,
    "extract": EXTRACT,
    "rob": EXTRACT,
    "retrieve": RETRIEVE,
}
_READ_CAPABILITY = {"adjudicate": ADJUDICATE}


class MembershipError(InstanceError):
    pass


@dataclass(frozen=True)
class Membership:
    project: str
    username: str
    actor: str
    role: str


def may(role: str, capability: str) -> bool:
    """Whether a member with `role` may do what `capability` names."""
    if role == "lead":
        return True
    return capability in _CAPABILITIES.get(role, frozenset())


def required_capability(method: str, path: str) -> str:
    """The capability a request inside a project needs; `path` is relative to the project."""
    segments = [s for s in path.split("/") if s]
    first = segments[0] if segments else ""
    if method in ("GET", "HEAD"):
        return _READ_CAPABILITY.get(first, READ)
    if first == "records" and len(segments) == 3 and segments[2] == "fix":
        return FIX_RECORD
    return _WRITE_CAPABILITY.get(first, LEAD)


def _membership(row: sqlite3.Row) -> Membership:
    return Membership(
        project=row["project"], username=row["username"], actor=row["actor"], role=row["role"]
    )


def add_member(
    instance: Instance,
    project_id: str,
    username: str,
    *,
    actor: str,
    role: str,
    by: str,
    now: float | None = None,
) -> Membership:
    """Map `username` to `actor` with `role` in a project. Writes instance state only, and an
    entry in the audit log, as `by`, when it grants a membership or changes one (saving what is
    already there changes nothing and logs nothing)."""
    if instance.get_project(project_id) is None:
        raise MembershipError(f"there is no project called {project_id!r}")
    user = accounts.get_user(instance.store, username)
    if user is None:
        raise MembershipError(f"there is no account called {username!r}")
    if role not in ROLES:
        raise MembershipError(f"invalid role {role!r}; use one of {', '.join(ROLES)}")
    repo = open_repo(instance.project_dir(project_id))
    actors = {a.get("handle"): a for a in repo.config.get("actors", [])}
    if actor not in actors:
        raise MembershipError(
            f"{actor!r} is not an actor in {project_id}'s strata.toml; add it there first "
            f"(`strata actor add`), or use one of: {', '.join(sorted(map(str, actors))) or 'none'}"
        )
    if actors[actor].get("role") == "inactive":
        raise MembershipError(f"{actor!r} is deactivated in {project_id}'s strata.toml")
    if agents_mod.is_agent(repo, actor):
        raise MembershipError(
            f"{actor!r} is an AI agent in {project_id}'s strata.toml; a person signs in as a person"
        )
    taken = instance.store.one(
        "SELECT username FROM memberships WHERE project = ? AND actor = ?", (project_id, actor)
    )
    if taken is not None and taken["username"] != username:
        raise MembershipError(
            f"{actor!r} already belongs to {taken['username']!r} in {project_id}; one actor is "
            "one person"
        )
    current = membership(instance, project_id, username)
    if (
        current is not None
        and current.role == "lead"
        and role != "lead"
        and len(leads_of(instance, project_id)) <= 1
    ):
        raise MembershipError(f"{username!r} is the only lead of {project_id}; a project keeps one")
    with instance.store.connect() as db:
        before = db.execute(
            "SELECT actor, role FROM memberships WHERE project = ? AND username = ?",
            (project_id, username),
        ).fetchone()
        db.execute(
            "INSERT INTO memberships (project, username, actor, role) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (project, username) DO UPDATE SET actor = excluded.actor, "
            "role = excluded.role",
            (project_id, username, actor, role),
        )
        if before is None:
            action, detail = audit.MEMBER_GRANT, f"now acts as {actor} with the role {role}"
        elif before["role"] != role:
            action = audit.ROLE_CHANGE
            detail = f"the role {before['role']} became {role}"
            if before["actor"] != actor:
                detail += f", and the actor {before['actor']} became {actor}"
        elif before["actor"] != actor:
            action = audit.ACTOR_CHANGE
            detail = f"the actor {before['actor']} became {actor}, with the same role {role}"
        else:
            action = detail = ""
        if action:
            audit.record(
                db, by=by, action=action, project=project_id, subject=username, detail=detail,
                now=now,
            )  # fmt: skip
    return Membership(project_id, username, actor, role)


def remove_member(
    instance: Instance, project_id: str, username: str, *, by: str, now: float | None = None
) -> bool:
    """Remove a membership; whether there was one. Logged, as `by`, when there was."""
    with instance.store.connect() as db:
        before = db.execute(
            "SELECT actor, role FROM memberships WHERE project = ? AND username = ?",
            (project_id, username),
        ).fetchone()
        if before is None:
            return False
        db.execute(
            "DELETE FROM memberships WHERE project = ? AND username = ?", (project_id, username)
        )
        audit.record(
            db, by=by, action=audit.MEMBER_REMOVE, project=project_id, subject=username,
            detail=f"removed; they were {before['actor']} with the role {before['role']}",
            now=now,
        )  # fmt: skip
    return True


def issue_api_token(
    instance: Instance,
    username: str,
    project_id: str,
    *,
    by: str,
    label: str = "mcp",
    days: float = accounts.DEFAULT_TOKEN_DAYS,
    now: float | None = None,
) -> str:
    """An API token for `username` that reads `project_id` and expires after `days`. A token is
    only useful to a member of the project, so it is only made for one."""
    projects = [project.id for project in instance.list_projects()]
    if project_id not in projects:
        raise MembershipError(
            f"there is no project called {project_id!r}, so no token was made; this instance "
            f"has: {', '.join(projects) or 'no projects yet'}"
        )
    if accounts.get_user(instance.store, username) is not None and (
        membership(instance, project_id, username) is None
    ):
        raise MembershipError(
            f"{username!r} is not a member of {project_id!r}, so a token for it would read "
            f"nothing and none was made; make them a member first with `strata host member add "
            f"{project_id} {username} --actor HANDLE --role ROLE`, then ask again"
        )
    return accounts.create_api_token(
        instance.store, username, label=label, project=project_id, days=days, by=by, now=now
    )


def membership(instance: Instance, project_id: str, username: str) -> Membership | None:
    row = instance.store.one(
        "SELECT * FROM memberships WHERE project = ? AND username = ?", (project_id, username)
    )
    return _membership(row) if row is not None else None


def members_of(instance: Instance, project_id: str) -> list[Membership]:
    rows = instance.store.all(
        "SELECT * FROM memberships WHERE project = ? ORDER BY username", (project_id,)
    )
    return [_membership(row) for row in rows]


def memberships_of(instance: Instance, username: str) -> list[Membership]:
    rows = instance.store.all(
        "SELECT * FROM memberships WHERE username = ? ORDER BY project", (username,)
    )
    return [_membership(row) for row in rows]


def leads_of(instance: Instance, project_id: str) -> list[Membership]:
    return [m for m in members_of(instance, project_id) if m.role == "lead"]
