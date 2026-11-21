"""SSH host keys a project's remote may be pinned to (openspec:hosted-deployment#hosted-security-baseline
and #instance-secrets-never-reach-a-repository; tasks 4.7 and 4.14): reading a key the operator
supplies, its fingerprint, and what is said when it cannot be used."""

# ruff: noqa: E501

from __future__ import annotations

import base64
import struct

import pytest

from strata.hosted import hostkeys
from strata.hosted.instance import InstanceError

#: GitHub's published ed25519 host key and its published fingerprint: an independent check that the
#: fingerprint is computed as OpenSSH does.
GITHUB_KEY = "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
GITHUB_FINGERPRINT = "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"
REMOTE = "git@github.com:owner/review.git"


def make_key(seed: int, key_type: str = "ssh-ed25519") -> str:
    """A well-formed public key blob (not a usable key), as it appears in known_hosts."""
    name = key_type.encode()
    blob = struct.pack(">I", len(name)) + name + struct.pack(">I", 32) + bytes([seed]) * 32
    return base64.b64encode(blob).decode()


def test_the_fingerprint_is_the_one_openssh_prints() -> None:
    assert hostkeys.fingerprint(GITHUB_KEY) == GITHUB_FINGERPRINT


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:owner/repo.git", ("github.com", None)),
        ("github.com:owner/repo.git", ("github.com", None)),
        ("ssh://git@git.example.org/owner/repo.git", ("git.example.org", None)),
        ("ssh://git@git.example.org:2222/owner/repo.git", ("git.example.org", 2222)),
        ("git+ssh://git@git.example.org/r.git", ("git.example.org", None)),
        ("ssh://git@[2001:db8::1]:2200/r.git", ("2001:db8::1", 2200)),
        ("git@[2001:db8::1]:owner/r.git", ("2001:db8::1", None)),
        ("https://github.com/owner/repo.git", None),
        ("http://git.example.org/r.git", None),
        ("/srv/git/review.git", None),
        ("./review.git", None),
        ("file:///srv/git/review.git", None),
        ("C:\\repos\\review.git", None),
    ],
)
def test_which_host_an_ssh_remote_reaches(
    url: str, expected: tuple[str, int | None] | None
) -> None:
    assert hostkeys.ssh_host_of(url) == expected


def test_a_known_hosts_line_is_read_and_its_fingerprint_is_shown() -> None:
    (key,) = hostkeys.parse_host_keys(
        [f"github.com ssh-ed25519 {GITHUB_KEY} from ssh-keyscan"], remote=REMOTE
    )
    assert (key.host, key.key_type, key.key) == ("github.com", "ssh-ed25519", GITHUB_KEY)
    assert key.fingerprint == GITHUB_FINGERPRINT
    assert key.line == f"github.com ssh-ed25519 {GITHUB_KEY}"  # the comment is not kept


def test_the_host_may_be_left_out_and_is_taken_from_the_remote() -> None:
    (key,) = hostkeys.parse_host_keys([f"ssh-ed25519 {GITHUB_KEY}"], remote=REMOTE)
    assert key.line == f"github.com ssh-ed25519 {GITHUB_KEY}"


def test_a_port_other_than_22_is_written_the_way_known_hosts_wants_it() -> None:
    remote = "ssh://git@git.example.org:2222/r.git"
    for given in (
        f"git.example.org ssh-ed25519 {GITHUB_KEY}",
        f"[git.example.org]:2222 ssh-ed25519 {GITHUB_KEY}",
        f"ssh-ed25519 {GITHUB_KEY}",
    ):
        (key,) = hostkeys.parse_host_keys([given], remote=remote)
        assert key.line == f"[git.example.org]:2222 ssh-ed25519 {GITHUB_KEY}"


def test_several_keys_for_one_host_are_kept_together() -> None:
    keys = hostkeys.parse_host_keys(
        [
            f"github.com ssh-ed25519 {GITHUB_KEY}",
            f"github.com ecdsa-sha2-nistp256 {make_key(2, 'ecdsa-sha2-nistp256')}",
        ],
        remote=REMOTE,
    )
    assert [k.key_type for k in keys] == ["ssh-ed25519", "ecdsa-sha2-nistp256"]


def _refusal(lines: list[str], remote: str | None = REMOTE) -> str:
    with pytest.raises(InstanceError) as refused:
        hostkeys.parse_host_keys(lines, remote=remote)
    return str(refused.value)


def test_a_host_key_for_a_remote_that_is_not_ssh_says_why_it_is_pointless() -> None:
    for remote in ("https://github.com/owner/repo.git", None):
        message = _refusal([f"github.com ssh-ed25519 {GITHUB_KEY}"], remote)
        assert "host key" in message and "not an SSH" in message  # what and why
        assert "leave out --host-key" in message  # the fix


def test_a_host_key_for_another_host_names_both_and_says_how_to_get_the_right_one() -> None:
    message = _refusal([f"gitlab.com ssh-ed25519 {GITHUB_KEY}"])
    assert "gitlab.com" in message and "github.com" in message  # what it is for, what the remote is
    assert "ssh-keyscan -t ed25519 github.com" in message  # the fix
    assert "fingerprint" in message  # and to check what it returns


def test_a_line_that_is_not_a_host_key_says_what_one_looks_like() -> None:
    for bad in (
        "",
        "github.com",
        "github.com ssh-ed25519",
        "github.com ssh-nonsense AAAA",
        "github.com ssh-ed25519 !!!notbase64!!!",
    ):
        message = _refusal([bad])
        assert "host key" in message and "known_hosts" in message and "ssh-keyscan" in message, bad


def test_a_key_whose_type_does_not_match_its_contents_is_refused() -> None:
    message = _refusal([f"github.com ssh-rsa {GITHUB_KEY}"])  # the blob inside is ed25519
    assert "ssh-rsa" in message and "ssh-ed25519" in message and "ssh-keyscan" in message


def test_a_hashed_host_or_a_marker_cannot_be_checked_against_the_remote() -> None:
    hashed = _refusal([f"|1|c2FsdA==|aGFzaA== ssh-ed25519 {GITHUB_KEY}"])
    assert "hashed" in hashed and "plain" in hashed
    marker = _refusal([f"@cert-authority github.com ssh-ed25519 {GITHUB_KEY}"])
    assert "@cert-authority" in marker and "host key" in marker


def test_more_than_one_key_per_option_is_refused_by_line_not_silently_dropped() -> None:
    message = _refusal(
        [f"github.com ssh-ed25519 {GITHUB_KEY}\ngithub.com ssh-ed25519 {make_key(3)}"]
    )
    assert "one key per" in message
