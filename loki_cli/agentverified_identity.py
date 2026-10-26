"""AgentVerified ID lifecycle helpers used by Loki's /id command.

The holder private key is generated locally and never sent to AgentVerified.  Remote
requests only contain the public JWK or signatures produced by the holder key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from loki_constants import get_loki_home

DEFAULT_API_URL = "https://agentverified.sh/v1"
DEFAULT_ISSUER_URL = "https://id.agentverified.sh"
OPENID4VCI_GRANT = "urn:ietf:params:oauth:grant-type:pre-authorized_code"
CREDENTIAL_CONFIGURATION_ID = "AgentVerifiedAgentCredential"


class AgentVerifiedIdentityError(RuntimeError):
    """A user-facing /id lifecycle failure."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_avid(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("qpid_"):
        return "avid_" + text[5:]
    return text


def _display_assurance(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("qpid") and text[4:].isdigit():
        return f"Level {text[4:]}"
    if text.startswith("avid") and text[4:].isdigit():
        return f"Level {text[4:]}"
    return text or "unknown"


def _private_fields(jwk: dict[str, Any]) -> set[str]:
    return {key for key in ("d", "p", "q", "dp", "dq", "qi", "oth", "k") if key in jwk}


def public_jwk(private_jwk: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in private_jwk.items() if key not in _private_fields(private_jwk)}


def generate_es256_jwk() -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate a P-256 holder key and RFC 7638 thumbprint-backed kid."""
    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.private_numbers()
    pub = numbers.public_numbers
    x = _b64url(pub.x.to_bytes(32, "big"))
    y = _b64url(pub.y.to_bytes(32, "big"))
    thumbprint_input = json.dumps(
        {"crv": "P-256", "kty": "EC", "x": x, "y": y},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    kid = _b64url(hashlib.sha256(thumbprint_input).digest())
    common = {"kty": "EC", "crv": "P-256", "x": x, "y": y, "alg": "ES256", "use": "sig", "kid": kid}
    private = {**common, "d": _b64url(numbers.private_value.to_bytes(32, "big"))}
    return common, private


def _ec_private_key(private_jwk: dict[str, Any]):
    if private_jwk.get("kty") != "EC" or private_jwk.get("crv") != "P-256" or not private_jwk.get("d"):
        raise AgentVerifiedIdentityError("The stored AgentVerified holder key is not a P-256 private JWK")
    value = int.from_bytes(_b64url_decode(str(private_jwk["d"])), "big")
    return ec.derive_private_key(value, ec.SECP256R1())


def _sign_openid_proof(private_jwk: dict[str, Any], nonce: str, issuer: str) -> str:
    return jwt.encode(
        {"nonce": nonce, "aud": issuer.rstrip("/"), "iat": int(time.time())},
        _ec_private_key(private_jwk),
        algorithm="ES256",
        headers={"typ": "openid4vci-proof+jwt", "jwk": public_jwk(private_jwk)},
    )




def _sign_enrollment_token_proof(private_jwk: dict[str, Any], device_code: str) -> str:
    now = int(time.time())
    device_hash = _b64url(hashlib.sha256(device_code.encode("utf-8")).digest())
    return jwt.encode(
        {
            "device_code_hash": device_hash,
            "aud": "agentverified-agent-enrollment-token",
            "iat": now,
            "exp": now + 300,
            "jti": str(uuid.uuid4()),
        },
        _ec_private_key(private_jwk),
        algorithm="ES256",
        headers={"alg": "ES256", "kid": private_jwk.get("kid"), "typ": "agentverified-agent-enrollment+jwt"},
    )


def identity_dir() -> Path:
    """Return the AgentVerified identity directory, migrating the legacy path once."""
    root = get_loki_home() / "identity"
    current = root / "agentverified"
    legacy = root / "quantpay"
    if legacy.exists() and not current.exists():
        root.mkdir(parents=True, exist_ok=True)
        try:
            legacy.replace(current)
        except OSError:
            # Preserve access to an existing profile if a filesystem-level move is unavailable.
            return legacy
    return current


def _ensure_identity_dir() -> Path:
    path = identity_dir()
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def state_path() -> Path:
    return identity_dir() / "state.json"


def key_path() -> Path:
    return identity_dir() / "holder.jwk"


def credential_path() -> Path:
    return identity_dir() / "credential.json"


def management_token_path() -> Path:
    return identity_dir() / "management-token.json"


def _atomic_private_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_identity_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentVerifiedIdentityError(f"Could not read {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _load_management_token() -> dict[str, Any]:
    record = _load_json(management_token_path())
    token = str(record.get("access_token") or "").strip()
    if not token:
        return {}
    try:
        expires_in = int(record.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    received_at = str(record.get("received_at") or "").strip()
    if expires_in > 0 and received_at:
        try:
            received = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc).timestamp() >= received.timestamp() + expires_in:
                try:
                    management_token_path().unlink()
                except FileNotFoundError:
                    pass
                return {}
        except ValueError:
            pass
    return record


def load_state() -> dict[str, Any]:
    state = _load_json(state_path())
    legacy = state.pop("qpid", None)
    if not state.get("avid") and legacy:
        state["avid"] = _canonical_avid(legacy)
        save_state(state)
    elif state.get("avid"):
        canonical = _canonical_avid(state.get("avid"))
        if canonical != state.get("avid"):
            state["avid"] = canonical
            save_state(state)
    return state


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    _atomic_private_json(state_path(), state)


def ensure_holder_key() -> tuple[dict[str, Any], dict[str, Any]]:
    existing = _load_json(key_path())
    if existing:
        if _private_fields(existing) != {"d"}:
            raise AgentVerifiedIdentityError("Stored AgentVerified holder JWK is malformed")
        return public_jwk(existing), existing
    public, private = generate_es256_jwk()
    _atomic_private_json(key_path(), private)
    return public, private


def _existing_holder_key() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the existing holder key without ever generating a replacement."""
    existing = _load_json(key_path())
    if not existing:
        raise AgentVerifiedIdentityError(
            "Existing AgentVerified holder key is missing. Refusing to reconnect with a new key."
        )
    if _private_fields(existing) != {"d"}:
        raise AgentVerifiedIdentityError("Stored AgentVerified holder JWK is malformed")
    return public_jwk(existing), existing


@dataclass
class AgentVerifiedClient:
    api_url: str
    issuer_url: str
    access_token: str = ""
    api_key: str = ""
    organization_id: str = ""

    @classmethod
    def from_env(cls) -> "AgentVerifiedClient":
        # Use Loki's scope-aware secret reader so multiplexed gateway profiles do not
        # leak credentials across homes, and ~/.loki/.env works without shell exports.
        from loki_cli.config import get_env_value

        def value(name: str, default: str = "") -> str:
            resolved = get_env_value(name)
            return (resolved if resolved is not None else default).strip()

        token_record = _load_management_token()
        local_management_token = str(token_record.get("access_token") or "").strip()
        return cls(
            api_url=(value("AGENTVERIFIED_API_URL") or value("AGENTVERIFIED_API_URL", DEFAULT_API_URL)).rstrip("/"),
            issuer_url=(value("AGENTVERIFIED_IDENTITY_ISSUER_URL") or value("AGENTVERIFIED_IDENTITY_ISSUER_URL", DEFAULT_ISSUER_URL)).rstrip("/"),
            access_token=value("AGENTVERIFIED_ACCESS_TOKEN") or value("AGENTVERIFIED_ACCESS_TOKEN") or local_management_token,
            api_key=value("AGENTVERIFIED_API_KEY") or value("AGENTVERIFIED_API_KEY"),
            organization_id=value("AGENTVERIFIED_ORGANIZATION_ID") or value("AGENTVERIFIED_ORGANIZATION_ID"),
        )

    @property
    def authenticated(self) -> bool:
        return bool(self.access_token or self.api_key)

    def require_management_auth(self) -> None:
        if not self.authenticated:
            raise AgentVerifiedIdentityError(
                "AgentVerified identity is waiting for approval. Run /id start to create an enrollment, approve it in "
                "AgentVerified, then run /id continue. Human Cognito bearer tokens are not required in Loki."
            )

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        elif self.api_key:
            headers["x-api-key"] = self.api_key
        if self.organization_id:
            headers["x-organization-id"] = self.organization_id
        return headers

    def request(self, method: str, path: str, *, json_body: Any = None) -> dict[str, Any]:
        if not self.authenticated:
            raise AgentVerifiedIdentityError(
                "AgentVerified agent management authorization is not available. Run /id start, approve the enrollment in "
                "AgentVerified, then run /id continue. Human Cognito bearer tokens are not required in Loki."
            )
        try:
            response = httpx.request(
                method,
                f"{self.api_url}{path}",
                headers=self._headers(),
                json=json_body,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise AgentVerifiedIdentityError(f"AgentVerified request failed: {exc}") from exc
        if response.status_code in {401, 422} and self.access_token.startswith("qpe_"):
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                payload = {}
            detail = str(payload.get("error_description") or payload.get("message") or payload.get("error") or "") if isinstance(payload, dict) else ""
            if "Invalid agent enrollment token" in detail or "expired" in detail.lower():
                try:
                    management_token_path().unlink()
                except FileNotFoundError:
                    pass
                self.access_token = ""
                raise AgentVerifiedIdentityError(
                    "AgentVerified management session expired. Local identity and holder credential remain intact."
                )
        return _decode_response(response, "AgentVerified ID")

    def public_request(self, method: str, path: str, *, json_body: Any = None) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.api_url}{path}",
                headers={"accept": "application/json"},
                json=json_body,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise AgentVerifiedIdentityError(f"AgentVerified enrollment request failed: {exc}") from exc
        return _decode_response(response, "AgentVerified enrollment")

    def issuer_request(self, method: str, path: str, *, json_body: Any = None,
                       bearer: str = "") -> dict[str, Any]:
        headers = {"accept": "application/json"}
        if bearer:
            headers["authorization"] = f"Bearer {bearer}"
        try:
            response = httpx.request(
                method,
                f"{self.issuer_url}{path}",
                headers=headers,
                json=json_body,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise AgentVerifiedIdentityError(f"AgentVerified issuer request failed: {exc}") from exc
        return _decode_response(response, "AgentVerified credential issuer")


def _decode_response(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("error_description") or payload.get("message") or payload.get("error") or "")
        suffix = f": {detail}" if detail else ""
        raise AgentVerifiedIdentityError(f"{label} returned HTTP {response.status_code}{suffix}")
    return payload if isinstance(payload, dict) else {"data": payload}


def _assurance_rank(value: str) -> int:
    try:
        return int(str(value).lower().removeprefix("qpid").removeprefix("avid"))
    except ValueError:
        return 0


def _get_agent(client: AgentVerifiedClient, state: dict[str, Any]) -> dict[str, Any]:
    agent_id = state.get("agent_id")
    if not agent_id:
        raise AgentVerifiedIdentityError("No local AgentVerified identity exists yet. Run /id start.")
    agent = client.request("GET", f"/agents/{agent_id}")
    state["avid"] = _canonical_avid(agent.get("avid") or agent.get("qpid") or state.get("avid"))
    state["assurance"] = agent.get("assurance", state.get("assurance", "qpid1"))
    save_state(state)
    return agent


def _format_status(client: AgentVerifiedClient, state: dict[str, Any]) -> str:
    if not state.get("agent_id"):
        if state.get("enrollment_device_code"):
            remote_status = "pending"
            if state.get("enrollment_user_code"):
                try:
                    remote = client.public_request("GET", f"/agent-enrollments/{state['enrollment_user_code']}")
                    remote_status = str(remote.get("status") or "pending")
                except AgentVerifiedIdentityError:
                    remote_status = "pending"
            if remote_status in {"expired", "canceled"}:
                mode = str(state.get("enrollment_mode") or "enroll")
                _clear_pending_enrollment(state)
                save_state(state)
                command = "/id reconnect" if mode == "reconnect" else "/id start"
                return f"AgentVerified ID: authorization {remote_status}. Run {command} to create a fresh pairing."
            next_step = (
                "Approval received. Run /id continue to finish reconnecting."
                if state.get("enrollment_mode") == "reconnect" and remote_status == "approved"
                else "Approval received. Run /id continue to claim the scoped agent token."
                if remote_status == "approved"
                else "After approval, run /id continue."
            )
            flow = "reconnect" if state.get("enrollment_mode") == "reconnect" else "enrollment"
            return (
                f"AgentVerified ID: {flow} {remote_status}\n"
                f"Pairing code: {state.get('enrollment_user_code', 'unknown')}\n"
                f"Approve: {state.get('enrollment_url', 'approval link unavailable')}\n"
                f"{next_step}\n"
                f"Holder key: {key_path()} (private, local only)"
            )
        return (
            "AgentVerified ID: not initialized\n"
            "Run /id start to generate Loki's holder key and create a secure AgentVerified enrollment.\n"
            "The private holder key stays under Loki home and is never sent to AgentVerified."
        )

    agent: dict[str, Any] = {}
    credentials: list[Any] | None = None
    remote_note = ""
    if client.authenticated:
        try:
            agent = client.request("GET", f"/agents/{state['agent_id']}")
            remote_avid = _canonical_avid(agent.get("avid") or agent.get("qpid"))
            if remote_avid and state.get("avid") and remote_avid != str(state["avid"]):
                raise AgentVerifiedIdentityError("Remote Agent ID does not match the locally stored identity")
            state["avid"] = _canonical_avid(agent.get("avid") or agent.get("qpid") or state.get("avid"))
            state["assurance"] = agent.get("assurance", state.get("assurance"))
            credentials = client.request("GET", f"/agents/{state['agent_id']}/credentials").get("items", [])
            save_state(state)
        except AgentVerifiedIdentityError as exc:
            message = str(exc)
            if "Invalid agent enrollment token" in message or "management session expired" in message.lower():
                try:
                    management_token_path().unlink()
                except FileNotFoundError:
                    pass
                client.access_token = ""
                remote_note = (
                    "\nManagement connection: inactive\n"
                    "Run /id reconnect to reconnect Loki to this AgentVerified ID."
                )
            else:
                remote_note = f"\nRemote status unavailable: {exc}"
    else:
        remote_note = (
            "\nManagement connection: inactive\n"
            "Run /id reconnect to reconnect Loki to this AgentVerified ID."
        )

    assurance = str(agent.get("assurance") or state.get("assurance") or "qpid1")
    credential_saved = credential_path().exists()
    lines = [
        "AgentVerified ID",
        f"Agent ID: {state.get('avid', 'unknown')}",
        f"Assurance: {_display_assurance(assurance)}",
        f"Holder key: {key_path()} (private, local only)",
        f"Verification session: {state.get('verification_session_id', 'not started')}",
        f"Active credentials: {sum(1 for item in credentials if item.get('status') == 'active') if credentials is not None else 'unavailable'}",
        f"Identity credential saved: {'yes' if credential_saved else 'no'}",
    ]
    if _assurance_rank(assurance) < 2 and state.get("verification_url"):
        lines += ["", f"Complete identity verification: {state['verification_url']}", "Then run /id continue."]
    elif _assurance_rank(assurance) >= 2 and not credential_saved:
        lines += ["", "Next: /id continue to obtain the holder-bound AgentVerified credential."]
    elif credential_saved:
        lines += ["", "Identity ready."]
    return "\n".join(lines) + remote_note

def _clear_pending_enrollment(state: dict[str, Any]) -> None:
    for key in (
        "enrollment_device_code", "enrollment_user_code", "enrollment_surface",
        "enrollment_url", "enrollment_personal_url", "enrollment_wallet_url", "enrollment_console_url",
        "enrollment_expires_at_epoch", "enrollment_mode", "reconnect_expected_agent_id",
        "reconnect_expected_avid",
    ):
        state.pop(key, None)


def _store_enrollment_result(
    state: dict[str, Any], result: dict[str, Any], *, surface: str, mode: str
) -> None:
    expires_in = int(result.get("expiresIn") or 900)
    state.update({
        "version": max(int(state.get("version") or 0), 3),
        "enrollment_device_code": result.get("deviceCode"),
        "enrollment_user_code": result.get("userCode"),
        "enrollment_surface": surface,
        "enrollment_mode": mode,
        "enrollment_url": result.get("verificationUriComplete"),
        "enrollment_personal_url": result.get("walletVerificationUriComplete") or result.get("verificationUriComplete"),
        "enrollment_wallet_url": result.get("walletVerificationUriComplete"),
        "enrollment_console_url": result.get("consoleVerificationUriComplete"),
        "enrollment_expires_at_epoch": time.time() + expires_in,
        "created_at": state.get("created_at") or _utc_now(),
    })
    if not state.get("enrollment_device_code") or not state.get("enrollment_user_code"):
        raise AgentVerifiedIdentityError("AgentVerified authorization did not return a device/user code")
    save_state(state)


def _start(client: AgentVerifiedClient, name: str, surface: str = "wallet") -> str:
    state = load_state()
    if state.get("agent_id"):
        return (
            "AgentVerified ID already exists.\n"
            f"Agent ID: {state.get('avid', 'unknown')}\n"
            "Run /id reconnect to restore management access, or /id status to inspect the identity."
        )

    public, _private = ensure_holder_key()
    enrollment = state.get("enrollment_device_code")
    enrollment_expires_at = float(state.get("enrollment_expires_at_epoch") or 0)
    if enrollment and state.get("enrollment_mode") not in {None, "enroll"}:
        _clear_pending_enrollment(state)
        save_state(state)
        enrollment = None
        enrollment_expires_at = 0
    if enrollment and enrollment_expires_at > time.time() and state.get("enrollment_user_code"):
        try:
            remote = client.public_request("GET", f"/agent-enrollments/{state['enrollment_user_code']}")
            if str(remote.get("status") or "") in {"expired", "canceled"}:
                _clear_pending_enrollment(state)
                save_state(state)
                enrollment = None
        except AgentVerifiedIdentityError:
            pass
    if not enrollment or enrollment_expires_at <= time.time():
        if enrollment_expires_at <= time.time():
            _clear_pending_enrollment(state)
        result = client.public_request("POST", "/agent-enrollments", json_body={
            "name": name or "Loki Agent",
            "surface": "console" if surface == "console" else "wallet",
            "publicKeyJwk": public,
        })
        _store_enrollment_result(state, result, surface=surface, mode="enroll")

    preferred = state.get("enrollment_url") or state.get("enrollment_personal_url") or state.get("enrollment_wallet_url") or state.get("enrollment_console_url")
    return (
        "AgentVerified ID enrollment started.\n"
        f"Pairing code: {state.get('enrollment_user_code')}\n"
        f"Approve this Loki agent: {preferred}\n\n"
        f"Personal approval: {state.get('enrollment_personal_url') or state.get('enrollment_wallet_url', 'unavailable')}\n"
        f"Business approval: {state.get('enrollment_console_url', 'unavailable')}\n\n"
        f"Holder key: {key_path()} (mode 0600; never uploaded)\n"
        "Sign in and approve in AgentVerified. If identity verification is needed, the web flow opens it. "
        "Then run /id continue. No human bearer token needs to be copied into Loki."
    )


def _reconnect(client: AgentVerifiedClient, surface: str = "wallet") -> str:
    state = load_state()
    agent_id = str(state.get("agent_id") or "")
    avid = str(state.get("avid") or "")
    if not agent_id or not avid:
        raise AgentVerifiedIdentityError("No existing AgentVerified ID to reconnect. Run /id start first.")

    public, _private = _existing_holder_key()

    # A valid management token means there is nothing to reconnect. A stale token
    # is discarded before the public reconnect ceremony begins.
    if client.authenticated:
        try:
            remote = client.request("GET", f"/agents/{agent_id}")
            remote_avid = _canonical_avid(remote.get("avid") or remote.get("qpid"))
            if remote_avid and remote_avid != avid:
                raise AgentVerifiedIdentityError("Remote Agent ID does not match the locally stored identity")
            return (
                "AgentVerified management connection is already active.\n"
                f"Agent ID: {avid}\nIdentity ready."
            )
        except AgentVerifiedIdentityError as exc:
            message = str(exc)
            if "Invalid agent enrollment token" not in message and "management session expired" not in message.lower():
                raise
            try:
                management_token_path().unlink()
            except FileNotFoundError:
                pass
            client.access_token = ""

    enrollment = state.get("enrollment_device_code")
    enrollment_expires_at = float(state.get("enrollment_expires_at_epoch") or 0)
    if enrollment and state.get("enrollment_mode") != "reconnect":
        _clear_pending_enrollment(state)
        save_state(state)
        enrollment = None
        enrollment_expires_at = 0
    if enrollment and enrollment_expires_at > time.time() and state.get("enrollment_user_code"):
        try:
            remote = client.public_request("GET", f"/agent-enrollments/{state['enrollment_user_code']}")
            if str(remote.get("status") or "") in {"expired", "canceled"}:
                _clear_pending_enrollment(state)
                save_state(state)
                enrollment = None
        except AgentVerifiedIdentityError:
            pass

    if not enrollment or enrollment_expires_at <= time.time():
        if enrollment_expires_at <= time.time():
            _clear_pending_enrollment(state)
        result = client.public_request("POST", "/agent-enrollments", json_body={
            "mode": "reconnect",
            "name": "Loki Agent",
            "surface": "console" if surface == "console" else "wallet",
            "agentId": agent_id,
            "avid": avid,
            "publicKeyJwk": public,
        })
        state["reconnect_expected_agent_id"] = agent_id
        state["reconnect_expected_avid"] = avid
        _store_enrollment_result(state, result, surface=surface, mode="reconnect")

    preferred = state.get("enrollment_url") or state.get("enrollment_personal_url") or state.get("enrollment_wallet_url") or state.get("enrollment_console_url")
    return (
        "AgentVerified reconnect started.\n"
        f"Agent ID: {avid}\n"
        f"Pairing code: {state.get('enrollment_user_code')}\n"
        f"Approve reconnect: {preferred}\n\n"
        f"Holder key: {key_path()} (existing key; never replaced or uploaded)\n"
        "Approve the connection in AgentVerified, then run /id continue. "
        "This reconnect does not create a new Agent ID or repeat identity verification."
    )

def _exchange_enrollment(client: AgentVerifiedClient, state: dict[str, Any]) -> str | None:
    mode = str(state.get("enrollment_mode") or "enroll")
    if client.authenticated and state.get("agent_id") and mode != "reconnect":
        return "active"
    device_code = str(state.get("enrollment_device_code") or "")
    if not device_code:
        return None
    _public, private = _existing_holder_key() if mode == "reconnect" else ensure_holder_key()
    holder_proof = _sign_enrollment_token_proof(private, device_code)
    result = client.public_request(
        "POST", "/agent-enrollments/token",
        json_body={"deviceCode": device_code, "holderProof": holder_proof},
    )
    status = str(result.get("status") or "")
    if status == "authorization_pending":
        verb = "reconnect" if mode == "reconnect" else "enrollment"
        raise AgentVerifiedIdentityError(
            f"Agent {verb} is waiting for human approval. Open {state.get('enrollment_url', 'the AgentVerified approval link')} "
            "and then run /id continue again."
        )
    if status in {"expired", "canceled"}:
        _clear_pending_enrollment(state)
        save_state(state)
        command = "/id reconnect" if mode == "reconnect" else "/id start"
        raise AgentVerifiedIdentityError(f"Agent authorization is {status}. Run {command} again.")
    token = str(result.get("accessToken") or "")
    if status != "approved" or not token:
        raise AgentVerifiedIdentityError("AgentVerified approval did not return a scoped agent token")

    if mode == "reconnect":
        expected_agent_id = str(state.get("reconnect_expected_agent_id") or state.get("agent_id") or "")
        expected_avid = str(state.get("reconnect_expected_avid") or state.get("avid") or "")
        returned_agent_id = str(result.get("agentId") or "")
        returned_avid = _canonical_avid(result.get("avid") or result.get("qpid"))
        if not returned_agent_id or not returned_avid:
            raise AgentVerifiedIdentityError("Reconnect response did not identify the existing AgentVerified ID")
        if returned_agent_id != expected_agent_id or returned_avid != expected_avid:
            _clear_pending_enrollment(state)
            save_state(state)
            raise AgentVerifiedIdentityError(
                "Reconnect identity mismatch. Refusing to replace the locally stored AgentVerified ID."
            )

    _atomic_private_json(management_token_path(), {
        "access_token": token,
        "token_type": result.get("tokenType", "Bearer"),
        "expires_in": result.get("expiresIn"),
        "received_at": _utc_now(),
    })

    if mode == "reconnect":
        state["management_reconnected_at"] = _utc_now()
        _clear_pending_enrollment(state)
        save_state(state)
        client.access_token = token
        return "reconnect"

    _clear_pending_enrollment(state)
    state.update({
        "agent_id": result.get("agentId"),
        "avid": _canonical_avid(result.get("avid") or result.get("qpid")),
        "assurance": result.get("assurance", "qpid1"),
        "verification_session_id": result.get("verificationSessionId"),
        "enrollment_approved_at": _utc_now(),
    })
    save_state(state)
    client.access_token = token
    return "enroll"

def _active_credential(client: AgentVerifiedClient, agent_id: str) -> dict[str, Any] | None:
    items = client.request("GET", f"/agents/{agent_id}/credentials").get("items", [])
    return next((item for item in items if isinstance(item, dict) and item.get("status") == "active"), None)


def _continue(client: AgentVerifiedClient) -> str:
    state = load_state()
    pending_mode = str(state.get("enrollment_mode") or "")
    if pending_mode == "reconnect":
        _public, private = _existing_holder_key()
    else:
        _public, private = ensure_holder_key()
    exchange_result: str | None = None
    if not state.get("agent_id") or not client.authenticated or pending_mode == "reconnect":
        exchange_result = _exchange_enrollment(client, state)
        if not exchange_result:
            command = "/id reconnect" if state.get("agent_id") else "/id start"
            raise AgentVerifiedIdentityError(f"No pending AgentVerified authorization. Run {command} first.")
    client.require_management_auth()
    agent = _get_agent(client, state)
    if exchange_result == "reconnect":
        returned_avid = _canonical_avid(agent.get("avid") or agent.get("qpid") or state.get("avid"))
        if returned_avid != str(state.get("avid") or ""):
            raise AgentVerifiedIdentityError("Reconnect verification returned a different AgentVerified ID")
        return (
            "AgentVerified management connection restored.\n"
            f"Agent ID: {state.get('avid')}\n"
            "Existing identity, holder key, assurance, and credential were not changed.\n"
            "Identity ready."
        )
    credential = _active_credential(client, str(state["agent_id"]))
    # Credential issuance is a separate authoritative step from Stripe/webhook reconciliation.
    # If verification is already marked verified but the credential has not been issued yet,
    # issue it now regardless of the cached/current assurance value. This makes /id continue
    # safe to repeat across races and partial runs.
    if credential is None:
        verification_id = state.get("verification_session_id")
        if not verification_id:
            raise AgentVerifiedIdentityError("KYA has not started. Run /id start first.")
        try:
            credential = client.request(
                "POST", f"/agents/{state['agent_id']}/kya",
                json_body={"verificationSessionId": verification_id},
            )
        except AgentVerifiedIdentityError as exc:
            if "verified KYC or KYB session is required" in str(exc):
                verification = client.request(
                    "POST", f"/agents/{state['agent_id']}/kya/stripe",
                    json_body={"requireMatchingSelfie": True},
                )
                resumed_id = verification.get("verificationSessionId")
                resumed_url = verification.get("verificationUrl")
                resumed_status = str(verification.get("status") or "requires_input")
                if resumed_id:
                    state["verification_session_id"] = resumed_id
                if resumed_url:
                    state["verification_url"] = resumed_url
                save_state(state)
                if resumed_status == "verified" and resumed_id:
                    credential = client.request(
                        "POST", f"/agents/{state['agent_id']}/kya",
                        json_body={"verificationSessionId": resumed_id},
                    )
                else:
                    url = state.get("verification_url")
                    return (
                        "Stripe KYA is ready to continue.\n"
                        f"Verification URL: {url or 'temporarily unavailable'}\n"
                        + ("Open it with /id open, complete verification, then run /id continue again." if url else
                           "AgentVerified could not recover a hosted URL yet; run /id continue again shortly.")
                    )
            else:
                raise
        state["credential_id"] = credential.get("id")
        state["assurance"] = credential.get("assurance", "qpid2")
        save_state(state)
    if credential is None or not credential.get("id"):
        raise AgentVerifiedIdentityError("Verified identity is active but no AgentVerified credential was found")
    state["credential_id"] = credential["id"]
    state["assurance"] = credential.get("assurance", state.get("assurance", "qpid2"))
    if credential_path().exists():
        save_state(state)
        return (
            f"AgentVerified credential already holder-bound and saved.\nAgent ID: {state.get('avid')}\n"
            f"Assurance: {_display_assurance(state.get('assurance'))}\nIdentity ready."
        )

    offer = client.request(
        "POST", f"/agents/{state['agent_id']}/credentials/{credential['id']}/offer", json_body=None,
    )
    offer_body = offer.get("credentialOffer") or {}
    grant = (offer_body.get("grants") or {}).get(OPENID4VCI_GRANT) or {}
    preauth = grant.get("pre-authorized_code")
    if not preauth:
        raise AgentVerifiedIdentityError("OpenID4VCI offer did not contain a pre-authorized code")
    token = client.issuer_request("POST", "/oid4vci/token", json_body={
        "grant_type": OPENID4VCI_GRANT,
        "pre-authorized_code": preauth,
    })
    access_token = token.get("access_token")
    if not access_token:
        raise AgentVerifiedIdentityError("OpenID4VCI token response did not contain an access token")
    nonce_result = client.issuer_request("POST", "/oid4vci/nonce", json_body={})
    nonce = nonce_result.get("c_nonce")
    if not nonce:
        raise AgentVerifiedIdentityError("OpenID4VCI nonce response did not contain c_nonce")
    proof = _sign_openid_proof(private, str(nonce), client.issuer_url)
    issued = client.issuer_request(
        "POST", "/oid4vci/credential", bearer=str(access_token), json_body={
            "credential_configuration_id": CREDENTIAL_CONFIGURATION_ID,
            "proofs": {"jwt": [proof]},
        },
    )
    credentials = issued.get("credentials") or []
    if not credentials or not isinstance(credentials[0], dict) or "credential" not in credentials[0]:
        raise AgentVerifiedIdentityError("OpenID4VCI credential response did not contain a credential")
    _atomic_private_json(credential_path(), credentials[0])
    state["openid4vci_issuance_session_id"] = offer.get("issuanceSessionId")
    state["credential_received_at"] = _utc_now()
    save_state(state)
    return (
        "AgentVerified credential issued and holder proof verified.\n"
        f"Agent ID: {state.get('avid')}\nAssurance: {_display_assurance(state.get('assurance'))}\n"
        f"Credential: {credential_path()}\nIdentity ready."
    )


def _doctor(client: AgentVerifiedClient) -> str:
    checks: list[str] = []
    for label, path in (
        ("JWKS", "/.well-known/jwks.json"),
        ("OpenID4VCI", "/.well-known/openid-credential-issuer"),
        ("OAuth", "/.well-known/oauth-authorization-server"),
    ):
        try:
            payload = client.issuer_request("GET", path)
            checks.append(f"{label}: ok ({len(payload)} top-level fields)")
        except AgentVerifiedIdentityError as exc:
            checks.append(f"{label}: FAILED ({exc})")
    return "AgentVerified ID doctor\n" + "\n".join(checks)


_HELP = """AgentVerified ID for Loki
/id status                 Show local + live AgentVerified identity state
/id start [name]           First-time browser enrollment only
/id start --console [name] Use the business/admin approval surface for first enrollment
/id reconnect              Reconnect Loki to the existing AgentVerified ID
/id reconnect --console    Use the business/admin approval surface for reconnect
/id continue               Finish the pending enrollment or reconnect authorization
/id doctor                 Check public AgentVerified issuer/discovery endpoints
/id open                   Reprint the pending AgentVerified approval URL
/id help                   Show this help

/id reconnect never creates a new Agent ID, replaces the holder key, or repeats identity verification.
Private holder key: stored mode 0600 under Loki home; never uploaded to AgentVerified."""


def run_id_command(raw_args: str = "") -> str:
    """Run one /id command and return user-facing text (no ANSI, no secret values)."""
    try:
        parts = shlex.split(raw_args or "")
    except ValueError as exc:
        return f"/id: invalid arguments: {exc}"
    action = parts[0].lower() if parts else "status"
    client = AgentVerifiedClient.from_env()
    try:
        if action in {"help", "?"}:
            return _HELP
        if action in {"status", "show"}:
            return _format_status(client, load_state())
        if action in {"start", "setup", "init"}:
            surface = "console" if any(item in {"--business", "--console"} for item in parts[1:]) else "wallet"
            name_parts = [item for item in parts[1:] if item not in {"--business", "--console", "--personal", "--wallet"}]
            return _start(client, " ".join(name_parts).strip() or "Loki Agent", surface)
        if action == "reconnect":
            surface = "console" if any(item in {"--business", "--console"} for item in parts[1:]) else "wallet"
            return _reconnect(client, surface)
        if action in {"continue", "resume", "credential"}:
            return _continue(client)
        if action == "doctor":
            return _doctor(client)
        if action == "open":
            state = load_state()
            url = state.get("verification_url") or state.get("enrollment_url")
            if not url:
                command = "/id reconnect" if state.get("agent_id") else "/id start"
                return f"No pending AgentVerified approval URL. Run {command}."
            if state.get("enrollment_mode") == "reconnect":
                return f"AgentVerified reconnect approval: {url}\nAfter approval, run /id continue."
            return f"AgentVerified ID approval: {url}\nAfter approval / verification, run /id continue."
        return f"Unknown /id action: {action}\n\n{_HELP}"
    except AgentVerifiedIdentityError as exc:
        return f"AgentVerified ID: {exc}"
