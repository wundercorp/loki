from __future__ import annotations

import json
from pathlib import Path

import pytest

from loki_cli import quantpay_identity as qid
from loki_cli.commands import resolve_command


@pytest.fixture
def qpid_home(tmp_path, monkeypatch):
    home = tmp_path / "loki"
    monkeypatch.setattr(qid, "get_loki_home", lambda: home)
    monkeypatch.setenv("QUANTPAY_ACCESS_TOKEN", "test-user-token")
    monkeypatch.delenv("QUANTPAY_API_KEY", raising=False)
    return home


def test_id_command_registered_and_completable():
    cmd = resolve_command("id")
    assert cmd is not None
    assert cmd.name == "id"
    assert "continue" in cmd.subcommands
    assert "test" in cmd.subcommands


def test_holder_key_is_private_and_public_projection_has_no_private_material(qpid_home):
    public, private = qid.ensure_holder_key()
    assert private["d"]
    assert "d" not in public
    assert public["kid"] == private["kid"]
    if hasattr(qid.key_path().stat(), "st_mode"):
        assert qid.key_path().stat().st_mode & 0o777 == 0o600


def test_full_qpid_lifecycle_sends_only_public_jwk_and_proves_allow_deny(qpid_home, monkeypatch):
    remote = {
        "agent": None,
        "credential": None,
        "create_agent_body": None,
    }

    def request(self, method, path, *, json_body=None):
        if method == "POST" and path == "/agents":
            remote["create_agent_body"] = json_body
            remote["agent"] = {
                "id": "11111111-1111-1111-1111-111111111111",
                "qpid": "qpid_0123456789ABCDEF01234567",
                "assurance": "qpid1",
                "status": "active",
                "erc8004": None,
            }
            return dict(remote["agent"])
        if method == "GET" and path == "/agents/11111111-1111-1111-1111-111111111111":
            return dict(remote["agent"])
        if method == "POST" and path.endswith("/kya/stripe"):
            return {
                "verificationSessionId": "22222222-2222-2222-2222-222222222222",
                "verificationUrl": "https://verify.stripe.test/session",
                "providerReference": "vs_test",
                "status": "requires_input",
            }
        if method == "GET" and path.endswith("/credentials"):
            return {"items": [remote["credential"]] if remote["credential"] else []}
        if method == "POST" and path.endswith("/kya"):
            remote["agent"]["assurance"] = "qpid2"
            remote["credential"] = {
                "id": "33333333-3333-3333-3333-333333333333",
                "status": "active",
                "assurance": "qpid2",
            }
            return dict(remote["credential"])
        if method == "POST" and path.endswith("/offer"):
            return {
                "issuanceSessionId": "44444444-4444-4444-4444-444444444444",
                "credentialOffer": {
                    "grants": {
                        qid.OPENID4VCI_GRANT: {"pre-authorized_code": "preauth-code-for-test-1234567890"}
                    }
                },
            }
        if method == "GET" and path.endswith("/mandates"):
            return {"items": []}
        if method == "POST" and path.endswith("/mandates"):
            assert json_body["amountLimitMinor"] == "10000"
            return {"id": "55555555-5555-5555-5555-555555555555", "mandateHash": "m" * 43}
        if method == "POST" and path == "/agents/authorize":
            assert json_body["agentProof"].count(".") == 2
            if json_body["amountMinor"] == "7500":
                return {"valid": True, "decision": "allow", "reasons": []}
            return {"valid": False, "decision": "deny", "reasons": ["amount_limit_exceeded"]}
        raise AssertionError(f"unexpected API request: {method} {path}")

    def issuer_request(self, method, path, *, json_body=None, bearer=""):
        if path == "/oid4vci/token":
            assert json_body["pre-authorized_code"].startswith("preauth-code")
            return {"access_token": "oid4vci-access-token"}
        if path == "/oid4vci/nonce":
            return {"c_nonce": "nonce-for-holder-proof"}
        if path == "/oid4vci/credential":
            assert bearer == "oid4vci-access-token"
            proof = json_body["proofs"]["jwt"][0]
            header = qid.jwt.get_unverified_header(proof)
            assert header["typ"] == "openid4vci-proof+jwt"
            assert "d" not in header["jwk"]
            return {"credentials": [{"credential": {"media_type": "application/vc+jwt", "credential": {"id": "vc1"}}}]}
        raise AssertionError(f"unexpected issuer request: {method} {path}")

    monkeypatch.setattr(qid.QuantPayClient, "request", request)
    monkeypatch.setattr(qid.QuantPayClient, "issuer_request", issuer_request)

    started = qid.run_id_command("start Loki Production Agent")
    assert "QPID1 ready" in started
    assert "https://verify.stripe.test/session" in started
    sent_jwk = remote["create_agent_body"]["publicKeyJwk"]
    assert "d" not in sent_jwk
    assert sent_jwk["kid"]

    continued = qid.run_id_command("continue")
    assert "QPID2 credential issued" in continued
    assert qid.credential_path().exists()
    credential = json.loads(qid.credential_path().read_text())
    assert credential["credential"]["credential"]["id"] == "vc1"

    tested = qid.run_id_command("test loki.computer")
    assert "PASS" in tested
    assert "$75.00 -> ALLOW" in tested
    assert "$100.01 -> DENY" in tested
    assert "amount_limit_exceeded" in tested


def test_start_refuses_to_accept_chat_secret_when_access_token_missing(qpid_home, monkeypatch):
    monkeypatch.delenv("QUANTPAY_ACCESS_TOKEN", raising=False)
    result = qid.run_id_command("start")
    assert "Set QUANTPAY_ACCESS_TOKEN" in result
    assert "Do not paste the token" in result
