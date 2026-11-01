"""Transport selection: the local API first, probed rather than assumed, the Web API when it must be
(openspec:zotero-integration#transport-selection), pinned per Zotero major version."""

from __future__ import annotations

import pytest

from strata.integrations.zotero.api import ZoteroUnavailableError
from strata.integrations.zotero.connect import connect
from strata.integrations.zotero.credentials import ENV_VAR
from strata.integrations.zotero.probe import probe_local
from tests.unit._zotero import MemoryKeystore, Sleeper
from tests.zotero_fake import API_KEY, LOCAL_HOST, MAJOR_VERSIONS, WEB_HOST, FakeZotero


def _hosts(fake: FakeZotero) -> list[str]:
    return [r.host for r in fake.requests]


# ----------------------------------------------------------------------------------- the probe


def test_zotero_7_with_the_local_api_switched_on_is_usable() -> None:
    api, reason = probe_local(FakeZotero("7"))

    assert reason == ""
    assert api is not None
    assert api.library == "users/12345"  # the real account, not the local `users/0` alias


def test_zotero_6_has_no_local_api_and_the_reason_says_so() -> None:
    api, reason = probe_local(FakeZotero("6"))

    assert api is None
    assert "no local API" in reason and "Zotero 7" in reason


def test_a_local_api_that_is_switched_off_says_where_to_switch_it_on() -> None:
    api, reason = probe_local(FakeZotero("7", local_api_enabled=False))

    assert api is None
    assert "switched off" in reason and "Allow other applications" in reason


def test_zotero_not_running_is_reported_as_such() -> None:
    api, reason = probe_local(FakeZotero("7", local_running=False))

    assert api is None
    assert reason == "Zotero is not running on this computer"


def test_a_local_api_shaped_differently_from_what_strata_reads_is_not_used() -> None:
    api, reason = probe_local(FakeZotero("7", reshape_local=True))

    assert api is None
    assert "did not answer as Zotero's API does" in reason


# ------------------------------------------------------------------------- choosing a transport


@pytest.mark.parametrize("major", MAJOR_VERSIONS)
def test_the_local_api_is_used_when_the_app_offers_it_and_no_key_is_asked_for(major: str) -> None:
    fake = FakeZotero(major)
    store = MemoryKeystore(available_=True, secret=None)
    asked: list[str] = []

    connection = connect(
        "auto",
        store=store,
        environ={},
        prompt_key=lambda: asked.append("asked") or API_KEY,
        http=fake,
        sleep=Sleeper(),
    )

    if major == "7":
        assert connection.transport == "local"
        assert asked == [] and store.writes == []
        assert set(_hosts(fake)) == {LOCAL_HOST}  # nothing left the machine
        assert connection.notices == ()
    else:
        # Zotero 6 has no local API: the Web API is the only way in, and it needs a key.
        assert connection.transport == "web"
        assert asked == ["asked"] and store.writes == [API_KEY]
        assert connection.notices and "local API is not available" in connection.notices[0]


def test_a_missing_local_api_falls_back_to_the_web_api_with_a_key_from_the_environment() -> None:
    fake = FakeZotero("6")

    connection = connect(
        "auto",
        store=MemoryKeystore(available_=True),
        environ={ENV_VAR: API_KEY},
        http=fake,
        sleep=Sleeper(),
    )

    assert connection.transport == "web"
    assert connection.personal_library == "users/12345"
    assert connection.key_info is not None and connection.key_info.user_write
    assert WEB_HOST in _hosts(fake)


def test_a_key_is_never_asked_for_when_there_is_no_keychain_to_keep_it_in() -> None:
    fake = FakeZotero("6")
    asked: list[str] = []

    with pytest.raises(ZoteroUnavailableError, match=ENV_VAR):
        connect(
            "auto",
            store=MemoryKeystore(available_=False),
            environ={},
            prompt_key=lambda: asked.append("asked") or API_KEY,
            http=fake,
            sleep=Sleeper(),
        )

    assert asked == []


def test_a_key_read_from_the_environment_with_no_keychain_comes_with_a_notice() -> None:
    fake = FakeZotero("6")

    connection = connect(
        "auto",
        store=MemoryKeystore(available_=False),
        environ={ENV_VAR: API_KEY},
        http=fake,
        sleep=Sleeper(),
    )

    assert any("not being stored" in n for n in connection.notices)


def test_writing_always_goes_through_the_web_api_even_when_the_local_one_is_there() -> None:
    fake = FakeZotero("7")

    connection = connect(
        "auto",
        need_write=True,
        store=MemoryKeystore(available_=True, secret=API_KEY),
        environ={},
        http=fake,
        sleep=Sleeper(),
    )

    assert connection.transport == "web"
    assert LOCAL_HOST not in _hosts(fake)  # not even probed: the local API is read-only


def test_asking_for_the_local_api_alone_is_an_error_when_it_is_unavailable() -> None:
    with pytest.raises(ZoteroUnavailableError, match="Zotero 7 or later"):
        connect("local", http=FakeZotero("6"), sleep=Sleeper())


def test_asking_to_write_with_the_local_api_alone_is_refused() -> None:
    with pytest.raises(ZoteroUnavailableError, match="read-only"):
        connect("local", need_write=True, http=FakeZotero("7"), sleep=Sleeper())


def test_the_web_api_can_be_chosen_outright() -> None:
    fake = FakeZotero("7")

    connection = connect(
        "web",
        store=MemoryKeystore(available_=True, secret=API_KEY),
        environ={},
        http=fake,
        sleep=Sleeper(),
    )

    assert connection.transport == "web"
    assert LOCAL_HOST not in _hosts(fake)


def test_an_unknown_transport_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="transport must be one of"):
        connect("carrier-pigeon", http=FakeZotero(), sleep=Sleeper())


class _Scripted:
    """A server that answers every request with the same response."""

    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        from strata.integrations.zotero.http import HttpResponse

        self.response = HttpResponse(status, headers or {}, body)

    def request(self, method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
        return self.response


_ITEM = {"key": "AB3D9XYZ", "version": 1, "data": {}, "csljson": {}}


@pytest.mark.parametrize(
    ("server", "words"),
    [
        (_Scripted(500, b"boom"), "answered with an error"),
        (_Scripted(200, b"[]", {"zotero-api-version": "2"}), "speaks Zotero API v2"),
        (_Scripted(200, b"<html>"), "the reply is not JSON"),
        (_Scripted(200, b'{"items": []}'), "no list of items"),
        (_Scripted(200, b'[{"key": "A", "version": 1}]'), "does not provide items with their CSL"),
    ],
    ids=["server-error", "other-api-version", "not-json", "not-a-list", "no-csljson"],
)
def test_a_local_api_that_answers_oddly_is_not_used_and_says_why(
    server: _Scripted, words: str
) -> None:
    api, reason = probe_local(server)

    assert api is None and words in reason


def test_an_empty_library_is_usable_and_is_the_local_users_library() -> None:
    api, reason = probe_local(_Scripted(200, b"[]"))

    assert reason == "" and api is not None and api.library == "users/0"


def test_an_account_less_zotero_reports_the_local_users_library() -> None:
    import json

    item = {**_ITEM, "library": {"type": "user", "id": 0}}

    api, _ = probe_local(_Scripted(200, json.dumps([item]).encode()))

    assert api is not None and api.library == "users/0"
