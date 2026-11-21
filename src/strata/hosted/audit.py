"""The audit log: who changed who may do what on an instance
(openspec:hosted-deployment#membership-maps-users-to-actors and
openspec:hosted-deployment#remote-mcp-access).

It sits beside the sign-in log in instance state (`strata.hosted.accounts.signin_log`) and answers
the question an incident leaves behind: who gave this person access, who raised their role, who
made this token, and when. An entry is written in the same transaction as the change it records,
so a change that was made is always in the log and one that was refused never is.

What an entry holds is about *access*, never a secret: a token's label, project and expiry, but
neither the token nor its hash; a membership's actor and role.

`performed_by` is a user name when a person did it in the browser, and `command line (<os user>)`
when an administrator did it with `strata host`: an administrator at a shell is known to the
instance only by the account they are logged in to the machine with.
"""

from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the store imports this module (its upgrade writes entries), not the reverse
    from strata.hosted.store import Store

MEMBER_GRANT = "member-grant"
ROLE_CHANGE = "role-change"
ACTOR_CHANGE = "actor-change"
MEMBER_REMOVE = "member-remove"
TOKEN_CREATE = "token-create"
TOKEN_REVOKE = "token-revoke"
#: A token expired by the instance itself, not by a person: the upgrade that ended the tokens made
#: before they named a project and expired.
TOKEN_EXPIRE = "token-expire"


def record(
    db: sqlite3.Connection,
    *,
    by: str,
    action: str,
    project: str | None = None,
    subject: str | None = None,
    detail: str,
    now: float | None = None,
) -> None:
    """Write one entry inside the caller's transaction (`Store.connect`)."""
    db.execute(
        "INSERT INTO audit (ts, performed_by, action, project, subject, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (now if now is not None else time.time(), by, action, project, subject, detail),
    )


def entries(store: Store, *, limit: int = 100) -> list[dict[str, object]]:
    """The newest entries first: `ts`, `by`, `action`, `project`, `subject` and `detail`."""
    rows = store.all(
        "SELECT id, ts, performed_by AS by_whom, action, project, subject, detail "
        "FROM audit ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [
        {
            "id": row["id"],
            "ts": row["ts"],
            "by": row["by_whom"],
            "action": row["action"],
            "project": row["project"],
            "subject": row["subject"],
            "detail": row["detail"],
        }
        for row in rows
    ]
