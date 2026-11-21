"""SSH host keys: trust on first use stays the default, an operator can pin a project's key when
adding it, and the first clone says which key it accepted (openspec:hosted-deployment#hosted-security-baseline
and #instance-secrets-never-reach-a-repository; tasks 4.7 and 4.14).

There is no SSH client in the environment these run in, so a stand-in `ssh` is put first on `PATH`.
It records the options it is called with and the known_hosts file as it was at that moment, and
checks the host key it is shown the way the options it is given say OpenSSH would: refuse an unknown
or different key under `StrictHostKeyChecking=yes`, remember the first key under `accept-new` and
refuse a different one after. It then runs git's own command locally, so a clone really happens
through the same `GIT_SSH_COMMAND` the instance builds. What it cannot show is OpenSSH itself.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from strata.hosted import hostkeys
from strata.hosted.instance import Instance, InstanceError
from strata.hosted.syncloop import SyncLoop
from tests.integration._hosted import make_instance, push_to_bare, seed_review
from tests.integration.test_cli_host import _instance, host
from tests.unit.test_hosted_hostkeys import GITHUB_FINGERPRINT, GITHUB_KEY, make_key

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="a POSIX shell script stands in for ssh, as the instance runs where the container does",
)

HOST = "git.example.test"
GOOD = GITHUB_KEY
ROGUE = make_key(7)

FAKE_SSH = """#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path

args = sys.argv[1:]
options, positional, identity = {}, [], None
index = 0
while index < len(args):
    arg = args[index]
    if arg == "-o":
        name, _, value = args[index + 1].partition("=")
        options.setdefault(name, value)  # as ssh does: the first value given wins
        index += 2
    elif arg in ("-i", "-p", "-l", "-F"):
        if arg == "-i":
            identity = args[index + 1]
        index += 2
    elif arg.startswith("-"):
        index += 1
    else:
        positional.append(arg)
        index += 1
destination, command = positional[0], positional[1]
host = destination.rsplit("@", 1)[-1]
known = Path(options["UserKnownHostsFile"]) if "UserKnownHostsFile" in options else None
record = {
    "options": options,
    "identity": identity,
    "host": host,
    "known_hosts": known.read_text() if known is not None and known.exists() else None,
}
with open(os.environ["FAKE_SSH_LOG"], "a") as handle:
    handle.write(json.dumps(record) + "\\n")
presented = os.environ["FAKE_HOST_KEY"]  # "ssh-ed25519 AAAA..."


def trusted_for_host():
    if known is None or not known.exists():
        return []
    found = []
    for line in known.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and host in fields[0].split(","):
            found.append(" ".join(fields[1:3]))
    return found


strict = options.get("StrictHostKeyChecking", "ask")
trusted = trusted_for_host()
if strict == "accept-new" and not trusted:
    with known.open("a") as handle:
        handle.write(f"{host} {presented}\\n")
elif presented not in trusted:
    sys.stderr.write("Host key verification failed.\\n")
    sys.exit(255)
sys.exit(subprocess.call(["sh", "-c", command]))
"""


@dataclass
class FakeSsh:
    log: Path

    def calls(self) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def present(self, monkeypatch: pytest.MonkeyPatch, key: str) -> None:
        monkeypatch.setenv("FAKE_HOST_KEY", f"ssh-ed25519 {key}")


@pytest.fixture
def ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeSsh:
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    script = bin_dir / "ssh"
    script.write_text(FAKE_SSH, encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "ssh-calls.jsonl"
    monkeypatch.setenv("FAKE_SSH_LOG", str(log))
    fake = FakeSsh(log)
    fake.present(monkeypatch, GOOD)
    return fake


def _remote(tmp_path: Path) -> str:
    """An ssh-style address for a bare repository the stand-in `ssh` reaches locally."""
    bare = push_to_bare(seed_review(tmp_path), tmp_path / "remote.git")
    return f"git@{HOST}:{bare}"


def _ssh_address(bare: Path) -> str:
    return f"git@{HOST}:{bare}"


def _instance_with_key(tmp_path: Path) -> Instance:
    instance = make_instance(tmp_path)
    instance.secrets.put("deploy", "-----BEGIN OPENSSH PRIVATE KEY-----\nnot a real key\n")
    return instance


def _add(instance: Instance, remote: str, **options):  # type: ignore[no-untyped-def]
    return instance.add_project(
        "spacing", remote=remote, credential_kind="ssh-key", credential_secret="deploy", **options
    )


# ------------------------------------------------------- trust on first use, the default


def test_trust_on_first_use_stays_the_default_and_the_first_clone_reports_the_key(
    tmp_path: Path, ssh: FakeSsh
) -> None:
    instance = _instance_with_key(tmp_path)
    _add(instance, _remote(tmp_path))

    (first, *_) = ssh.calls()
    options = first["options"]
    assert options["StrictHostKeyChecking"] == "accept-new"  # type: ignore[index]
    assert options["UserKnownHostsFile"] == str(instance.state_dir / "known_hosts")  # type: ignore[index]
    assert options["HashKnownHosts"] == "no"  # type: ignore[index]  # so the accepted key can be read back
    assert first["identity"] is not None

    report = instance.host_key_report("spacing")
    assert report is not None and not report.pinned and report.host == HOST
    (key,) = report.keys
    assert key.fingerprint == hostkeys.fingerprint(GOOD) == GITHUB_FINGERPRINT
    assert instance.get_project("spacing").host_key is None  # type: ignore[union-attr]


def test_the_command_prints_the_accepted_keys_fingerprint_at_the_first_clone(
    tmp_path: Path, ssh: FakeSsh
) -> None:
    data, bare = _instance(tmp_path)
    Instance(data).secrets.put("deploy", "not a real key")

    out = host(
        data,
        "project",
        "add",
        "spacing",
        "--remote",
        _ssh_address(bare),
        "--credential",
        "ssh-key:deploy",
    )

    assert "added project spacing" in out
    assert HOST in out and GITHUB_FINGERPRINT in out and "ssh-ed25519" in out
    assert "first use" in out  # how it came to be trusted
    assert "compare" in out.lower() and "fingerprint" in out  # what to do with it
    payload = json.loads(host(data, "project", "host-key", "spacing", json_output=True))
    assert payload["pinned"] is False and payload["keys"][0]["fingerprint"] == GITHUB_FINGERPRINT


# ----------------------------------------------------------------------------- pinning


def test_a_pinned_key_is_the_only_one_ssh_will_accept(tmp_path: Path, ssh: FakeSsh) -> None:
    instance = _instance_with_key(tmp_path)
    line = f"{HOST} ssh-ed25519 {GOOD}"

    project = _add(instance, _remote(tmp_path), host_keys=[line + " scanned yesterday"])

    (call, *_) = ssh.calls()
    options = call["options"]
    assert options["StrictHostKeyChecking"] == "yes"  # type: ignore[index]
    assert options["GlobalKnownHostsFile"] == "/dev/null"  # type: ignore[index]  # nothing else is believed
    assert call["known_hosts"] == line + "\n"  # exactly the pinned key, at the moment ssh ran
    assert "accept-new" not in json.dumps(call)
    assert not (instance.state_dir / "known_hosts").exists()  # nothing was trusted on first use
    assert not list(instance.tmp_dir.glob("known-hosts-*"))  # the file made for the command is gone
    assert project.host_key == line and instance.get_project("spacing").host_key == line  # type: ignore[union-attr]
    report = instance.host_key_report("spacing")
    assert report is not None and report.pinned and report.keys[0].fingerprint == GITHUB_FINGERPRINT


def test_a_pinned_key_applies_without_a_deploy_key_too(tmp_path: Path, ssh: FakeSsh) -> None:
    instance = make_instance(tmp_path)
    instance.add_project("spacing", remote=_remote(tmp_path), host_keys=[f"ssh-ed25519 {GOOD}"])
    (call, *_) = ssh.calls()
    assert call["identity"] is None and call["options"]["StrictHostKeyChecking"] == "yes"  # type: ignore[index]
    assert call["known_hosts"] == f"{HOST} ssh-ed25519 {GOOD}\n"


def test_a_host_that_shows_another_key_than_the_pinned_one_is_refused_in_plain_words(
    tmp_path: Path, ssh: FakeSsh, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance_with_key(tmp_path)
    ssh.present(monkeypatch, ROGUE)

    with pytest.raises(InstanceError) as refused:
        _add(instance, _remote(tmp_path), host_keys=[f"{HOST} ssh-ed25519 {GOOD}"])

    message = str(refused.value)
    assert "spacing" in message and HOST in message  # what was refused
    assert "pinned" in message and GITHUB_FINGERPRINT in message  # why
    assert "impersonat" in message and "nothing was cloned" in message
    assert f"ssh-keyscan -t ed25519 {HOST}" in message and "--host-key" in message  # the fix
    assert "Host key verification failed" not in message  # said in words, not as ssh said it
    assert instance.get_project("spacing") is None and not instance.project_dir("spacing").exists()


def test_a_changed_key_after_the_first_clone_is_refused_at_the_next_sync_in_plain_words(
    tmp_path: Path, ssh: FakeSsh, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="strata.hosted")
    instance = _instance_with_key(tmp_path)
    _add(instance, _remote(tmp_path))  # trusted on first use
    ssh.present(monkeypatch, ROGUE)

    status = SyncLoop(instance).sync_now("spacing", "ethan")

    message = status.last_error
    assert message is not None
    assert "spacing" in message and HOST in message  # what was refused
    assert (
        "different" in message and GITHUB_FINGERPRINT in message
    )  # why: it is not the key accepted before
    assert "impersonat" in message
    assert "strata host project host-key spacing --host-key" in message  # what fixes it
    assert "Host key verification failed" not in message
    assert status.failures == 1 and status.next_retry is not None  # retried later, with backoff
    assert message in caplog.text  # the same words are in the log


def test_a_pinned_key_that_stops_matching_names_the_pin_in_the_sync_status(
    tmp_path: Path, ssh: FakeSsh, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _instance_with_key(tmp_path)
    _add(instance, _remote(tmp_path), host_keys=[f"{HOST} ssh-ed25519 {GOOD}"])
    ssh.present(monkeypatch, ROGUE)

    message = SyncLoop(instance).sync_now("spacing", "ethan").last_error

    assert message is not None and "pinned" in message and GITHUB_FINGERPRINT in message
    assert "strata host project host-key spacing --host-key" in message


# ----------------------------------------------------------------------- the commands


def test_the_command_pins_a_key_when_adding_a_project(tmp_path: Path, ssh: FakeSsh) -> None:
    data, bare = _instance(tmp_path)
    Instance(data).secrets.put("deploy", "not a real key")

    out = host(
        data, "project", "add", "spacing", "--remote", _ssh_address(bare), "--credential", "ssh-key:deploy",
        "--host-key", f"{HOST} ssh-ed25519 {GOOD}",
    )  # fmt: skip

    assert "pinned" in out and GITHUB_FINGERPRINT in out
    assert Instance(data).get_project("spacing").host_key == f"{HOST} ssh-ed25519 {GOOD}"  # type: ignore[union-attr]


def test_a_host_key_for_a_project_without_an_ssh_remote_is_refused_by_the_command(
    tmp_path: Path,
) -> None:
    data, bare = _instance(tmp_path)
    out = host(
        data,
        "project",
        "add",
        "spacing",
        "--remote",
        str(bare),
        "--host-key",
        f"{HOST} ssh-ed25519 {GOOD}",
        code=2,
    )
    assert "not an SSH" in out and "leave out --host-key" in out
    assert Instance(data).get_project("spacing") is None


def test_a_pin_can_be_set_shown_replaced_and_cleared_on_an_existing_project(
    tmp_path: Path, ssh: FakeSsh, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, bare = _instance(tmp_path)
    Instance(data).secrets.put("deploy", "not a real key")
    host(
        data,
        "project",
        "add",
        "spacing",
        "--remote",
        _ssh_address(bare),
        "--credential",
        "ssh-key:deploy",
    )
    ssh.present(
        monkeypatch, ROGUE
    )  # the host's key changed, and the operator has checked that it should

    shown = host(data, "project", "host-key", "spacing")
    assert "trusted on first use" in shown and GITHUB_FINGERPRINT in shown

    pinned = host(
        data, "project", "host-key", "spacing", "--host-key", f"{HOST} ssh-ed25519 {ROGUE}"
    )
    assert "pinned" in pinned and hostkeys.fingerprint(ROGUE) in pinned
    assert (
        SyncLoop(Instance(data)).sync_now("spacing", "ethan").last_error is None
    )  # it works again

    cleared = host(data, "project", "host-key", "spacing", "--clear")
    assert (
        "trust on first use" in cleared and Instance(data).get_project("spacing").host_key is None
    )  # type: ignore[union-attr]


def test_setting_a_pin_that_cannot_work_changes_nothing_and_says_why(
    tmp_path: Path, ssh: FakeSsh
) -> None:
    data, bare = _instance(tmp_path)
    Instance(data).secrets.put("deploy", "not a real key")
    host(
        data,
        "project",
        "add",
        "spacing",
        "--remote",
        _ssh_address(bare),
        "--credential",
        "ssh-key:deploy",
    )

    wrong_host = host(
        data,
        "project",
        "host-key",
        "spacing",
        "--host-key",
        f"other.example.test ssh-ed25519 {GOOD}",
        code=2,
    )
    assert (
        "other.example.test" in wrong_host
        and HOST in wrong_host
        and f"ssh-keyscan -t ed25519 {HOST}" in wrong_host
    )
    nonsense = host(data, "project", "host-key", "spacing", "--host-key", "not a key", code=2)
    assert "known_hosts" in nonsense
    assert host(data, "project", "host-key", "nope", code=2).count("no project called 'nope'") == 1
    assert Instance(data).get_project("spacing").host_key is None  # type: ignore[union-attr]
