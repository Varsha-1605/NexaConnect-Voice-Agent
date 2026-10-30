"""The token Lambda: refuses without a passed Turnstile check, and makes tokens LiveKit accepts."""

import json
from datetime import timedelta

import jwt
import pytest
from livekit import api

from token_api import handler

KEY, SECRET = "APIkeyexample", "s" * 40


@pytest.fixture(autouse=True)
def lambda_settings(monkeypatch):
    for name, value in {
        "LIVEKIT_URL": "wss://example.livekit.cloud",
        "LIVEKIT_API_KEY": KEY,
        "LIVEKIT_API_SECRET": SECRET,
        "TURNSTILE_SECRET": "turnstile-secret",
        "AGENT_NAME": "nexaconnect-ashley",
    }.items():
        monkeypatch.setenv(name, value)


def request(body="", method="POST", path="/api/token", **extra):
    return {"requestContext": {"http": {"method": method, "path": path}}, "body": body, "headers": {}, **extra}


def pass_check(monkeypatch, passed=True):
    monkeypatch.setattr(handler, "turnstile_passed", lambda token, ip: passed)


# ---------------------------------------------------------------- the token itself
def test_token_has_the_same_claims_as_one_made_by_the_livekit_sdk():
    mine = handler.make_token(KEY, SECRET, "web-1234abcd", "customer-abcdef", "nexaconnect-ashley", now=1_000_000)
    sdk = (
        api.AccessToken(KEY, SECRET)
        .with_identity("customer-abcdef")
        .with_grants(
            api.VideoGrants(
                room_join=True, room="web-1234abcd", can_publish=True, can_subscribe=True,
                can_publish_data=True, can_publish_sources=["microphone"],
            )
        )
        .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name="nexaconnect-ashley")]))
        .with_ttl(timedelta(minutes=10))
        .to_jwt()
    )
    options = {"verify_signature": False, "verify_exp": False, "verify_nbf": False}
    ours, theirs = (jwt.decode(t, options=options) for t in (mine, sdk))
    assert ours["video"] == theirs["video"]
    assert ours["roomConfig"] == theirs["roomConfig"]
    assert ours["iss"] == theirs["iss"] == KEY and ours["sub"] == theirs["sub"]
    assert ours["exp"] - ours["nbf"] == theirs["exp"] - theirs["nbf"] == 600


def test_livekit_accepts_the_token_signature():
    token = handler.make_token(KEY, SECRET, "web-1234abcd", "customer-abcdef", "nexaconnect-ashley")
    claims = api.TokenVerifier(KEY, SECRET).verify(token)
    assert claims.identity == "customer-abcdef" and claims.video.room == "web-1234abcd"


def test_a_token_signed_with_another_secret_is_rejected():
    token = handler.make_token(KEY, "x" * 40, "web-1", "customer-1", "nexaconnect-ashley")
    with pytest.raises(Exception):
        api.TokenVerifier(KEY, SECRET).verify(token)


# ---------------------------------------------------------------- the request
def test_valid_request_gets_a_token_and_the_livekit_url(monkeypatch):
    pass_check(monkeypatch)
    result = handler.lambda_handler(request(json.dumps({"turnstile": "ok"})), None)
    body = json.loads(result["body"])
    assert result["statusCode"] == 200 and result["headers"]["Cache-Control"] == "no-store"
    assert body["url"] == "wss://example.livekit.cloud" and body["token"].count(".") == 2


def test_every_request_gets_a_new_room_and_identity(monkeypatch):
    pass_check(monkeypatch)
    options = {"verify_signature": False}
    tokens = [json.loads(handler.lambda_handler(request('{"turnstile": "ok"}'), None)["body"])["token"] for _ in range(2)]
    first, second = (jwt.decode(t, options=options) for t in tokens)
    assert first["video"]["room"] != second["video"]["room"] and first["sub"] != second["sub"]


def test_failed_turnstile_check_is_refused(monkeypatch):
    pass_check(monkeypatch, passed=False)
    assert handler.lambda_handler(request('{"turnstile": "bad"}'), None)["statusCode"] == 403


def test_turnstile_outage_is_refused_not_waved_through(monkeypatch):
    def down(token, ip):
        raise TimeoutError

    monkeypatch.setattr(handler, "turnstile_passed", down)
    assert handler.lambda_handler(request('{"turnstile": "ok"}'), None)["statusCode"] == 503


@pytest.mark.parametrize("body", ["", "not json", "{}", '{"turnstile": ""}', '{"turnstile": 5}', "[]"])
def test_missing_or_broken_check_is_refused(monkeypatch, body):
    pass_check(monkeypatch)
    assert handler.lambda_handler(request(body), None)["statusCode"] == 400


def test_only_post_to_api_token_is_served(monkeypatch):
    pass_check(monkeypatch)
    assert handler.lambda_handler(request("{}", method="GET"), None)["statusCode"] == 404
    assert handler.lambda_handler(request("{}", path="/other"), None)["statusCode"] == 404


def test_oversized_body_is_refused(monkeypatch):
    pass_check(monkeypatch)
    assert handler.lambda_handler(request("x" * 5000), None)["statusCode"] == 413


def test_the_token_is_never_written_to_the_log(monkeypatch, capsys):
    pass_check(monkeypatch)
    token = json.loads(handler.lambda_handler(request('{"turnstile": "ok"}'), None)["body"])["token"]
    assert token not in capsys.readouterr().out
