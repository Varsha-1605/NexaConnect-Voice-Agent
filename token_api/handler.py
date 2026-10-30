"""AWS Lambda: gives a visitor a short-lived LiveKit token, after a Cloudflare Turnstile check.

POST /api/token   body: {"turnstile": "<token from the page>"}
                  -> {"url": "wss://...", "token": "<jwt>"}

Only the Python standard library is used, so the code can be pasted into the Lambda console.
Environment variables (encrypted): LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET,
TURNSTILE_SECRET, AGENT_NAME.
Optional: ALLOWED_ORIGIN, the address of the page when it is hosted somewhere else than this Lambda's own
domain (for example https://nexaconnect-web.pages.dev). Several can be given, separated by commas.
When the page and this Lambda share one address (CloudFront), leave it unset.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import uuid

TOKEN_LIFETIME_SECONDS = 10 * 60
MAX_BODY_BYTES = 4096
TURNSTILE_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_TIMEOUT_SECONDS = 3


def reply(status: int, body: dict, extra_headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store", **(extra_headers or {})},
        "body": json.dumps(body),
    }


def cors_headers(event: dict) -> dict:
    """Let the browser read the answer only when the request comes from an allowed page."""
    allowed = {item.strip() for item in os.environ.get("ALLOWED_ORIGIN", "").split(",") if item.strip()}
    origin = (event.get("headers") or {}).get("origin", "")
    if origin not in allowed:
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}


def log(event: str, **fields) -> None:
    # One JSON line per event, so CloudWatch can filter and count them. Never log the token or the visitor's IP.
    print(json.dumps({"event": event, **fields}))


def turnstile_passed(response_token: str, visitor_ip: str | None) -> bool:
    fields = {"secret": os.environ["TURNSTILE_SECRET"], "response": response_token}
    if visitor_ip:
        fields["remoteip"] = visitor_ip
    request = urllib.request.Request(TURNSTILE_URL, data=urllib.parse.urlencode(fields).encode())
    with urllib.request.urlopen(request, timeout=TURNSTILE_TIMEOUT_SECONDS) as response:
        return bool(json.load(response).get("success"))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(api_key: str, api_secret: str, room: str, identity: str, agent_name: str, now: int | None = None) -> str:
    """A LiveKit access token (an HS256 JWT): join one new room, publish the microphone and data, and have
    LiveKit send the named agent into the room."""
    now = int(time.time()) if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "iss": api_key,
        "sub": identity,
        "nbf": now,
        "exp": now + TOKEN_LIFETIME_SECONDS,
        "video": {
            "roomJoin": True,
            "room": room,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
            "canPublishSources": ["microphone"],
        },
        "roomConfig": {"agents": [{"agentName": agent_name}]},
    }
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(claims, separators=(',', ':')).encode())}"
    signature = hmac.new(api_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def lambda_handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    cors = cors_headers(event)
    if not http.get("path", "").endswith("/api/token"):
        return reply(404, {"error": "not found"})
    if http.get("method") == "OPTIONS":  # the browser's permission check before the real request
        if not cors:
            return reply(403, {"error": "origin not allowed"})
        return {
            "statusCode": 204,
            "headers": {**cors, "Access-Control-Allow-Methods": "POST", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400"},
        }
    if http.get("method") != "POST":
        return reply(404, {"error": "not found"})

    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", "replace")
    if len(body) > MAX_BODY_BYTES:
        return reply(413, {"error": "request too large"}, cors)
    try:
        turnstile_token = json.loads(body).get("turnstile")
    except (ValueError, AttributeError):
        turnstile_token = None
    if not isinstance(turnstile_token, str) or not turnstile_token:
        log("token_refused", reason="no_turnstile_token")
        return reply(400, {"error": "missing check"}, cors)

    forwarded = (event.get("headers") or {}).get("x-forwarded-for", "")
    visitor_ip = forwarded.split(",")[0].strip() or None
    try:
        passed = turnstile_passed(turnstile_token, visitor_ip)
    except Exception as error:  # Turnstile unreachable or slow: refuse, never let people through unchecked
        log("turnstile_unavailable", error=type(error).__name__)
        return reply(503, {"error": "check unavailable, please try again"}, cors)
    if not passed:
        log("token_refused", reason="turnstile_failed")
        return reply(403, {"error": "check failed"}, cors)

    token = make_token(
        os.environ["LIVEKIT_API_KEY"],
        os.environ["LIVEKIT_API_SECRET"],
        room=f"web-{uuid.uuid4().hex[:8]}",
        identity=f"customer-{uuid.uuid4().hex[:6]}",
        agent_name=os.environ["AGENT_NAME"],
    )
    log("token_issued")
    return reply(200, {"url": os.environ["LIVEKIT_URL"], "token": token}, cors)
