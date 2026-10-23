from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx

from loki_constants import get_loki_home
from utils import atomic_json_write, warn_if_credential_file_broadly_readable

DEFAULT_SSO_DOMAIN = "https://auth.wundercorp.co"
DEFAULT_CLIENT_ID = "5kg855gamgk38cicro6pfbglcu"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:48741/auth/callback"
DEFAULT_SCOPE = "openid email profile"
DEFAULT_LOGIN_TIMEOUT_SECONDS = 300
TOKEN_REFRESH_SKEW_SECONDS = 120


class WunderCorpSSOError(RuntimeError):
    pass


def sso_domain() -> str:
    return os.getenv("LOKI_WUNDERCORP_SSO_DOMAIN", DEFAULT_SSO_DOMAIN).rstrip("/")


def sso_client_id() -> str:
    return os.getenv("LOKI_WUNDERCORP_SSO_CLIENT_ID", DEFAULT_CLIENT_ID).strip() or DEFAULT_CLIENT_ID


def sso_redirect_uri() -> str:
    return os.getenv("LOKI_WUNDERCORP_SSO_REDIRECT_URI", DEFAULT_REDIRECT_URI).strip() or DEFAULT_REDIRECT_URI


def sso_scope() -> str:
    return os.getenv("LOKI_WUNDERCORP_SSO_SCOPE", DEFAULT_SCOPE).strip() or DEFAULT_SCOPE


def sso_state_path() -> Path:
    return get_loki_home() / "wundercorp-sso.json"


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        value = json.loads(decoded.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _load_state() -> dict[str, Any]:
    path = sso_state_path()
    warn_if_credential_file_broadly_readable(path, label="WunderCorp SSO")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    path = sso_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, state, mode=0o600, sort_keys=True)


def _delete_state() -> None:
    try:
        sso_state_path().unlink()
    except FileNotFoundError:
        pass


def _token_expiration(token: str) -> int:
    value = _decode_jwt_payload(token).get("exp")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _state_matches_client(state: dict[str, Any]) -> bool:
    state_client_id = state.get("_client_id")
    if isinstance(state_client_id, str) and state_client_id and state_client_id != sso_client_id():
        return False
    access_token = state.get("access_token")
    if isinstance(access_token, str) and access_token:
        token_client_id = _decode_jwt_payload(access_token).get("client_id")
        if isinstance(token_client_id, str) and token_client_id and token_client_id != sso_client_id():
            return False
    return True


def _access_token_usable(state: dict[str, Any], *, skew_seconds: int = TOKEN_REFRESH_SKEW_SECONDS) -> bool:
    access_token = state.get("access_token")
    if not isinstance(access_token, str) or not access_token or not _state_matches_client(state):
        return False
    claims = _decode_jwt_payload(access_token)
    if claims.get("token_use") not in (None, "access"):
        return False
    expiration = _token_expiration(access_token)
    return bool(expiration and expiration > int(time.time()) + skew_seconds)


def _identity_from_state(state: dict[str, Any]) -> dict[str, str]:
    claims: dict[str, Any] = {}
    id_token = state.get("id_token")
    if isinstance(id_token, str) and id_token:
        claims = _decode_jwt_payload(id_token)
    if not claims:
        access_token = state.get("access_token")
        if isinstance(access_token, str) and access_token:
            claims = _decode_jwt_payload(access_token)
    result: dict[str, str] = {}
    for source, target in (("email", "email"), ("cognito:username", "username"), ("username", "username"), ("sub", "subject")):
        value = claims.get(source)
        if isinstance(value, str) and value and target not in result:
            result[target] = value
    return result


def sso_status() -> dict[str, Any]:
    state = _load_state()
    access_token = state.get("access_token")
    refresh_token = state.get("refresh_token")
    expiration = _token_expiration(access_token) if isinstance(access_token, str) else 0
    state_matches_client = _state_matches_client(state)
    return {
        "signed_in": bool(state_matches_client and (_access_token_usable(state, skew_seconds=0) or (isinstance(refresh_token, str) and refresh_token))),
        "access_token_valid": _access_token_usable(state, skew_seconds=0),
        "expires_at": expiration or None,
        **_identity_from_state(state),
    }


def _token_request(data: dict[str, str], *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{sso_domain()}/oauth2/token",
            data=data,
            headers={"content-type": "application/x-www-form-urlencoded", "accept": "application/json"},
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise WunderCorpSSOError(f"WunderCorp SSO token request failed: {exc}") from exc
    if response.status_code >= 400:
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("error_description") or payload.get("error") or "")
        except Exception:
            pass
        suffix = f": {detail}" if detail else ""
        raise WunderCorpSSOError(f"WunderCorp SSO token request returned HTTP {response.status_code}{suffix}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise WunderCorpSSOError("WunderCorp SSO token response was not JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
        raise WunderCorpSSOError("WunderCorp SSO token response did not contain an access token")
    return payload


def refresh_sso_session(*, timeout_seconds: float = 20.0) -> str | None:
    state = _load_state()
    if not _state_matches_client(state):
        return None
    refresh_token = state.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return None
    try:
        payload = _token_request({
            "grant_type": "refresh_token",
            "client_id": sso_client_id(),
            "refresh_token": refresh_token,
        }, timeout_seconds=timeout_seconds)
    except WunderCorpSSOError:
        return None
    state.update(payload)
    if not state.get("refresh_token"):
        state["refresh_token"] = refresh_token
    state["_client_id"] = sso_client_id()
    state["updated_at"] = int(time.time())
    _save_state(state)
    access_token = state.get("access_token")
    return access_token if isinstance(access_token, str) and access_token else None


def _authorization_url(state: str, code_challenge: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": sso_client_id(),
        "response_type": "code",
        "redirect_uri": sso_redirect_uri(),
        "scope": sso_scope(),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{sso_domain()}/oauth2/authorize?{query}"


def login_sso(*, open_browser: bool = True, timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS) -> dict[str, Any]:
    redirect = urllib.parse.urlparse(sso_redirect_uri())
    if redirect.scheme != "http" or redirect.hostname not in {"127.0.0.1", "localhost"} or not redirect.port:
        raise WunderCorpSSOError("WunderCorp SSO redirect URI must be a local HTTP callback with an explicit port")

    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    result: dict[str, str] = {}
    callback_path = redirect.path or "/"

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            parameters = urllib.parse.parse_qs(parsed.query)
            if parameters.get("state", [None])[0] != state:
                result["error"] = "Invalid OAuth state"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid OAuth state")
                return
            if "error" in parameters:
                result["error"] = parameters.get("error_description", parameters["error"])[0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"WunderCorp authentication failed")
                return
            code = parameters.get("code", [None])[0]
            if not code:
                result["error"] = "No authorization code received"
                self.send_response(400)
                self.end_headers()
                return
            result["code"] = code
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b'<!doctype html><html><body style="font-family:system-ui;padding:40px">'
                b'<h2>WunderCorp sign-in complete</h2><p>You can close this window and return to LokiAgent.</p>'
                b'</body></html>'
            )

        def log_message(self, format: str, *args: Any) -> None:
            return

    try:
        server = HTTPServer((redirect.hostname, redirect.port), CallbackHandler)
    except OSError as exc:
        raise WunderCorpSSOError(f"Could not listen on {redirect.hostname}:{redirect.port}: {exc}") from exc
    server.timeout = 1.0
    authorization_url = _authorization_url(state, challenge)
    if open_browser:
        webbrowser.open(authorization_url)
    deadline = time.monotonic() + timeout_seconds
    try:
        while "code" not in result and "error" not in result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "error" in result:
        raise WunderCorpSSOError(result["error"])
    if "code" not in result:
        raise WunderCorpSSOError("WunderCorp sign-in timed out")

    payload = _token_request({
        "grant_type": "authorization_code",
        "client_id": sso_client_id(),
        "code": result["code"],
        "redirect_uri": sso_redirect_uri(),
        "code_verifier": verifier,
    })
    payload["_client_id"] = sso_client_id()
    payload["updated_at"] = int(time.time())
    _save_state(payload)
    return payload


def get_sso_access_token(*, interactive: bool = False, force_refresh: bool = False) -> str | None:
    state = _load_state()
    if not force_refresh and _access_token_usable(state):
        token = state.get("access_token")
        return token if isinstance(token, str) else None
    refreshed = refresh_sso_session()
    if refreshed:
        return refreshed
    if not interactive:
        return None
    state = login_sso()
    token = state.get("access_token")
    return token if isinstance(token, str) and token else None


def logout_sso() -> None:
    state = _load_state()
    refresh_token = state.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        try:
            httpx.post(
                f"{sso_domain()}/oauth2/revoke",
                data={"token": refresh_token, "client_id": sso_client_id()},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
        except httpx.HTTPError:
            pass
    _delete_state()


def format_sso_status() -> str:
    status = sso_status()
    if not status["signed_in"]:
        return "WunderCorp SSO: signed out\nRun /sso login or /link connect to sign in."
    identity = status.get("email") or status.get("username") or status.get("subject") or "signed-in account"
    token_state = "active" if status["access_token_valid"] else "refresh available"
    return f"WunderCorp SSO: signed in as {identity}\nSession: {token_state}"
