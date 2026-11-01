"""The Zotero API client: `Backoff` and `Retry-After` are honoured, and errors say what happened
(openspec:zotero-integration#transport-selection; the rate limits in the change's design)."""

from __future__ import annotations

import pytest

from strata.integrations.zotero.api import (
    WEB_BASE_URL,
    ZoteroApi,
    ZoteroError,
    ZoteroNotFoundError,
    ZoteroPreconditionError,
    ZoteroUnavailableError,
)
from strata.integrations.zotero.http import HttpResponse
from tests.unit._zotero import Sleeper, local_api, web_api
from tests.zotero_fake import API_KEY, WEB_HOST, FakeZotero


def test_a_backoff_header_makes_the_next_request_wait_and_only_the_next() -> None:
    fake, sleeper = FakeZotero(), Sleeper()
    api = web_api(fake, sleeper)
    fake.backoff_after_next("7")

    api.get_json("/users/12345/collections")
    assert sleeper.waits == []  # the response that carried it is not delayed

    api.get_json("/users/12345/collections")
    assert sleeper.waits == [7.0]

    api.get_json("/users/12345/collections")
    assert sleeper.waits == [7.0]  # once told, once waited


def test_a_429_is_retried_after_the_time_retry_after_names() -> None:
    fake, sleeper = FakeZotero(), Sleeper()
    api = web_api(fake, sleeper)
    fake.throttle(2, retry_after="5")

    collections = api.get_json("/users/12345/collections")

    assert len(collections) == 4
    assert sleeper.waits == [5.0, 5.0]
    assert [r.path for r in fake.requests].count("/users/12345/collections") == 3


def test_a_429_without_retry_after_backs_off_exponentially() -> None:
    fake, sleeper = FakeZotero(), Sleeper()
    api = web_api(fake, sleeper)
    fake.throttle(3, retry_after="not-a-number")

    api.get_json("/users/12345/collections")

    assert sleeper.waits == [1.0, 2.0, 4.0]


def test_a_server_that_stays_busy_is_given_up_on_with_the_status() -> None:
    fake, sleeper = FakeZotero(), Sleeper()
    api = ZoteroApi(WEB_BASE_URL, fake, api_key=API_KEY, sleep=sleeper, max_retries=2)
    fake.throttle(99, retry_after="1")

    with pytest.raises(ZoteroError, match="still busy") as caught:
        api.get_json("/users/12345/collections")

    assert caught.value.status == 429
    assert len(sleeper.waits) == 2


def test_a_wait_longer_than_the_limit_is_refused_not_slept_through() -> None:
    fake, sleeper = FakeZotero(), Sleeper()
    api = web_api(fake, sleeper)
    fake.throttle(1, retry_after="86400")

    with pytest.raises(ZoteroError, match="asked for a wait of 86400 s"):
        api.get_json("/users/12345/collections")

    assert sleeper.waits == []


def test_an_unreachable_zotero_is_unavailable_not_a_crash() -> None:
    fake = FakeZotero(local_running=False)

    with pytest.raises(ZoteroUnavailableError, match="could not reach Zotero"):
        local_api(fake).get_json("/users/0/items/top")


@pytest.mark.parametrize(
    ("path", "error", "words"),
    [
        ("/users/999/collections", ZoteroNotFoundError, "no /users/999/collections"),
    ],
)
def test_error_statuses_become_errors_that_say_what_was_asked(
    path: str, error: type[ZoteroError], words: str
) -> None:
    with pytest.raises(error, match=words):
        web_api(FakeZotero()).get_json(path)


def test_a_wrong_key_says_the_key_is_the_likely_cause() -> None:
    with pytest.raises(ZoteroError, match="API key is missing, wrong, or lacks permission"):
        web_api(FakeZotero(), key="WRONG").get_json("/users/12345/collections")


def test_a_precondition_failure_is_its_own_error() -> None:
    class Precondition:
        def request(self, method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
            return HttpResponse(412, {}, b"changed")

    with pytest.raises(ZoteroPreconditionError):
        ZoteroApi(WEB_BASE_URL, Precondition()).request("POST", "/users/12345/items")


def test_the_key_is_sent_as_a_header_and_never_in_the_url() -> None:
    fake = FakeZotero()
    web_api(fake).get_json("/users/12345/collections")
    local_api(fake).get_json("/users/0/collections")

    web, local = fake.requests
    assert web.headers["zotero-api-key"] == API_KEY
    assert API_KEY not in web.path and API_KEY not in str(web.query)
    assert "zotero-api-key" not in local.headers
    assert web.headers["zotero-api-version"] == "3"
    assert web.host == WEB_HOST


def test_pages_are_read_until_one_comes_back_short() -> None:
    fake = FakeZotero()
    api = web_api(fake)

    pages = list(api.get_pages("/users/12345/collections", page_size=3))

    assert [len(p) for p in pages] == [3, 1]
    assert [r.query["start"] for r in fake.requests] == ["0", "3"]


def test_a_reply_that_is_not_json_is_an_error_not_a_crash() -> None:
    class Html:
        def request(self, method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
            return HttpResponse(200, {}, b"<html>captive portal</html>")

    with pytest.raises(ZoteroError, match="not JSON"):
        ZoteroApi(WEB_BASE_URL, Html()).get_json("/users/12345/collections")
