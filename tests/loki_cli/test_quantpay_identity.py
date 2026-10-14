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
    monkeypatch.delenv("QUANTPAY_ACCESS_TOKEN", raising=False)
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
    assert qid.key_path().stat().st_mode & 0o777 == 0o600


def test_start_uses_public_device_enrollment_without_human_bearer_token(qpid_home, monkeypatch):
    captured = {}

    def public_request(self, method, path, *, json_body=None):
        assert method == "POST"
        assert path == "/agent-enrollments"
        captured.update(json_body)
        return {
            "deviceCode": "qpd_device_code_for_test_abcdefghijklmnopqrstuvwxyz",
            "userCode": "QP-ABCD-2345",
            "verificationUriComplete": "https://wallet.quantpay.sh/?qpid_enroll=QP-ABCD-2345",
            "walletVerificationUriComplete": "https://wallet.quantpay.sh/?qpid_enroll=QP-ABCD-2345",
            "consoleVerificationUriComplete": "https://console.quantpay.sh/?qpid_enroll=QP-ABCD-2345",
            "expiresIn": 900,
            "interval": 3,
        }

    monkeypatch.setattr(qid.QuantPayClient, "public_request", public_request)

    result = qid.run_id_command("start Loki Production Agent")
    assert "QuantPay ID enrollment started" in result
    assert "QP-ABCD-2345" in result
    assert "wallet.quantpay.sh" in result
    assert "No Cognito bearer token needs to be copied into Loki" in result
    assert captured["name"] == "Loki Production Agent"
    assert captured["surface"] == "wallet"
    assert "d" not in captured["publicKeyJwk"]
    assert captured["publicKeyJwk"]["kid"]
    assert qid.state_path().exists()


def test_start_business_prefers_console_surface(qpid_home, monkeypatch):
    captured = {}

    def public_request(self, method, path, *, json_body=None):
        captured.update(json_body)
        return {
            "deviceCode": "qpd_device_code_for_test_abcdefghijklmnopqrstuvwxyz",
            "userCode": "QP-WXYZ-6789",
            "verificationUriComplete": "https://console.quantpay.sh/?qpid_enroll=QP-WXYZ-6789",
            "walletVerificationUriComplete": "https://wallet.quantpay.sh/?qpid_enroll=QP-WXYZ-6789",
            "consoleVerificationUriComplete": "https://console.quantpay.sh/?qpid_enroll=QP-WXYZ-6789",
            "expiresIn": 900,
        }

    monkeypatch.setattr(qid.QuantPayClient, "public_request", public_request)
    result = qid.run_id_command("start --business Finance Loki")
    assert captured["surface"] == "console"
    assert captured["name"] == "Finance Loki"
    assert "console.quantpay.sh" in result


def test_full_qpid_lifecycle_device_exchange_holder_proof_and_allow_deny(qpid_home, monkeypatch):
    remote = {
        "agent": None,
        "credential": None,
        "enrollment_body": None,
        "token_exchange_count": 0,
        "mandate_status": "pending",
    }

    agent_id = "11111111-1111-1111-1111-111111111111"
    verification_id = "22222222-2222-2222-2222-222222222222"
    credential_id = "33333333-3333-3333-3333-333333333333"

    def public_request(self, method, path, *, json_body=None):
        if method == "POST" and path == "/agent-enrollments":
            remote["enrollment_body"] = json_body
            return {
                "deviceCode": "qpd_device_code_for_test_abcdefghijklmnopqrstuvwxyz",
                "userCode": "QP-ABCD-2345",
                "verificationUriComplete": "https://wallet.quantpay.sh/?qpid_enroll=QP-ABCD-2345",
                "walletVerificationUriComplete": "https://wallet.quantpay.sh/?qpid_enroll=QP-ABCD-2345",
                "consoleVerificationUriComplete": "https://console.quantpay.sh/?qpid_enroll=QP-ABCD-2345",
                "expiresIn": 900,
            }
        if method == "POST" and path == "/agent-enrollments/token":
            assert json_body["deviceCode"].startswith("qpd_")
            proof = json_body["holderProof"]
            assert proof.count(".") == 2
            header = qid.jwt.get_unverified_header(proof)
            claims = qid.jwt.decode(proof, options={"verify_signature": False, "verify_aud": False})
            assert header["typ"] == "quantpay-agent-enrollment+jwt"
            assert claims["aud"] == "quantpay-agent-enrollment-token"
            assert claims["device_code_hash"] == qid._b64url(qid.hashlib.sha256(json_body["deviceCode"].encode("utf-8")).digest())
            remote["token_exchange_count"] += 1
            remote["agent"] = {
                "id": agent_id,
                "qpid": "qpid_0123456789ABCDEF01234567",
                "assurance": "qpid1",
                "status": "active",
                "erc8004": None,
            }
            return {
                "status": "approved",
                "accessToken": "qpe_scoped_agent_token_for_test",
                "tokenType": "Bearer",
                "expiresIn": 86400,
                "agentId": agent_id,
                "qpid": remote["agent"]["qpid"],
                "assurance": "qpid1",
                "verificationSessionId": verification_id,
            }
        if method == "GET" and path == "/agent-mandate-requests/QPM-TEST-2345":
            if remote["mandate_status"] == "pending":
                return {"requestCode": "QPM-TEST-2345", "status": "pending"}
            return {
                "requestCode": "QPM-TEST-2345",
                "status": "approved",
                "mandateId": "55555555-5555-5555-5555-555555555555",
                "mandateHash": "m" * 43,
            }
        raise AssertionError(f"unexpected public API request: {method} {path}")

    def request(self, method, path, *, json_body=None):
        assert self.access_token == "qpe_scoped_agent_token_for_test"
        if method == "GET" and path == f"/agents/{agent_id}":
            return dict(remote["agent"])
        if method == "GET" and path == f"/agents/{agent_id}/credentials":
            return {"items": [remote["credential"]] if remote["credential"] else []}
        if method == "POST" and path == f"/agents/{agent_id}/kya":
            assert json_body["verificationSessionId"] == verification_id
            remote["agent"]["assurance"] = "qpid2"
            remote["credential"] = {
                "id": credential_id,
                "status": "active",
                "assurance": "qpid2",
            }
            return dict(remote["credential"])
        if method == "POST" and path == f"/agents/{agent_id}/credentials/{credential_id}/offer":
            return {
                "issuanceSessionId": "44444444-4444-4444-4444-444444444444",
                "credentialOffer": {
                    "grants": {
                        qid.OPENID4VCI_GRANT: {
                            "pre-authorized_code": "preauth-code-for-test-1234567890"
                        }
                    }
                },
            }
        if method == "POST" and path == f"/agents/{agent_id}/mandate-requests":
            assert json_body["amountLimitMinor"] == "10000"
            assert json_body["surface"] == "wallet"
            return {
                "requestCode": "QPM-TEST-2345",
                "status": "pending",
                "approvalUrl": "https://wallet.quantpay.sh/?qpid_mandate=QPM-TEST-2345",
            }
        if method == "POST" and path == "/agents/authorize":
            assert json_body["agentProof"].count(".") == 2
            if json_body["amountMinor"] == "7500":
                return {"valid": True, "decision": "allow", "reasons": []}
            return {"valid": False, "decision": "deny", "reasons": ["amount_limit_exceeded"]}
        raise AssertionError(f"unexpected authenticated API request: {method} {path}")

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

    monkeypatch.setattr(qid.QuantPayClient, "public_request", public_request)
    monkeypatch.setattr(qid.QuantPayClient, "request", request)
    monkeypatch.setattr(qid.QuantPayClient, "issuer_request", issuer_request)

    started = qid.run_id_command("start Loki Production Agent")
    assert "enrollment started" in started
    assert "QP-ABCD-2345" in started
    sent_jwk = remote["enrollment_body"]["publicKeyJwk"]
    assert "d" not in sent_jwk
    assert sent_jwk["kid"]

    continued = qid.run_id_command("continue")
    assert "QPID2 credential issued" in continued
    assert remote["token_exchange_count"] == 1
    assert qid.management_token_path().exists()
    management = json.loads(qid.management_token_path().read_text())
    assert management["access_token"].startswith("qpe_")
    assert qid.management_token_path().stat().st_mode & 0o777 == 0o600
    assert qid.credential_path().exists()
    credential = json.loads(qid.credential_path().read_text())
    assert credential["credential"]["credential"]["id"] == "vc1"

    requested = qid.run_id_command("test loki.computer")
    assert "Human approval is required" in requested
    assert "QPM-TEST-2345" in requested
    assert "qpid_mandate=QPM-TEST-2345" in requested

    remote["mandate_status"] = "approved"
    tested = qid.run_id_command("test loki.computer")
    assert "PASS" in tested
    assert "$75.00 -> ALLOW" in tested
    assert "$100.01 -> DENY" in tested
    assert "amount_limit_exceeded" in tested


def test_continue_reports_pending_human_approval(qpid_home, monkeypatch):
    state = {
        "enrollment_device_code": "qpd_device_code_for_test_abcdefghijklmnopqrstuvwxyz",
        "enrollment_user_code": "QP-ABCD-2345",
        "enrollment_url": "https://wallet.quantpay.sh/?qpid_enroll=QP-ABCD-2345",
        "enrollment_expires_at_epoch": 9999999999,
    }
    qid.save_state(state)

    def public_request(self, method, path, *, json_body=None):
        return {"status": "authorization_pending", "interval": 3}

    monkeypatch.setattr(qid.QuantPayClient, "public_request", public_request)
    result = qid.run_id_command("continue")
    assert "waiting for human approval" in result
    assert "wallet.quantpay.sh" in result
    assert not qid.management_token_path().exists()


def test_start_replaces_server_canceled_pairing_immediately(qpid_home, monkeypatch):
    qid.save_state({
        "enrollment_device_code": "qpd_old_device_code_abcdefghijklmnopqrstuvwxyz",
        "enrollment_user_code": "QP-OLD2-3456",
        "enrollment_url": "https://wallet.quantpay.sh/?qpid_enroll=QP-OLD2-3456",
        "enrollment_expires_at_epoch": 9999999999,
    })
    calls = []

    def public_request(self, method, path, *, json_body=None):
        calls.append((method, path))
        if method == "GET":
            return {"status": "canceled", "userCode": "QP-OLD2-3456"}
        return {
            "deviceCode": "qpd_fresh_device_code_abcdefghijklmnopqrstuvwxyz",
            "userCode": "QP-NEW2-3456",
            "verificationUriComplete": "https://wallet.quantpay.sh/?qpid_enroll=QP-NEW2-3456",
            "walletVerificationUriComplete": "https://wallet.quantpay.sh/?qpid_enroll=QP-NEW2-3456",
            "consoleVerificationUriComplete": "https://console.quantpay.sh/?qpid_enroll=QP-NEW2-3456",
            "expiresIn": 900,
        }

    monkeypatch.setattr(qid.QuantPayClient, "public_request", public_request)
    result = qid.run_id_command("start Loki Production Agent")
    assert "QP-NEW2-3456" in result
    assert calls[0] == ("GET", "/agent-enrollments/QP-OLD2-3456")
    assert calls[1] == ("POST", "/agent-enrollments")
    assert qid.load_state()["enrollment_user_code"] == "QP-NEW2-3456"
