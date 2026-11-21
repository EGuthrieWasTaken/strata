"""SSH host keys for a project's remote: openspec:hosted-deployment#hosted-security-baseline and
openspec:hosted-deployment#instance-secrets-never-reach-a-repository.

When the instance reaches a project's remote over SSH it has to decide whether the machine that
answers is the git host. Two ways, chosen per project:

- **Trust on first use** (the default). The first connection with a deploy key remembers whatever
  key the host shows (`StrictHostKeyChecking=accept-new`) in `<data>/instance/known_hosts`, and a
  different key later is refused. Someone in the network path at that first clone could pose as the
  host, so the key it accepted is printed for the operator to compare with the one the host
  publishes.
- **Pinned.** The operator supplies the host's key (a `known_hosts` line, such as `ssh-keyscan -t
  ed25519 HOST` prints) when adding the project. Only that key is believed
  (`StrictHostKeyChecking=yes`, and no other known_hosts file), so there is no first use to be
  fooled at.

This module reads the keys an operator supplies, computes the fingerprint OpenSSH shows for a key,
reads back the key trust on first use accepted, and words what is said when a host shows a key that
is not the expected one. It runs no ssh itself.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from strata.hosted.errors import InstanceError

KEY_TYPES = frozenset(
    {
        "ssh-ed25519",
        "ssh-rsa",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "sk-ssh-ed25519@openssh.com",
        "sk-ecdsa-sha2-nistp256@openssh.com",
    }
)
_SSH_SCHEMES = ("ssh", "git+ssh", "ssh+git")
#: `[user@]host:path`, the short form git accepts for an SSH remote.
_SCP_LIKE = re.compile(r"^(?:[^@/\\\s]+@)?(?P<host>\[[^\]]+\]|[^:/\\\s]+):(?!//)")
_VERIFICATION_FAILED = ("host key verification failed", "remote host identification has changed")


@dataclass(frozen=True)
class HostKey:
    """One public key for one host. `host` is spelled as `known_hosts` spells it: the name, or
    `[name]:port` for a port other than 22."""

    host: str
    key_type: str
    key: str

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.key)

    @property
    def line(self) -> str:
        return f"{self.host} {self.key_type} {self.key}"


def fingerprint(key: str) -> str:
    """The fingerprint OpenSSH prints for a base64 public key: `SHA256:` and the unpadded base64
    of the SHA-256 of the key's bytes."""
    digest = hashlib.sha256(base64.b64decode(key)).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def ssh_host_of(url: str) -> tuple[str, int | None] | None:
    """The host (and port, if it names one) an SSH remote reaches; `None` for a remote that is not
    reached over SSH (https, a local path, `file://`)."""
    text = url.strip()
    if "://" in text:
        parts = urlsplit(text)
        if parts.scheme not in _SSH_SCHEMES or not parts.hostname:
            return None
        return parts.hostname, parts.port
    if text.startswith(("/", ".", "~")) or "\\" in text:
        return None
    match = _SCP_LIKE.match(text)
    return (match["host"].strip("[]"), None) if match else None


def known_hosts_host(host: str, port: int | None) -> str:
    """How `known_hosts` names a host: bare on port 22, `[host]:port` on any other."""
    return host if port in (None, 22) else f"[{host}]:{port}"


def _scan_command(host: str, port: int | None) -> str:
    option = f" -p {port}" if port not in (None, 22) else ""
    return f"ssh-keyscan -t ed25519{option} {host}"


def _not_a_host_key(raw: str, host: str, port: int | None) -> InstanceError:
    shown = raw.strip().splitlines()[0][:48] if raw.strip() else "(empty)"
    return InstanceError(
        f"{shown!r} is not a host key in known_hosts form, so nothing was pinned. Give it as "
        "`HOST KEYTYPE BASE64` (or just `KEYTYPE BASE64`), for example a line from "
        f"`{_scan_command(host, port)}`, and check its fingerprint with the git host's operator "
        "before trusting it."
    )


def parse_host_keys(lines: list[str], *, remote: str | None) -> list[HostKey]:
    """The keys an operator supplied for `remote`, each a `known_hosts` line (`HOST KEYTYPE BASE64
    [comment]`, or `KEYTYPE BASE64` with the host taken from the remote). A key that could never
    match what ssh is shown is refused, in words that say why and what to give instead."""
    target = ssh_host_of(remote) if remote else None
    if target is None:
        reason = (
            f"its remote ({remote}) is not an SSH address"
            if remote
            else "it has no remote at all, so there is no SSH address to check it against (it is "
            "not an SSH remote)"
        )
        raise InstanceError(
            f"A host key was given, but {reason}; the key would never be checked and was not "
            "stored. Host keys apply to remotes such as git@host:path or ssh://host/path; leave "
            "out --host-key otherwise (an https remote is checked by TLS)."
        )
    host, port = target
    expected = known_hosts_host(host, port)
    return [_parse_one(raw, host, port, expected) for raw in lines]


def _parse_one(raw: str, host: str, port: int | None, expected: str) -> HostKey:
    text = raw.strip()
    if "\n" in text:
        raise InstanceError(
            "This --host-key has more than one line, but each takes one key per option; repeat "
            "--host-key for each key, so no key is dropped without being noticed."
        )
    fields = text.split()
    if fields and fields[0].startswith("@"):
        raise InstanceError(
            f"The line starts with {fields[0]}, which marks a certificate authority or a revoked "
            "key rather than a host key, so it cannot be pinned. Give the host's own key, as "
            f"`{_scan_command(host, port)}` prints it."
        )
    if fields and fields[0].startswith("|"):
        raise InstanceError(
            "The host name in this line is hashed, so it cannot be checked against the remote "
            "and was not pinned. Give the host in plain text, as "
            f"`{_scan_command(host, port)}` prints it."
        )
    if fields and fields[0] in KEY_TYPES:
        named, rest = None, fields
    elif len(fields) >= 3:
        named, rest = fields[0], fields[1:]
    else:
        raise _not_a_host_key(raw, host, port)
    if len(rest) < 2 or rest[0] not in KEY_TYPES:
        raise _not_a_host_key(raw, host, port)
    key_type, key = rest[0], rest[1]
    try:
        blob = base64.b64decode(key, validate=True)
        (length,) = struct.unpack(">I", blob[:4])
        inside = blob[4 : 4 + length].decode("ascii")
    except (binascii.Error, struct.error, UnicodeDecodeError):
        raise _not_a_host_key(raw, host, port) from None
    if inside != key_type:
        raise InstanceError(
            f"The line says the key is {key_type}, but the key inside it is {inside}, so it was "
            f"not pinned. Copy the whole line as `{_scan_command(host, port)}` prints it."
        )
    if named is not None:
        names = [name.lower() for name in named.split(",")]
        if host.lower() not in names and expected.lower() not in names:
            raise InstanceError(
                f"This host key is for {named}, but the remote is at {host}, so ssh would never "
                f"accept it and nothing was pinned. Give the key of {host}: "
                f"`{_scan_command(host, port)}`, and check its fingerprint with the git host's "
                "operator."
            )
    return HostKey(host=expected, key_type=key_type, key=key)


def parse_stored(text: str) -> list[HostKey]:
    """The keys of a pin as the instance stores it: one `HOST KEYTYPE BASE64` line each."""
    keys = []
    for line in text.splitlines():
        host, key_type, key = line.split()[:3]
        keys.append(HostKey(host=host, key_type=key_type, key=key))
    return keys


def accepted_keys(known_hosts: Path, host: str, port: int | None) -> list[HostKey]:
    """The keys trust on first use has accepted for a host, read from the instance's known_hosts."""
    try:
        text = known_hosts.read_text(encoding="utf-8")
    except OSError:
        return []
    expected = known_hosts_host(host, port)
    found = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[1] not in KEY_TYPES or fields[0].startswith("|"):
            continue
        if expected in fields[0].split(","):
            found.append(HostKey(host=expected, key_type=fields[1], key=fields[2]))
    return found


def is_verification_failure(text: str) -> bool:
    """Whether ssh's output says it refused the host's key."""
    lowered = text.lower()
    return any(phrase in lowered for phrase in _VERIFICATION_FAILED)


def verification_failure_message(
    project_id: str,
    remote: str,
    *,
    pinned: list[HostKey],
    accepted: list[HostKey],
    during: str,
) -> str:
    """What is said when ssh refused a project's git host because of its key: what was refused,
    why, and what to do. `during` is `clone` (adding the project) or `sync`."""
    target = ssh_host_of(remote)
    host, port = target if target is not None else (remote, None)
    scan = _scan_command(host, port)
    pin = f"strata host project host-key {project_id} --host-key '<the line {scan} prints>'"
    outcome = (
        "nothing was cloned and the project was not added"
        if during == "clone"
        else "the project was not synced; what was recorded here is kept, and the sync is tried "
        "again later"
    )
    fixing = (
        "If you did not expect the host's key to change, someone may be impersonating the host: "
        "do not pin a new key. If it really did change, check the new key's fingerprint with the "
        "git host's operator, then "
    )
    fixing += (
        f"add the project again with `--host-key` set to the line `{scan}` prints."
        if during == "clone"
        else f"have an administrator of this instance pin it: `{pin}`."
    )
    if pinned:
        shown = ", ".join(key.fingerprint for key in pinned)
        why = (
            f"The git host {host} showed a host key that is not the one pinned for the project "
            f"{project_id!r} (pinned: {shown}), so ssh refused the connection and {outcome}."
        )
    elif accepted:
        shown = ", ".join(key.fingerprint for key in accepted)
        why = (
            f"The git host {host} showed a host key different from the one this instance "
            f"accepted when it first connected ({shown}), so ssh refused the connection for the "
            f"project {project_id!r} and {outcome}."
        )
    else:
        return (
            f"ssh could not check the host key of the git host {host} for the project "
            f"{project_id!r}: this instance has no key recorded for it, so ssh refused the "
            f"connection and {outcome}. Pin the host's key, after checking its fingerprint with "
            f"the git host's operator: "
            + (
                f"add the project again with `--host-key` set to the line `{scan}` prints."
                if during == "clone"
                else f"have an administrator of this instance run `{pin}`."
            )
        )
    return f"{why} {fixing}"
