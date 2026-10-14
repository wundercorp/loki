"""QuantPay ID (QPID) lifecycle helpers used by Loki's /id command.

The holder private key is generated locally and never sent to QuantPay.  Remote
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

DEFAULT_API_URL = "https://quantpay.sh/v1"
DEFAULT_ISSUER_URL = "https://id.quantpay.sh"
OPENID4VCI_GRANT = "urn:ietf:params:oauth:grant-type:pre-authorized_code"
CREDENTIAL_CONFIGURATION_ID = "QuantPayAgentCredential"
QPC_CHAIN_ID = 1716125


class QuantPayIdentityError(RuntimeError):
    """A user-facing /id lifecycle failure."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        raise QuantPayIdentityError("The stored QuantPay holder key is not a P-256 private JWK")
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
            "aud": "quantpay-agent-enrollment-token",
            "iat": now,
            "exp": now + 300,
            "jti": str(uuid.uuid4()),
        },
        _ec_private_key(private_jwk),
        algorithm="ES256",
        headers={"alg": "ES256", "kid": private_jwk.get("kid"), "typ": "quantpay-agent-enrollment+jwt"},
    )


def _normalize_merchant(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if "://" in value:
        from urllib.parse import urlparse
        parsed = urlparse(value)
        value = (parsed.hostname or value).lower().rstrip(".")
    if not value or "/" in value or " " in value:
        raise QuantPayIdentityError("Merchant must be a hostname such as loki.computer")
    return value


def _sign_authorization_proof(
    private_jwk: dict[str, Any], *, qpid: str, mandate_hash: str, merchant: str,
    amount_minor: str, request_id: str, payment_method: str = "x402", currency: str = "USD",
) -> str:
    now = int(time.time())
    payload = {
        "mandate_hash": mandate_hash,
        "payment_method": payment_method,
        "merchant": _normalize_merchant(merchant),
        "currency": currency.upper(),
        "amount_minor": amount_minor,
        "capabilities": [],
        "request_id": request_id,
        "iss": qpid,
        "sub": qpid,
        "aud": "quantpay-agent-authorization",
        "iat": now,
        "exp": now + 300,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        payload,
        _ec_private_key(private_jwk),
        algorithm="ES256",
        headers={"alg": "ES256", "kid": private_jwk.get("kid"), "typ": "quantpay-agent-action+jwt"},
    )


def identity_dir() -> Path:
    return get_loki_home() / "identity" / "quantpay"


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
        raise QuantPayIdentityError(f"Could not read {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def load_state() -> dict[str, Any]:
    return _load_json(state_path())


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    _atomic_private_json(state_path(), state)


def ensure_holder_key() -> tuple[dict[str, Any], dict[str, Any]]:
    existing = _load_json(key_path())
    if existing:
        if _private_fields(existing) != {"d"}:
            raise QuantPayIdentityError("Stored QuantPay holder JWK is malformed")
        return public_jwk(existing), existing
    public, private = generate_es256_jwk()
    _atomic_private_json(key_path(), private)
    return public, private


@dataclass
class QuantPayClient:
    api_url: str
    issuer_url: str
    access_token: str = ""
    api_key: str = ""
    organization_id: str = ""

    @classmethod
    def from_env(cls) -> "QuantPayClient":
        # Use Loki's scope-aware secret reader so multiplexed gateway profiles do not
        # leak credentials across homes, and ~/.loki/.env works without shell exports.
        from loki_cli.config import get_env_value

        def value(name: str, default: str = "") -> str:
            resolved = get_env_value(name)
            return (resolved if resolved is not None else default).strip()

        token_record = _load_json(management_token_path())
        local_management_token = str(token_record.get("access_token") or "").strip()
        return cls(
            api_url=value("QUANTPAY_API_URL", DEFAULT_API_URL).rstrip("/"),
            issuer_url=value("QUANTPAY_IDENTITY_ISSUER_URL", DEFAULT_ISSUER_URL).rstrip("/"),
            access_token=value("QUANTPAY_ACCESS_TOKEN") or local_management_token,
            api_key=value("QUANTPAY_API_KEY"),
            organization_id=value("QUANTPAY_ORGANIZATION_ID"),
        )

    @property
    def authenticated(self) -> bool:
        return bool(self.access_token or self.api_key)

    def require_management_auth(self) -> None:
        if not self.authenticated:
            raise QuantPayIdentityError(
                "QPID is waiting for QuantPay approval. Run /id start to create an enrollment, approve it in "
                "Wallet or Console, then run /id continue. Human Cognito bearer tokens are not required in Loki."
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
            raise QuantPayIdentityError(
                "QuantPay agent management authorization is not available. Run /id start, approve the enrollment in "
                "Wallet or Console, then run /id continue. Human Cognito bearer tokens are not required in Loki."
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
            raise QuantPayIdentityError(f"QuantPay request failed: {exc}") from exc
        return _decode_response(response, "QuantPay ID")

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
            raise QuantPayIdentityError(f"QuantPay enrollment request failed: {exc}") from exc
        return _decode_response(response, "QuantPay enrollment")

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
            raise QuantPayIdentityError(f"QuantPay issuer request failed: {exc}") from exc
        return _decode_response(response, "QuantPay credential issuer")


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
        raise QuantPayIdentityError(f"{label} returned HTTP {response.status_code}{suffix}")
    return payload if isinstance(payload, dict) else {"data": payload}


def _assurance_rank(value: str) -> int:
    try:
        return int(str(value).lower().removeprefix("qpid"))
    except ValueError:
        return 0


def _get_agent(client: QuantPayClient, state: dict[str, Any]) -> dict[str, Any]:
    agent_id = state.get("agent_id")
    if not agent_id:
        raise QuantPayIdentityError("No local QPID agent exists yet. Run /id start.")
    agent = client.request("GET", f"/agents/{agent_id}")
    state["qpid"] = agent.get("qpid", state.get("qpid"))
    state["assurance"] = agent.get("assurance", state.get("assurance", "qpid1"))
    save_state(state)
    return agent


def _format_status(client: QuantPayClient, state: dict[str, Any]) -> str:
    if not state.get("agent_id"):
        if state.get("enrollment_device_code"):
            remote_status = "pending"
            if state.get("enrollment_user_code"):
                try:
                    remote = client.public_request("GET", f"/agent-enrollments/{state['enrollment_user_code']}")
                    remote_status = str(remote.get("status") or "pending")
                except QuantPayIdentityError:
                    remote_status = "pending"
            if remote_status in {"expired", "canceled"}:
                _clear_pending_enrollment(state)
                save_state(state)
                return f"QuantPay ID: enrollment {remote_status}. Run /id start to create a fresh pairing."
            next_step = "Approval received. Run /id continue to claim the scoped QPID token." if remote_status == "approved" else "After approval / Stripe verification, run /id continue."
            return (
                f"QuantPay ID: enrollment {remote_status}\n"
                f"Pairing code: {state.get('enrollment_user_code', 'unknown')}\n"
                f"Approve: {state.get('enrollment_url', 'approval link unavailable')}\n"
                f"{next_step}\n"
                f"Holder key: {key_path()} (private, local only)"
            )
        return (
            "QuantPay ID: not initialized\n"
            "Run /id start to generate Loki's holder key and create a secure QuantPay enrollment.\n"
            "The private holder key stays under Loki home and is never sent to QuantPay."
        )
    agent: dict[str, Any] = {}
    credentials: list[Any] = []
    mandates: list[Any] = []
    remote_note = ""
    if client.authenticated:
        try:
            agent = client.request("GET", f"/agents/{state['agent_id']}")
            state["qpid"] = agent.get("qpid", state.get("qpid"))
            state["assurance"] = agent.get("assurance", state.get("assurance"))
            credentials = client.request("GET", f"/agents/{state['agent_id']}/credentials").get("items", [])
            mandates = client.request("GET", f"/agents/{state['agent_id']}/mandates").get("items", [])
            save_state(state)
        except QuantPayIdentityError as exc:
            remote_note = f"\nRemote status unavailable: {exc}"
    else:
        remote_note = "\nRemote status skipped: QuantPay authentication is not configured in this process."
    assurance = str(agent.get("assurance") or state.get("assurance") or "qpid1")
    erc = agent.get("erc8004") if agent else None
    credential_saved = credential_path().exists()
    lines = [
        "QuantPay ID",
        f"QPID: {state.get('qpid', 'unknown')}",
        f"Assurance: {assurance}",
        f"Holder key: {key_path()} (private, local only)",
        f"KYA session: {state.get('verification_session_id', 'not started')}",
        f"Active credentials: {sum(1 for item in credentials if item.get('status') == 'active')}",
        f"Holder credential saved: {'yes' if credential_saved else 'no'}",
        f"Mandates: {len(mandates)}",
        f"ERC-8004 binding: {erc.get('agentId') if isinstance(erc, dict) else 'not bound'}",
    ]
    if _assurance_rank(assurance) < 2 and state.get("verification_url"):
        lines += ["", f"Complete Stripe KYA: {state['verification_url']}", "Then run /id continue."]
    elif _assurance_rank(assurance) >= 2 and not credential_saved:
        lines += ["", "Next: /id continue to obtain the holder-bound QuantPay Agent Credential."]
    elif credential_saved:
        lines += ["", "Next: /id test [merchant] to prove deterministic ALLOW/DENY authorization."]
    return "\n".join(lines) + remote_note


def _clear_pending_enrollment(state: dict[str, Any]) -> None:
    for key in (
        "enrollment_device_code", "enrollment_user_code", "enrollment_surface",
        "enrollment_url", "enrollment_wallet_url", "enrollment_console_url",
        "enrollment_expires_at_epoch",
    ):
        state.pop(key, None)


def _start(client: QuantPayClient, name: str, surface: str = "wallet") -> str:
    state = load_state()
    public, _private = ensure_holder_key()
    if state.get("agent_id"):
        return _format_status(client, state)

    enrollment = state.get("enrollment_device_code")
    enrollment_expires_at = float(state.get("enrollment_expires_at_epoch") or 0)
    if enrollment and enrollment_expires_at > time.time() and state.get("enrollment_user_code"):
        try:
            remote = client.public_request("GET", f"/agent-enrollments/{state['enrollment_user_code']}")
            if str(remote.get("status") or "") in {"expired", "canceled"}:
                _clear_pending_enrollment(state)
                save_state(state)
                enrollment = None
        except QuantPayIdentityError:
            # If the status endpoint is temporarily unreachable, preserve the still-live local pairing.
            pass
    if not enrollment or enrollment_expires_at <= time.time():
        if enrollment_expires_at <= time.time():
            _clear_pending_enrollment(state)
        result = client.public_request("POST", "/agent-enrollments", json_body={
            "name": name or "Loki Agent",
            "surface": "console" if surface == "console" else "wallet",
            "publicKeyJwk": public,
            "capabilities": ["shopping", "payments", "purchase"],
            "paymentMethods": ["x402", "quantpay_wallet"],
        })
        expires_in = int(result.get("expiresIn") or 900)
        state.update({
            "version": 2,
            "enrollment_device_code": result.get("deviceCode"),
            "enrollment_user_code": result.get("userCode"),
            "enrollment_surface": surface,
            "enrollment_url": result.get("verificationUriComplete"),
            "enrollment_wallet_url": result.get("walletVerificationUriComplete"),
            "enrollment_console_url": result.get("consoleVerificationUriComplete"),
            "enrollment_expires_at_epoch": time.time() + expires_in,
            "created_at": state.get("created_at") or _utc_now(),
        })
        if not state.get("enrollment_device_code") or not state.get("enrollment_user_code"):
            raise QuantPayIdentityError("QuantPay enrollment did not return a device/user code")
        save_state(state)

    preferred = state.get("enrollment_url") or state.get("enrollment_wallet_url") or state.get("enrollment_console_url")
    return (
        "QuantPay ID enrollment started.\n"
        f"Pairing code: {state.get('enrollment_user_code')}\n"
        f"Approve this Loki agent: {preferred}\n\n"
        f"Personal / Wallet: {state.get('enrollment_wallet_url', 'unavailable')}\n"
        f"Business / Console: {state.get('enrollment_console_url', 'unavailable')}\n\n"
        f"Holder key: {key_path()} (mode 0600; never uploaded)\n"
        "Sign in and approve in QuantPay. If identity verification is needed, the web flow opens Stripe. "
        "Then run /id continue. No Cognito bearer token needs to be copied into Loki."
    )


def _exchange_enrollment(client: QuantPayClient, state: dict[str, Any]) -> bool:
    if client.authenticated and state.get("agent_id"):
        return True
    device_code = str(state.get("enrollment_device_code") or "")
    if not device_code:
        return False
    _public, private = ensure_holder_key()
    holder_proof = _sign_enrollment_token_proof(private, device_code)
    result = client.public_request(
        "POST", "/agent-enrollments/token",
        json_body={"deviceCode": device_code, "holderProof": holder_proof},
    )
    status = str(result.get("status") or "")
    if status == "authorization_pending":
        raise QuantPayIdentityError(
            f"QPID enrollment is waiting for human approval. Open {state.get('enrollment_url', 'the QuantPay approval link')} "
            "and then run /id continue again."
        )
    if status in {"expired", "canceled"}:
        _clear_pending_enrollment(state)
        save_state(state)
        raise QuantPayIdentityError(f"QPID enrollment is {status}. Run /id start again.")
    token = str(result.get("accessToken") or "")
    if status != "approved" or not token:
        raise QuantPayIdentityError("QuantPay enrollment approval did not return a scoped agent token")
    _atomic_private_json(management_token_path(), {
        "access_token": token,
        "token_type": result.get("tokenType", "Bearer"),
        "expires_in": result.get("expiresIn"),
        "received_at": _utc_now(),
    })
    state.pop("enrollment_device_code", None)
    state.pop("enrollment_expires_at_epoch", None)
    state.update({
        "agent_id": result.get("agentId"),
        "qpid": result.get("qpid"),
        "assurance": result.get("assurance", "qpid1"),
        "verification_session_id": result.get("verificationSessionId"),
        "enrollment_approved_at": _utc_now(),
    })
    save_state(state)
    client.access_token = token
    return True


def _active_credential(client: QuantPayClient, agent_id: str) -> dict[str, Any] | None:
    items = client.request("GET", f"/agents/{agent_id}/credentials").get("items", [])
    return next((item for item in items if isinstance(item, dict) and item.get("status") == "active"), None)


def _continue(client: QuantPayClient) -> str:
    state = load_state()
    _public, private = ensure_holder_key()
    if not state.get("agent_id") or not client.authenticated:
        if not _exchange_enrollment(client, state):
            raise QuantPayIdentityError("No pending QPID enrollment. Run /id start first.")
    client.require_management_auth()
    agent = _get_agent(client, state)
    credential = _active_credential(client, str(state["agent_id"]))
    # Credential issuance is a separate authoritative step from Stripe/webhook reconciliation.
    # If verification is already marked verified but the credential has not been issued yet,
    # issue it now regardless of the cached/current assurance value. This makes /id continue
    # safe to repeat across races and partial runs.
    if credential is None:
        verification_id = state.get("verification_session_id")
        if not verification_id:
            raise QuantPayIdentityError("KYA has not started. Run /id start first.")
        try:
            credential = client.request(
                "POST", f"/agents/{state['agent_id']}/kya",
                json_body={"verificationSessionId": verification_id},
            )
        except QuantPayIdentityError as exc:
            if "verified KYC or KYB session is required" in str(exc):
                return (
                    "Stripe KYA has not reconciled as verified yet.\n"
                    f"Verification URL: {state.get('verification_url', 'unavailable')}\n"
                    "Complete the verification (or allow the webhook to reconcile), then run /id continue again."
                )
            raise
        state["credential_id"] = credential.get("id")
        state["assurance"] = credential.get("assurance", "qpid2")
        save_state(state)
    if credential is None or not credential.get("id"):
        raise QuantPayIdentityError("QPID2 is active but no active QuantPay Agent Credential was found")
    state["credential_id"] = credential["id"]
    state["assurance"] = credential.get("assurance", state.get("assurance", "qpid2"))
    if credential_path().exists():
        save_state(state)
        return (
            f"QPID credential already holder-bound and saved.\nQPID: {state.get('qpid')}\n"
            f"Assurance: {state.get('assurance')}\nNext: /id test loki.computer"
        )

    offer = client.request(
        "POST", f"/agents/{state['agent_id']}/credentials/{credential['id']}/offer", json_body=None,
    )
    offer_body = offer.get("credentialOffer") or {}
    grant = (offer_body.get("grants") or {}).get(OPENID4VCI_GRANT) or {}
    preauth = grant.get("pre-authorized_code")
    if not preauth:
        raise QuantPayIdentityError("OpenID4VCI offer did not contain a pre-authorized code")
    token = client.issuer_request("POST", "/oid4vci/token", json_body={
        "grant_type": OPENID4VCI_GRANT,
        "pre-authorized_code": preauth,
    })
    access_token = token.get("access_token")
    if not access_token:
        raise QuantPayIdentityError("OpenID4VCI token response did not contain an access token")
    nonce_result = client.issuer_request("POST", "/oid4vci/nonce", json_body={})
    nonce = nonce_result.get("c_nonce")
    if not nonce:
        raise QuantPayIdentityError("OpenID4VCI nonce response did not contain c_nonce")
    proof = _sign_openid_proof(private, str(nonce), client.issuer_url)
    issued = client.issuer_request(
        "POST", "/oid4vci/credential", bearer=str(access_token), json_body={
            "credential_configuration_id": CREDENTIAL_CONFIGURATION_ID,
            "proofs": {"jwt": [proof]},
        },
    )
    credentials = issued.get("credentials") or []
    if not credentials or not isinstance(credentials[0], dict) or "credential" not in credentials[0]:
        raise QuantPayIdentityError("OpenID4VCI credential response did not contain a credential")
    _atomic_private_json(credential_path(), credentials[0])
    state["openid4vci_issuance_session_id"] = offer.get("issuanceSessionId")
    state["credential_received_at"] = _utc_now()
    save_state(state)
    return (
        "QPID2 credential issued and holder proof verified.\n"
        f"QPID: {state.get('qpid')}\nAssurance: {state.get('assurance')}\n"
        f"Credential: {credential_path()}\nNext: /id test loki.computer"
    )


def _authorization(client: QuantPayClient, private: dict[str, Any], *, state: dict[str, Any],
                   mandate_hash: str, merchant: str, amount_minor: str) -> dict[str, Any]:
    request_id = f"loki-id-{uuid.uuid4()}"
    proof = _sign_authorization_proof(
        private,
        qpid=str(state["qpid"]),
        mandate_hash=mandate_hash,
        merchant=merchant,
        amount_minor=amount_minor,
        request_id=request_id,
    )
    return client.request("POST", "/agents/authorize", json_body={
        "qpid": state["qpid"],
        "minimumAssurance": "qpid2",
        "mandateHash": mandate_hash,
        "paymentMethod": "x402",
        "merchant": merchant,
        "currency": "USD",
        "amountMinor": amount_minor,
        "capabilities": [],
        "requestId": request_id,
        "context": {"source": "loki-/id-test"},
        "agentProof": proof,
    })


def _test(client: QuantPayClient, merchant: str) -> str:
    client.require_management_auth()
    merchant = _normalize_merchant(merchant or "loki.computer")
    state = load_state()
    _public, private = ensure_holder_key()
    agent = _get_agent(client, state)
    if _assurance_rank(str(agent.get("assurance", "qpid0"))) < 2:
        raise QuantPayIdentityError("QPID2 is required. Complete KYA and run /id continue first.")
    if not credential_path().exists():
        raise QuantPayIdentityError("Holder credential is not present locally. Run /id continue first.")

    mandate_hash = str(state.get("test_mandate_hash") or "")
    request_code = str(state.get("test_mandate_request_code") or "")
    if not mandate_hash and request_code:
        request_status = client.public_request("GET", f"/agent-mandate-requests/{request_code}")
        status = str(request_status.get("status") or "")
        if status == "approved" and request_status.get("mandateHash"):
            mandate_hash = str(request_status["mandateHash"])
            state["test_mandate_hash"] = mandate_hash
            state["test_mandate_id"] = request_status.get("mandateId")
            save_state(state)
        elif status == "pending":
            return (
                "QPID test mandate is waiting for human approval.\n"
                f"Approval code: {request_code}\n"
                f"Approve: {state.get('test_mandate_approval_url', 'open the QuantPay approval link')}\n"
                "After approval, run /id test again. The agent cannot grant itself spending authority."
            )
        else:
            state.pop("test_mandate_request_code", None)
            state.pop("test_mandate_approval_url", None)
            state.pop("test_mandate_hash", None)
            state.pop("test_mandate_id", None)
            save_state(state)
            request_code = ""

    if not mandate_hash:
        surface = "console" if state.get("enrollment_surface") == "console" else "wallet"
        mandate_request = client.request("POST", f"/agents/{state['agent_id']}/mandate-requests", json_body={
            "merchant": merchant,
            "currency": "USD",
            "amountLimitMinor": "10000",
            "paymentMethods": ["x402"],
            "validForSeconds": 3600,
            "surface": surface,
        })
        request_code = str(mandate_request.get("requestCode") or "")
        approval_url = str(mandate_request.get("approvalUrl") or "")
        if not request_code or not approval_url:
            raise QuantPayIdentityError("QuantPay did not return a mandate approval code/link")
        state["test_mandate_request_code"] = request_code
        state["test_mandate_approval_url"] = approval_url
        state["test_merchant"] = merchant
        save_state(state)
        return (
            "QPID test mandate requested. Human approval is required before Loki can spend.\n"
            f"Approval code: {request_code}\n"
            f"Approve: {approval_url}\n"
            "Mandate: $100.00 USD via x402 for this merchant, valid for 60 minutes.\n"
            "After approval, run /id test again to prove $75 ALLOW and $100.01 DENY."
        )

    allowed = _authorization(client, private, state=state, mandate_hash=mandate_hash, merchant=merchant, amount_minor="7500")
    denied = _authorization(client, private, state=state, mandate_hash=mandate_hash, merchant=merchant, amount_minor="10001")
    allow_ok = allowed.get("decision") == "allow" and allowed.get("valid") is True
    deny_ok = denied.get("decision") == "deny" and "amount_limit_exceeded" in (denied.get("reasons") or [])
    verdict = "PASS" if allow_ok and deny_ok else "FAIL"
    return (
        f"QPID deterministic authorization test: {verdict}\n"
        f"Merchant: {merchant}\nMandate: $100.00 USD via x402 (human approved)\n"
        f"$75.00 -> {str(allowed.get('decision', 'unknown')).upper()}"
        f" ({', '.join(allowed.get('reasons') or []) or 'policy satisfied'})\n"
        f"$100.01 -> {str(denied.get('decision', 'unknown')).upper()}"
        f" ({', '.join(denied.get('reasons') or []) or 'no reason returned'})\n"
        f"Mandate hash: {mandate_hash}"
    )


def _bind(client: QuantPayClient, erc8004_agent_id: str) -> str:
    client.require_management_auth()
    if client.access_token.startswith("qpe_"):
        raise QuantPayIdentityError("ERC-8004 binding is a principal/admin action and is intentionally unavailable to the scoped agent enrollment token. Bind it from QuantPay Console or use an admin API credential.")
    if not erc8004_agent_id.isdigit():
        raise QuantPayIdentityError("Usage: /id bind <erc8004-agent-id>")
    state = load_state()
    if not state.get("agent_id"):
        raise QuantPayIdentityError("No QPID agent exists. Run /id start first.")
    agent = client.request("POST", f"/agents/{state['agent_id']}/erc8004", json_body={"agentId": erc8004_agent_id})
    binding = agent.get("erc8004") or {}
    return (
        "QPID ERC-8004 binding verified.\n"
        f"QPID: {agent.get('qpid', state.get('qpid'))}\n"
        f"Chain ID: {binding.get('chainId', QPC_CHAIN_ID)}\n"
        f"Registry: {binding.get('registryAddress', 'configured QPC registry')}\n"
        f"ERC-8004 agent ID: {binding.get('agentId', erc8004_agent_id)}"
    )


def _doctor(client: QuantPayClient) -> str:
    checks: list[str] = []
    for label, path in (
        ("JWKS", "/.well-known/jwks.json"),
        ("OpenID4VCI", "/.well-known/openid-credential-issuer"),
        ("OAuth", "/.well-known/oauth-authorization-server"),
    ):
        try:
            payload = client.issuer_request("GET", path)
            checks.append(f"{label}: ok ({len(payload)} top-level fields)")
        except QuantPayIdentityError as exc:
            checks.append(f"{label}: FAILED ({exc})")
    return "QuantPay ID doctor\n" + "\n".join(checks)


_HELP = """QuantPay ID for Loki
/id status                 Show local + live QPID state
/id start [name]           Generate holder key and start Wallet browser enrollment
/id continue               Exchange approval, reconcile KYA, issue QPID2 + holder-bound credential
/id test [merchant]        Request a human-approved $100 x402 mandate, then prove $75 ALLOW / $100.01 DENY
/id bind <erc8004-id>      Admin-only: verify/bind an existing QPC ERC-8004 registry entry
/id doctor                 Check public QPID discovery endpoints
/id open                   Reprint the pending Stripe verification URL
/id help                   Show this help

Auth: /id start uses a short-lived browser enrollment. Human Cognito bearer tokens never need to enter Loki.
Private holder key: stored mode 0600 under Loki home; never uploaded to QuantPay."""


def run_id_command(raw_args: str = "") -> str:
    """Run one /id command and return user-facing text (no ANSI, no secret values)."""
    try:
        parts = shlex.split(raw_args or "")
    except ValueError as exc:
        return f"/id: invalid arguments: {exc}"
    action = parts[0].lower() if parts else "status"
    client = QuantPayClient.from_env()
    try:
        if action in {"help", "?"}:
            return _HELP
        if action in {"status", "show"}:
            return _format_status(client, load_state())
        if action in {"start", "setup", "init"}:
            surface = "console" if any(item in {"--business", "--console"} for item in parts[1:]) else "wallet"
            name_parts = [item for item in parts[1:] if item not in {"--business", "--console", "--personal", "--wallet"}]
            return _start(client, " ".join(name_parts).strip() or "Loki Agent", surface)
        if action in {"continue", "resume", "credential"}:
            return _continue(client)
        if action == "test":
            return _test(client, parts[1] if len(parts) > 1 else "loki.computer")
        if action == "bind":
            return _bind(client, parts[1] if len(parts) > 1 else "")
        if action == "doctor":
            return _doctor(client)
        if action == "open":
            state = load_state()
            url = state.get("test_mandate_approval_url") or state.get("verification_url") or state.get("enrollment_url")
            if state.get("test_mandate_approval_url"):
                return f"QuantPay mandate approval: {url}\nAfter approval, run /id test again."
            return f"QuantPay ID approval: {url}\nAfter approval / verification, run /id continue." if url else "No pending QPID approval URL. Run /id start."
        return f"Unknown /id action: {action}\n\n{_HELP}"
    except QuantPayIdentityError as exc:
        return f"QuantPay ID: {exc}"
