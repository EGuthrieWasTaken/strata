"""Instance secrets and the git environment that uses them
(openspec:hosted-deployment#instance-secrets-never-reach-a-repository)."""

# ruff: noqa: E501

from __future__ import annotations

import os
from pathlib import Path

import pytest

from strata import gitio
from strata.hosted.secrets import (
    SecretError,
    SecretStore,
    env_name,
    generate_key,
    git_credential_env,
)
from strata.hosted.store import Store

DEPLOY_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAfakekeymaterial0123456789\n-----END OPENSSH PRIVATE KEY-----"


def _secrets(tmp_path: Path, environ: dict[str, str] | None = None) -> SecretStore:
    store = Store(tmp_path / "instance" / "instance.db")
    store.create()
    secrets = SecretStore(store, tmp_path / "instance" / "instance.key", environ=environ or {},
                          secrets_dir=tmp_path / "run-secrets")  # fmt: skip
    secrets.ensure_key()
    return secrets


def test_stored_secrets_are_encrypted_at_rest(tmp_path: Path) -> None:
    secrets = _secrets(tmp_path)
    secrets.put("spacing-token", "ghp_supersecretvalue")
    assert secrets.get("spacing-token") == "ghp_supersecretvalue"
    assert b"ghp_supersecretvalue" not in (tmp_path / "instance" / "instance.db").read_bytes()
    assert oct((tmp_path / "instance" / "instance.key").stat().st_mode & 0o777) == "0o600"
    assert secrets.stored_names() == ["spacing-token"]
    assert secrets.source("spacing-token") == "stored"
    # Another instance key cannot read it.
    other = SecretStore(
        secrets._store,
        tmp_path / "other.key",
        environ={"STRATA_INSTANCE_KEY": generate_key().decode()},
    )
    with pytest.raises(SecretError, match="cannot be decrypted"):
        other.get("spacing-token")


def test_operator_supplied_secrets_win_over_stored_ones(tmp_path: Path) -> None:
    (tmp_path / "run-secrets").mkdir()
    (tmp_path / "run-secrets" / "from-file").write_text("file-value\n")
    secrets = _secrets(tmp_path, {env_name("from-env"): "env-value"})
    secrets.put("from-file", "stored-value")
    assert secrets.get("from-env") == "env-value" and secrets.source("from-env") == "environment"
    assert secrets.get("from-file") == "file-value" and secrets.source("from-file") == "file"
    assert secrets.get("missing") is None and secrets.source("missing") is None
    assert env_name("oidc.github-client") == "STRATA_SECRET_OIDC_GITHUB_CLIENT"


def test_an_operator_key_means_no_key_file(tmp_path: Path) -> None:
    key = generate_key().decode()
    secrets = _secrets(tmp_path, {"STRATA_INSTANCE_KEY": key})
    assert not (tmp_path / "instance" / "instance.key").exists()
    secrets.put("x", "value")
    assert secrets.get("x") == "value"


def test_secret_names_and_values_are_checked(tmp_path: Path) -> None:
    secrets = _secrets(tmp_path)
    with pytest.raises(SecretError, match="invalid secret name"):
        secrets.put("../escape", "v")
    with pytest.raises(SecretError, match="cannot be empty"):
        secrets.put("empty", "")
    assert secrets.delete("never-there") is False


def test_a_deploy_key_reaches_git_through_its_environment_only_for_one_command(
    tmp_path: Path,
) -> None:
    """The deploy key is usable by git (ssh is called with it) and is gone afterwards."""
    secrets = _secrets(tmp_path)
    secrets.put("deploy-key", DEPLOY_KEY)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record = tmp_path / "ssh-called.txt"
    (fake_bin / "ssh").write_text(
        "#!/bin/sh\n"
        f'for a in "$@"; do echo "$a" >> {record}; done\n'
        'while [ "$1" != "-i" ]; do shift; done; cat "$(echo $2 | tr -d "\'")" >> '
        + str(record)
        + "\n"
        "exit 1\n"
    )
    (fake_bin / "ssh").chmod(0o755)
    repo = tmp_path / "repo"
    gitio.init(repo)
    gitio.run(["remote", "add", "origin", "ssh://git@example.invalid/review.git"], cwd=repo)
    tmp_dir = tmp_path / "instance" / "tmp"
    with git_credential_env(
        secrets, kind="ssh-key", secret="deploy-key", username=None, tmp_dir=tmp_dir
    ) as env:
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        env = {
            **env,
            "GIT_SSH_COMMAND": env["GIT_SSH_COMMAND"].replace("ssh ", f"{fake_bin}/ssh ", 1),
        }
        with gitio.environment(env):
            result = gitio.run(["fetch", "origin"], cwd=repo, check=False)
        assert result.returncode != 0
        assert len(list(tmp_dir.iterdir())) == 1
    called = record.read_text()
    assert "IdentitiesOnly=yes" in called and "AAAAfakekeymaterial0123456789" in called
    assert list(tmp_dir.iterdir()) == []  # the key file is removed after the command
    assert "AAAAfakekeymaterial" not in "".join(
        p.read_text(errors="ignore") for p in repo.rglob("*") if p.is_file()
    )


def test_a_token_is_answered_through_askpass(tmp_path: Path) -> None:
    secrets = _secrets(tmp_path)
    secrets.put("spacing-token", "ghp_tokenvalue")
    tmp_dir = tmp_path / "instance" / "tmp"
    with git_credential_env(
        secrets, kind="token", secret="spacing-token", username=None, tmp_dir=tmp_dir
    ) as env:
        askpass = Path(env["GIT_ASKPASS"])
        assert "ghp_tokenvalue" not in askpass.read_text()
        import subprocess

        merged = {**os.environ, **env}
        user = subprocess.run(
            [str(askpass), "Username for 'https://example'"],
            env=merged,
            capture_output=True,
            text=True,
        )
        password = subprocess.run(
            [str(askpass), "Password for 'https://x@example'"],
            env=merged,
            capture_output=True,
            text=True,
        )
        assert (
            user.stdout.strip() == "x-access-token" and password.stdout.strip() == "ghp_tokenvalue"
        )


def test_a_missing_credential_is_reported_by_name(tmp_path: Path) -> None:
    secrets = _secrets(tmp_path)
    with (
        pytest.raises(SecretError, match="STRATA_SECRET_NOT_THERE"),
        git_credential_env(
            secrets, kind="token", secret="not-there", username=None, tmp_dir=tmp_path / "t"
        ),
    ):
        pass
    with git_credential_env(
        secrets, kind=None, secret=None, username=None, tmp_dir=tmp_path / "t"
    ) as env:
        assert env == {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def test_gitio_environment_sets_author_and_committer_for_the_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    repo = tmp_path / "repo"
    gitio.init(repo)
    gitio.set_config(repo, "user.name", "Local Person")
    gitio.set_config(repo, "user.email", "local@example.org")
    (repo / "a.txt").write_text("a\n")
    gitio.add_all(repo)
    identity = gitio.identity_env(
        author=("Sam Okonkwo", "sam@example.org"), committer=("strata instance", "i@x")
    )
    with gitio.environment(identity):
        gitio.commit(repo, "first")
    (repo / "b.txt").write_text("b\n")
    gitio.add_all(repo)
    gitio.commit(repo, "second")
    assert gitio.log(repo, fmt="%an|%cn") == [
        "Local Person|Local Person",
        "Sam Okonkwo|strata instance",
    ]
