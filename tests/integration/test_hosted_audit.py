"""Who granted what, and who made or ended a token: the audit log beside the sign-in log
(openspec:hosted-deployment#membership-maps-users-to-actors and #remote-mcp-access; task 4.11)."""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

from strata.hosted import accounts, audit
from strata.hosted import members as members_mod
from tests.integration._hosted import PASSWORD, hosted, post

SPACING = "spacing"


def _about(world, subject: str) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    """The audit entries about `subject`, oldest first."""
    return [r for r in reversed(audit.entries(world.instance.store)) if r["subject"] == subject]


def test_a_grant_a_role_change_and_a_removal_are_logged_with_who_did_each(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    instance = world.instance
    accounts.add_user(instance.store, "zoe", password=PASSWORD)

    members_mod.add_member(
        instance, SPACING, "zoe", actor="priya", role="screener", by="ethan.g", now=100.0
    )
    members_mod.add_member(
        instance, SPACING, "zoe", actor="priya", role="adjudicator", by="ethan.g", now=200.0
    )
    members_mod.remove_member(instance, SPACING, "zoe", by="admin", now=300.0)

    grant, change, removal = _about(world, "zoe")
    assert (grant["ts"], grant["by"], grant["action"], grant["project"]) == (
        100.0, "ethan.g", "member-grant", SPACING,
    )  # fmt: skip
    assert "priya" in str(grant["detail"]) and "screener" in str(grant["detail"])
    assert (change["ts"], change["by"], change["action"]) == (200.0, "ethan.g", "role-change")
    assert "screener" in str(change["detail"]) and "adjudicator" in str(change["detail"])
    assert (removal["ts"], removal["by"], removal["action"]) == (300.0, "admin", "member-remove")
    assert "priya" in str(removal["detail"]) and "adjudicator" in str(removal["detail"])


def test_a_change_of_actor_alone_is_logged_too(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    accounts.add_user(world.instance.store, "zoe", password=PASSWORD)
    members_mod.add_member(
        world.instance, SPACING, "zoe", actor="priya", role="screener", by="ethan.g"
    )
    members_mod.remove_member(world.instance, SPACING, "sam.okonkwo", by="ethan.g")
    members_mod.add_member(
        world.instance, SPACING, "zoe", actor="sam", role="screener", by="ethan.g"
    )

    actions = [r["action"] for r in _about(world, "zoe")]
    assert actions == ["member-grant", "actor-change"]


def test_saving_a_membership_that_changes_nothing_logs_nothing(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    before = len(audit.entries(world.instance.store))
    members_mod.add_member(
        world.instance, SPACING, "sam.okonkwo", actor="sam", role="screener", by="ethan.g"
    )
    assert len(audit.entries(world.instance.store)) == before
    assert not members_mod.remove_member(world.instance, SPACING, "nobody", by="ethan.g")
    assert len(audit.entries(world.instance.store)) == before


def test_a_refused_membership_change_is_not_logged_as_made(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    before = len(audit.entries(world.instance.store))
    try:
        members_mod.add_member(
            world.instance, SPACING, "ethan.g", actor="ethan", role="observer", by="ethan.g"
        )
    except members_mod.MembershipError:
        pass
    else:  # pragma: no cover
        raise AssertionError("the only lead was demoted")
    assert len(audit.entries(world.instance.store)) == before


def test_creating_and_revoking_a_token_is_logged_and_never_contains_the_token(
    tmp_path: Path,
) -> None:
    world = hosted(tmp_path)
    store = world.instance.store
    token = accounts.create_api_token(
        store,
        "sam.okonkwo",
        label="laptop",
        project=SPACING,
        days=30,
        by="admin",
        now=1_800_000_000.0,
    )
    assert (
        accounts.revoke_api_tokens(
            store, "sam.okonkwo", label="laptop", by="ethan.g", now=1_800_000_100.0
        )
        == 1
    )

    created, revoked = _about(world, "sam.okonkwo")[-2:]
    assert (created["by"], created["action"], created["project"]) == (
        "admin",
        "token-create",
        SPACING,
    )
    assert "laptop" in str(created["detail"]) and "30 day" in str(created["detail"])
    assert (revoked["by"], revoked["action"]) == ("ethan.g", "token-revoke")
    assert "laptop" in str(revoked["detail"]) and "1 token" in str(revoked["detail"])
    for entry in audit.entries(store):
        assert token not in repr(entry) and accounts._digest(token) not in repr(entry)


def test_revoking_nothing_is_not_logged(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    before = len(audit.entries(world.instance.store))
    assert accounts.revoke_api_tokens(world.instance.store, "sam.okonkwo", by="admin") == 0
    assert len(audit.entries(world.instance.store)) == before


def test_a_lead_changing_members_in_the_browser_is_recorded_as_that_lead(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    accounts.add_user(world.instance.store, "zoe", password=PASSWORD)
    lead = world.signed_in("ethan.g")

    added = post(lead, "/-/members", {"username": "zoe", "actor": "priya", "role": "screener"})
    assert added.status_code == 303
    removed = post(lead, "/-/members/remove", {"username": "zoe"})
    assert removed.status_code == 303

    grant, removal = _about(world, "zoe")
    assert (grant["by"], grant["action"], grant["project"]) == ("ethan.g", "member-grant", SPACING)
    assert (removal["by"], removal["action"]) == ("ethan.g", "member-remove")


def test_the_log_is_newest_first_and_limited(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    store = world.instance.store
    for index in range(5):
        accounts.create_api_token(
            store, "olive", label=f"t{index}", project=SPACING, by="admin", now=float(index)
        )
    rows = audit.entries(store, limit=3)
    assert [r["ts"] for r in rows] == [4.0, 3.0, 2.0]
