"""What a project's remote and a lead cannot do to an instance: openspec:hosted-deployment
#hosted-security-baseline and #isolation-between-projects (the security review of task 4.6)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from strata import gitio
from strata.hosted import members as members_mod
from strata.hosted.instance import InstanceError, check_remote_url
from tests.integration._hosted import hosted, make_instance, push_to_bare, seed_review


def test_a_symbolic_link_pushed_to_the_remote_is_checked_out_as_a_plain_file(
    tmp_path: Path,
) -> None:
    seed = seed_review(tmp_path, records=2)
    link = seed.root / "protocol" / "question.md"
    link.unlink(missing_ok=True)
    os.symlink("../../instance/secrets.key", link)
    gitio.add_all(seed.root)
    gitio.commit(
        seed.root, "test: a link out of the project\n\nStrata-Op: test\nStrata-Actor: ethan\n"
    )
    bare = push_to_bare(seed, tmp_path / "remote.git")
    instance = make_instance(tmp_path)

    instance.add_project("spacing", remote=str(bare))

    checked_out = instance.project_dir("spacing") / "protocol" / "question.md"
    assert not checked_out.is_symlink()
    assert checked_out.read_text(encoding="utf-8") == "../../instance/secrets.key"
    assert gitio.get_config(instance.project_dir("spacing"), "core.symlinks") == "false"


def test_an_instance_refuses_a_project_that_already_has_a_symbolic_link(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    root = world.instance.project_dir("spacing")
    os.symlink("/etc/hostname", root / "protocol" / "leak.md")

    with pytest.raises(InstanceError, match="symbolic link"):
        world.instance.secure_project("spacing")


def test_the_only_lead_cannot_be_demoted_by_the_members_form(tmp_path: Path) -> None:
    world = hosted(tmp_path)
    (lead,) = members_mod.leads_of(world.instance, "spacing")

    with pytest.raises(members_mod.MembershipError, match="only lead"):
        members_mod.add_member(
            world.instance, "spacing", lead.username, actor=lead.actor, role="observer"
        )
    assert members_mod.membership(world.instance, "spacing", lead.username).role == "lead"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "url",
    ["ssh://deploy:hunter2@git.example.org/review.git", "https://token@git.example.org/r.git"],
)
def test_a_remote_url_with_a_credential_in_it_is_refused(url: str) -> None:
    with pytest.raises(InstanceError, match="user name or token"):
        check_remote_url(url)
