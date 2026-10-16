"""Browser authorization never exposes credentials across origins or starts a job."""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from local_encoder import desktop, server
from local_encoder.avideo_client import (
    AVideoAPIError,
    AVideoClient,
    LoginResult,
    ServerConfig,
    SiteStatus,
)

STATE = "a" * 32
CODE = "b" * 64
SITE = "https://video.test/subsite/"
client = TestClient(server.app, base_url="http://127.0.0.1:47800", headers={"X-Local-Encoder": "1"})


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_sessions", {})
    monkeypatch.setattr(server, "_browser_logins", {})


def mock_client() -> MagicMock:
    remote = MagicMock()
    remote.__enter__.return_value = remote
    remote.login_from_browser.return_value = LoginResult(
        True, True, "_user_hash_private", "alice", 7, categories=[{"id": 1, "name": "News"}]
    )
    remote.get_server_config.return_value = ServerConfig()
    remote.get_site_status.return_value = SiteStatus()
    return remote


def test_discovery_reveals_only_a_public_per_attempt_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = desktop.login_verifier(STATE)
    challenge = desktop.login_challenge(STATE)
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert challenge == expected and len(challenge) == 43
    assert desktop.login_challenge("c" * 32) != challenge
    response = client.get("/api/desktop", params={"state": STATE})
    assert response.json()["login_challenge"] == challenge
    assert verifier not in response.text
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/desktop?state=invalid").status_code == 400
    monkeypatch.setattr(desktop, "_LOGIN_KEY", b"different instance")
    assert desktop.login_challenge(STATE) != challenge


def test_authorization_only_acknowledges_then_the_local_page_claims_the_account() -> None:
    remote = mock_client()
    jobs_before = dict(server._jobs)
    with patch.object(server, "AVideoClient", return_value=remote) as constructor:
        reply = client.post(
            "/api/browser-login", json={"server_url": SITE, "code": CODE, "state": STATE}
        )
        assert reply.json() == {"ok": True}
        constructor.assert_called_once_with(SITE)
        remote.login_from_browser.assert_called_once_with(CODE, desktop.login_verifier(STATE))
        assert (
            client.post(
                "/api/browser-login/claim",
                json={"server_url": "https://other.test/", "state": STATE},
            ).json()["ok"]
            is False
        )
        result = client.post(
            "/api/browser-login/claim", json={"server_url": SITE, "state": STATE}
        ).json()
    assert result["ok"] is True and result["username"] == "alice" and result["user_id"] == 7
    assert result["site"]["url"] == SITE
    assert "private" not in str(result) and "pass" not in result
    assert server._sessions[result["session_id"]].ssl_verify is True
    assert (
        client.post("/api/browser-login/claim", json={"server_url": SITE, "state": STATE}).json()[
            "ok"
        ]
        is False
    )
    assert server._jobs == jobs_before


def test_unclaimed_authorization_expires() -> None:
    with patch.object(server, "AVideoClient", return_value=mock_client()):
        assert client.post(
            "/api/browser-login", json={"server_url": SITE, "code": CODE, "state": STATE}
        ).json()["ok"]
    with patch.object(server.time, "monotonic", return_value=time.monotonic() + 61):
        assert (
            client.post(
                "/api/browser-login/claim", json={"server_url": SITE, "state": STATE}
            ).json()["ok"]
            is False
        )


@pytest.mark.parametrize(
    "patch_data",
    [
        {"state": "bad"},
        {"code": "bad"},
        {"server_url": "file:///private"},
        {"server_url": "https://user:secret@video.test/"},
    ],
)
def test_invalid_requests_never_contact_a_site(patch_data: dict[str, str]) -> None:
    with patch.object(server, "AVideoClient") as constructor:
        result = client.post(
            "/api/browser-login",
            json={"server_url": SITE, "code": CODE, "state": STATE, **patch_data},
        )
        assert result.json()["ok"] is False
        constructor.assert_not_called()


def test_failures_do_not_leak_response_secrets_or_save_a_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    remote = mock_client()
    remote.login_from_browser.side_effect = AVideoAPIError(
        "private-response-credential",
        code="login_error",
        params={"detail": "private-response-credential"},
    )
    with patch.object(server, "AVideoClient", return_value=remote), caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/browser-login", json={"server_url": SITE, "code": CODE, "state": STATE}
        )
    assert response.json()["error_info"]["code"] == "browser_login"
    assert "private-response-credential" not in response.text + caplog.text
    assert server._sessions == {} and server._browser_logins == {}


def test_cross_origin_forms_cannot_authorize_or_claim() -> None:
    other = TestClient(server.app, base_url="http://127.0.0.1:47800")
    for endpoint in ("/api/browser-login", "/api/browser-login/claim"):
        assert (
            other.post(
                endpoint, json={"server_url": SITE, "state": STATE, "code": CODE}
            ).status_code
            == 403
        )
        assert (
            other.options(
                endpoint,
                headers={
                    "Origin": "https://other.test",
                    "Access-Control-Request-Headers": "X-Local-Encoder",
                },
            ).headers.get("access-control-allow-origin")
            is None
        )


def test_remote_exchange_uses_post_no_redirects_and_the_existing_encoded_login() -> None:
    grant = httpx.Response(
        200, json={"error": False, "user": "alice", "pass": "_user_hash_private"}
    )
    login = httpx.Response(
        200,
        json={
            "isLogged": True,
            "canUpload": True,
            "user": "alice",
            "pass": "_user_hash_refreshed",
            "id": 7,
        },
    )
    with (
        AVideoClient(SITE) as remote,
        patch.object(remote._http, "post", side_effect=[grant, login]) as post,
    ):
        result = remote.login_from_browser(CODE, "verifier")
    assert result.username == "alice" and result.encrypted_pass == "_user_hash_refreshed"
    assert post.call_args_list[0].args == (
        SITE + "plugin/CustomizeAdvanced/localEncoderLogin.json.php",
    )
    assert post.call_args_list[0].kwargs == {
        "data": {"action": "redeem", "code": CODE, "verifier": "verifier"},
        "follow_redirects": False,
    }
    assert post.call_args_list[1].kwargs["data"] == {
        "user": "alice",
        "pass": "_user_hash_private",
        "encodedPass": "1",
        "redirectUri": SITE,
    }


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, text="private-body"),
        httpx.Response(200, json={"error": True, "msg": "private-body"}),
        httpx.Response(302, headers={"Location": "https://other.test/private-body"}),
    ],
)
def test_missing_expired_and_redirecting_grants_fall_back_without_body_leak(
    response: httpx.Response,
) -> None:
    with (
        AVideoClient(SITE) as remote,
        patch.object(remote._http, "post", return_value=response) as post,
    ):
        with pytest.raises(AVideoAPIError) as error:
            remote.login_from_browser(CODE, "verifier")
        assert error.value.code == "browser_login" and "private-body" not in str(error.value)
        assert post.call_count == 1
