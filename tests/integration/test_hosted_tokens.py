"""API tokens name one project and expire; ones made before keep working until revoked
(openspec:hosted-deployment#remote-mcp-access and #isolation-between-projects; tasks 4.8 and
4.14)."""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

import pytest

from strata.hosted import accounts
from strata.hosted import members as members_mod
from tests.integration._hosted import hosted
from tests.integration.test_hosted_isolation import _mcp, _tool, _two_projects

DAY = 24 * 3600.0


def _token(world, username: str, project: str = "spacing", **options):  # type: ignore[no-untyped-def]
    return accounts.create_api_token(
        world.instance.store, username, label="mcp", project=project, by="admin",
        now=world.clock(), **options,
    )  # fmt: skip


# --------------------------------------------------------------------------- the model


def test_a_token_names_one_project_and_has_an_expiry(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    token = _token(world, "sam.okonkwo", days=30)
    found = accounts.api_token(world.instance.store, token, now=world.clock())
    assert found is not None
    assert (found.username, found.project, found.label) == ("sam.okonkwo", "spacing", "mcp")
    assert found.expires == world.clock() + 30 * DAY


def test_a_token_lasts_ninety_days_unless_told_otherwise(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    found = accounts.api_token(
        world.instance.store, _token(world, "sam.okonkwo"), now=world.clock()
    )
    assert found is not None and found.expires == world.clock() + 90 * DAY


def test_an_expired_token_is_refused_with_the_date_it_ended(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    token = _token(world, "sam.okonkwo", days=1)
    store = world.instance.store
    assert accounts.api_token(store, token, now=world.clock() + DAY - 1) is not None
    with pytest.raises(accounts.TokenExpired) as refused:
        accounts.api_token(store, token, now=world.clock() + DAY + 1)
    assert refused.value.expires == world.clock() + DAY


def test_a_token_must_last_at_least_a_day_and_says_how_to_ask_for_one(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    with pytest.raises(accounts.AccountError, match=r"at least one day.*--days 1"):
        _token(world, "sam.okonkwo", days=0)


# ------------------------------------------------------------------ making one for a member


def test_a_token_is_made_only_for_a_member_of_the_project_and_the_refusal_says_how_to_fix_it(
    tmp_path: Path,
) -> None:
    world = hosted(tmp_path)
    accounts.add_user(world.instance.store, "zoe", password="a long enough password")
    with pytest.raises(members_mod.MembershipError) as refused:
        members_mod.issue_api_token(world.instance, "zoe", "spacing", label="mcp", by="admin")
    message = str(refused.value)
    assert "zoe" in message and "spacing" in message and "not a member" in message  # what and why
    assert "strata host member add spacing zoe" in message  # what fixes it
    assert not world.instance.store.all("SELECT 1 FROM api_tokens WHERE username = 'zoe'")


def test_a_token_for_a_project_that_is_not_there_names_the_projects_that_are(
    tmp_path: Path,
) -> None:
    world = hosted(tmp_path)
    with pytest.raises(members_mod.MembershipError, match=r"no project called 'nope'.*spacing"):
        members_mod.issue_api_token(world.instance, "sam.okonkwo", "nope", label="mcp", by="admin")


# --------------------------------------------------------------------------------- over MCP


def test_a_token_reads_its_own_project(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    token = _token(h, "sam.okonkwo")
    assert _tool(h.client(), "spacing", token, "status")["title"] == "Spacing review"


def test_a_token_for_one_project_is_refused_in_another_its_owner_belongs_to(
    tmp_path: Path,
) -> None:
    h, other_ids = _two_projects(tmp_path)
    members_mod.add_member(
        h.instance, "secret-trial", "sam.okonkwo", actor="sam", role="screener", by="test"
    )
    token = _token(h, "sam.okonkwo", project="spacing")

    refused = _mcp(h.client(), "secret-trial", token, "tools/list")

    assert refused.status_code == 403
    text = refused.text
    assert (
        "spacing" in text and "secret-trial" in text
    )  # what the token is for, what it was used on
    assert "strata host token add sam.okonkwo --project secret-trial" in text  # the fix
    assert other_ids[0] not in text
    assert token not in text


def test_a_token_in_a_project_its_owner_is_not_in_learns_nothing_about_it(tmp_path: Path) -> None:
    h, _ids = _two_projects(tmp_path)
    token = _token(h, "sam.okonkwo", project="spacing")
    unknown = _mcp(h.client(), "no-such-project", token, "tools/list")
    other = _mcp(h.client(), "secret-trial", token, "tools/list")
    assert unknown.status_code == other.status_code == 404
    assert unknown.json() == other.json()


def test_an_expired_token_is_refused_and_says_so_without_naming_anyone(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    token = _token(h, "sam.okonkwo", days=2)
    assert _mcp(h.client(), "spacing", token, "initialize").status_code == 200
    h.clock.advance(3 * DAY)

    refused = _mcp(h.client(), "spacing", token, "initialize")

    assert refused.status_code == 401
    assert refused.headers["www-authenticate"].startswith("Bearer")
    description = refused.json()["error_description"]
    assert "expired" in description and "2027" in description  # the date it ended
    assert "strata host token add" in description and "--project" in description
    # It names neither the account nor the project: whoever holds a stale token is not
    # necessarily who it was made for.
    assert "sam.okonkwo" not in description and "spacing" not in description
    assert token not in refused.text


def test_a_token_made_before_projects_were_named_still_reads_every_project_its_owner_is_in(
    tmp_path: Path,
) -> None:
    h, other_ids = _two_projects(tmp_path)
    members_mod.add_member(
        h.instance, "secret-trial", "sam.okonkwo", actor="sam", role="screener", by="test"
    )
    legacy = "strata_a-token-from-the-first-release"
    h.instance.store.execute(
        "INSERT INTO api_tokens (token_hash, username, label, created, project, expires) "
        "VALUES (?, 'sam.okonkwo', 'old', 0, NULL, NULL)",
        (accounts._digest(legacy),),
    )
    h.clock.advance(10 * 365 * DAY)  # it has no expiry

    assert _tool(h.client(), "spacing", legacy, "status")["title"] == "Spacing review"
    assert [r["id"] for r in _tool(h.client(), "secret-trial", legacy, "records")] == other_ids
    assert accounts.revoke_api_tokens(h.instance.store, "sam.okonkwo", by="admin") == 1
    assert _mcp(h.client(), "spacing", legacy, "initialize").status_code == 401
