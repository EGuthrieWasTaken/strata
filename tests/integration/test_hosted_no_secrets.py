"""No secret is ever written into a review repository
(openspec:hosted-deployment#instance-secrets-never-reach-a-repository,
openspec:privacy-and-security#no-stored-credentials)."""

# ruff: noqa: E501

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from strata import gitio
from strata.core import records as records_mod
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.hosted.instance import InstanceError
from strata.web.hosted import HostedServer
from strata.web.security import parse_public_url
from tests.integration._hosted import (
    PASSWORD,
    PUBLIC_URL,
    FakeClock,
    csrf_from,
    make_instance,
    post,
    push_to_bare,
    seed_review,
    sign_in,
)

TOKEN = "ghp_REMOTE-TOKEN-0123456789abcdef"
DEPLOY_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nDEPLOYKEYMATERIAL0123456789\n-----END OPENSSH PRIVATE KEY-----"
OIDC_SECRET = "OIDC-CLIENT-SECRET-0123456789"


def _everything_git_holds(root: Path) -> bytes:
    """Every byte a repository holds or would hand on: its files, its config, and every object
    in its history (decompressed), reachable or not."""
    chunks = [p.read_bytes() for p in root.rglob("*") if p.is_file()]
    objects = subprocess.run(
        ["git", "cat-file", "--batch-all-objects", "--batch"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    chunks.append(objects.stdout)
    chunks.append(gitio.run(["config", "--list", "--show-origin"], cwd=root).stdout.encode())
    return b"\n".join(chunks)


def test_no_secret_is_ever_written_into_a_review_repository(tmp_path: Path) -> None:
    environ = {"STRATA_SECRET_SPACING_DEPLOY_KEY": DEPLOY_KEY}
    instance = make_instance(tmp_path, environ=environ)
    instance.secrets.put("spacing-token", TOKEN)
    instance.secrets.put("oidc-university", OIDC_SECRET)
    bare = push_to_bare(seed_review(tmp_path), tmp_path / "remote.git")
    other = push_to_bare(seed_review(tmp_path, "other-seed", first=50), tmp_path / "other.git")
    # One project authenticates with a token, the other with a deploy key from the operator.
    instance.add_project(
        "spacing", remote=str(bare), credential_kind="token", credential_secret="spacing-token"
    )
    instance.add_project(
        "trial",
        remote=str(other),
        credential_kind="ssh-key",
        credential_secret="spacing-deploy-key",
    )
    for username, actor, role in (("ethan.g", "ethan", "lead"), ("sam.okonkwo", "sam", "screener")):
        accounts.add_user(instance.store, username, password=PASSWORD)
        members_mod.add_member(instance, "spacing", username, actor=actor, role=role)
        members_mod.add_member(instance, "trial", username, actor=actor, role=role)
    api_token = accounts.create_api_token(instance.store, "sam.okonkwo", label="mcp")
    clock = FakeClock()
    server = HostedServer(
        instance, public_url=parse_public_url(PUBLIC_URL), background=False, clock=clock
    )
    from fastapi.testclient import TestClient

    from strata.web.hosted import create_hosted_app

    app = create_hosted_app(server)
    sam = sign_in(TestClient(app, base_url=PUBLIC_URL, follow_redirects=False), "sam.okonkwo")
    ethan = sign_in(TestClient(app, base_url=PUBLIC_URL, follow_redirects=False), "ethan.g")

    # A day's work: screening, a criteria edit, batches committed, syncs and pushes.
    for project in ("spacing", "trial"):
        repo = instance.open_project(project)
        for record in sorted(r["id"] for r in records_mod.read_records(repo)):
            assert (
                post(
                    sam,
                    "/screen/title-abstract",
                    {"record_id": record, "decision": "include"},
                    project=project,
                ).status_code
                == 303
            )
        server.sync.flush(project)
    post(
        ethan,
        "/criteria/EXC-01/edit",
        {
            "direction": "tightened",
            "definition": "Wrong population.",
            "rationale": "Rewording it now.",
        },
    )
    server.sync.run_due()
    pages = [sam.get(p).text for p in ("/", "/p/spacing/", "/p/spacing/-/sync", "/p/trial/-/sync")]
    pages.append(ethan.get("/p/spacing/-/members").text)

    secrets = [TOKEN, DEPLOY_KEY.splitlines()[1], OIDC_SECRET, PASSWORD, api_token]
    for project in ("spacing", "trial"):
        held = _everything_git_holds(instance.project_dir(project))
        for secret in secrets:
            assert secret.encode() not in held, (project, secret[:12])
    for remote in (bare, other):
        held = _everything_git_holds(remote)
        for secret in secrets:
            assert secret.encode() not in held
    # Nor is one displayed back in the interface.
    for page in pages:
        for secret in secrets:
            assert secret not in page
    # Instance state holds only hashes and ciphertext; the operator-supplied key is not stored.
    database = (instance.state_dir / "instance.db").read_bytes()
    for secret in secrets:
        assert secret.encode() not in database
    assert instance.secrets.get("spacing-token") == TOKEN
    assert (
        gitio.current_commit(instance.project_dir("spacing"))
        == gitio.run(["rev-parse", "main"], cwd=bare).stdout.strip()
    )


def test_a_remote_url_with_a_credential_in_it_is_refused(tmp_path: Path) -> None:
    instance = make_instance(tmp_path)
    with pytest.raises(InstanceError, match="user name or token in it"):
        instance.add_project(
            "spacing", remote="https://x-access-token:ghp_abc@github.com/lab/review.git"
        )
    assert not (instance.projects_dir / "spacing").exists()
    assert instance.list_projects() == []


def test_the_sign_in_page_never_echoes_a_password(tmp_path: Path) -> None:
    instance = make_instance(tmp_path)
    accounts.add_user(instance.store, "sam", password=PASSWORD)
    server = HostedServer(instance, public_url=parse_public_url(PUBLIC_URL), background=False)
    from fastapi.testclient import TestClient

    from strata.web.hosted import create_hosted_app

    client = TestClient(create_hosted_app(server), base_url=PUBLIC_URL, follow_redirects=False)
    page = client.get("/signin")
    refused = client.post(
        "/signin",
        data={
            "csrf_token": csrf_from(page.text),
            "username": "sam",
            "password": "my-typo-password",
        },
    )
    assert refused.status_code == 401 and "my-typo-password" not in refused.text
