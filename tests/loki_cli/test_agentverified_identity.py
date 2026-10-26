from __future__ import annotations

import json
from pathlib import Path

import pytest

from loki_cli import agentverified_identity as qid
from loki_cli.commands import resolve_command


@pytest.fixture
def avid_home(tmp_path, monkeypatch):
    home = tmp_path / "loki"
    monkeypatch.setattr(qid, "get_loki_home", lambda: home)
    monkeypatch.delenv("AGENTVERIFIED_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTVERIFIED_API_KEY", raising=False)
    monkeypatch.delenv("AGENTVERIFIED_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTVERIFIED_API_KEY", raising=False)
    return home


def test_id_command_registered_and_completable():
    cmd = resolve_command("id")
    assert cmd is not None
    assert cmd.name == "id"
    assert "continue" in cmd.subcommands
    assert "reconnect" in cmd.subcommands
    assert "doctor" in cmd.subcommands
    assert "test" not in cmd.subcommands
    assert "bind" not in cmd.subcommands


def test_holder_key_is_private_and_public_projection_has_no_private_material(avid_home):
    public, private = qid.ensure_holder_key()
    assert private["d"]
    assert "d" not in public
    assert public["kid"] == private["kid"]
    assert qid.key_path().stat().st_mode & 0o777 == 0o600


def test_start_uses_console_device_enrollment_without_human_bearer_token(avid_home, monkeypatch):
    captured = {}

    def public_request(self, method, path, *, json_body=None):
        assert method == "POST"
        assert path == "/agent-enrollments"
        captured.update(json_body)
        return {
            "deviceCode": "qpd_device_code_for_test_abcdefghijklmnopqrstuvwxyz",
            "userCode": "AV-ABCD-2345",
            "verificationUriComplete": "https://agentverified.sh/?avid_enroll=AV-ABCD-2345",
            "walletVerificationUriComplete": "https://agentverified.sh/?avid_enroll=AV-ABCD-2345",
            "consoleVerificationUriComplete": "https://console.agentverified.sh/?avid_enroll=AV-ABCD-2345",
            "expiresIn": 900,
            "interval": 3,
        }

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)

    result = qid.run_id_command("start Loki Production Agent")
    assert "AgentVerified ID enrollment started" in result
    assert "AV-ABCD-2345" in result
    assert "agentverified.sh" in result
    assert "No human bearer token needs to be copied into Loki" in result
    assert captured["name"] == "Loki Production Agent"
    assert captured["surface"] == "console"
    assert "d" not in captured["publicKeyJwk"]
    assert captured["publicKeyJwk"]["kid"]
    assert qid.state_path().exists()


def test_start_business_prefers_console_surface(avid_home, monkeypatch):
    captured = {}

    def public_request(self, method, path, *, json_body=None):
        captured.update(json_body)
        return {
            "deviceCode": "qpd_device_code_for_test_abcdefghijklmnopqrstuvwxyz",
            "userCode": "AV-WXYZ-6789",
            "verificationUriComplete": "https://console.agentverified.sh/?avid_enroll=AV-WXYZ-6789",
            "walletVerificationUriComplete": "https://agentverified.sh/?avid_enroll=AV-WXYZ-6789",
            "consoleVerificationUriComplete": "https://console.agentverified.sh/?avid_enroll=AV-WXYZ-6789",
            "expiresIn": 900,
        }

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    result = qid.run_id_command("start --business Finance Loki")
    assert captured["surface"] == "console"
    assert captured["name"] == "Finance Loki"
    assert "console.agentverified.sh" in result


def test_full_agentverified_identity_lifecycle(avid_home, monkeypatch):
    remote = {
        "agent": None,
        "credential": None,
        "enrollment_body": None,
        "token_exchange_count": 0,
    }

    agent_id = "11111111-1111-1111-1111-111111111111"
    verification_id = "22222222-2222-2222-2222-222222222222"
    credential_id = "33333333-3333-3333-3333-333333333333"

    def public_request(self, method, path, *, json_body=None):
        if method == "POST" and path == "/agent-enrollments":
            remote["enrollment_body"] = json_body
            return {
                "deviceCode": "qpd_device_code_for_test_abcdefghijklmnopqrstuvwxyz",
                "userCode": "AV-ABCD-2345",
                "verificationUriComplete": "https://agentverified.sh/?avid_enroll=AV-ABCD-2345",
                "walletVerificationUriComplete": "https://agentverified.sh/?avid_enroll=AV-ABCD-2345",
                "consoleVerificationUriComplete": "https://console.agentverified.sh/?avid_enroll=AV-ABCD-2345",
                "expiresIn": 900,
            }
        if method == "POST" and path == "/agent-enrollments/token":
            assert json_body["deviceCode"].startswith("qpd_")
            proof = json_body["holderProof"]
            assert proof.count(".") == 2
            header = qid.jwt.get_unverified_header(proof)
            claims = qid.jwt.decode(proof, options={"verify_signature": False, "verify_aud": False})
            assert header["typ"] == "agentverified-agent-enrollment+jwt"
            assert claims["aud"] == "agentverified-agent-enrollment-token"
            assert claims["device_code_hash"] == qid._b64url(qid.hashlib.sha256(json_body["deviceCode"].encode("utf-8")).digest())
            remote["token_exchange_count"] += 1
            remote["agent"] = {
                "id": agent_id,
                "avid": "avid_0123456789ABCDEF01234567",
                "assurance": "qpid1",
                "status": "active",
            }
            return {
                "status": "approved",
                "accessToken": "qpe_scoped_agent_token_for_test",
                "tokenType": "Bearer",
                "expiresIn": 86400,
                "agentId": agent_id,
                "avid": remote["agent"]["avid"],
                "assurance": "qpid1",
                "verificationSessionId": verification_id,
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

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    monkeypatch.setattr(qid.AgentVerifiedClient, "request", request)
    monkeypatch.setattr(qid.AgentVerifiedClient, "issuer_request", issuer_request)

    started = qid.run_id_command("start Loki Production Agent")
    assert "enrollment started" in started
    assert "AV-ABCD-2345" in started
    sent_jwk = remote["enrollment_body"]["publicKeyJwk"]
    assert "d" not in sent_jwk
    assert sent_jwk["kid"]

    continued = qid.run_id_command("continue")
    assert "AgentVerified credential issued" in continued
    assert remote["token_exchange_count"] == 1
    assert qid.management_token_path().exists()
    management = json.loads(qid.management_token_path().read_text())
    assert management["access_token"].startswith("qpe_")
    assert qid.management_token_path().stat().st_mode & 0o777 == 0o600
    assert qid.credential_path().exists()
    credential = json.loads(qid.credential_path().read_text())
    assert credential["credential"]["credential"]["id"] == "vc1"

    status = qid.run_id_command("status")
    assert "AgentVerified ID" in status
    assert "Agent ID:" in status
    assert "ERC-8004" not in status
    assert "x402" not in status


def test_continue_reports_pending_human_approval(avid_home, monkeypatch):
    state = {
        "enrollment_device_code": "qpd_device_code_for_test_abcdefghijklmnopqrstuvwxyz",
        "enrollment_user_code": "AV-ABCD-2345",
        "enrollment_url": "https://agentverified.sh/?avid_enroll=AV-ABCD-2345",
        "enrollment_expires_at_epoch": 9999999999,
    }
    qid.save_state(state)

    def public_request(self, method, path, *, json_body=None):
        return {"status": "authorization_pending", "interval": 3}

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    result = qid.run_id_command("continue")
    assert "waiting for human approval" in result
    assert "agentverified.sh" in result
    assert not qid.management_token_path().exists()


def test_start_replaces_server_canceled_pairing_immediately(avid_home, monkeypatch):
    qid.save_state({
        "enrollment_device_code": "qpd_old_device_code_abcdefghijklmnopqrstuvwxyz",
        "enrollment_user_code": "AV-OLD2-3456",
        "enrollment_url": "https://agentverified.sh/?avid_enroll=AV-OLD2-3456",
        "enrollment_expires_at_epoch": 9999999999,
    })
    calls = []

    def public_request(self, method, path, *, json_body=None):
        calls.append((method, path))
        if method == "GET":
            return {"status": "canceled", "userCode": "AV-OLD2-3456"}
        return {
            "deviceCode": "qpd_fresh_device_code_abcdefghijklmnopqrstuvwxyz",
            "userCode": "AV-NEW2-3456",
            "verificationUriComplete": "https://agentverified.sh/?avid_enroll=AV-NEW2-3456",
            "walletVerificationUriComplete": "https://agentverified.sh/?avid_enroll=AV-NEW2-3456",
            "consoleVerificationUriComplete": "https://console.agentverified.sh/?avid_enroll=AV-NEW2-3456",
            "expiresIn": 900,
        }

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    result = qid.run_id_command("start Loki Production Agent")
    assert "AV-NEW2-3456" in result
    assert calls[0] == ("GET", "/agent-enrollments/AV-OLD2-3456")
    assert calls[1] == ("POST", "/agent-enrollments")
    assert qid.load_state()["enrollment_user_code"] == "AV-NEW2-3456"


def test_continue_recovers_missing_stripe_verification_url(avid_home, monkeypatch):
    qid.save_state({
        "agent_id": "11111111-1111-1111-1111-111111111111",
        "avid": "avid_AB8E4825B4D6D709F172232E",
        "assurance": "qpid1",
        "verification_session_id": "22222222-2222-2222-2222-222222222222",
    })
    qid._atomic_private_json(qid.management_token_path(), {"access_token": "qpe_test"})

    def request(self, method, path, *, json_body=None):
        if method == "GET" and path.endswith("/credentials"):
            return {"items": []}
        if method == "GET" and path.startswith("/agents/"):
            return {"id": "11111111-1111-1111-1111-111111111111", "avid": "avid_AB8E4825B4D6D709F172232E", "assurance": "qpid1"}
        if method == "POST" and path.endswith("/kya"):
            raise qid.AgentVerifiedIdentityError("AgentVerified ID returned HTTP 400: verified KYC or KYB session is required")
        if method == "POST" and path.endswith("/kya/stripe"):
            return {
                "verificationSessionId": "33333333-3333-3333-3333-333333333333",
                "status": "requires_input",
                "verificationUrl": "https://verify.stripe.com/resume-test",
                "resumedVerification": True,
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(qid.AgentVerifiedClient, "request", request)
    result = qid.run_id_command("continue")
    assert "Stripe KYA is ready to continue" in result
    assert "https://verify.stripe.com/resume-test" in result
    state = qid.load_state()
    assert state["verification_session_id"] == "33333333-3333-3333-3333-333333333333"
    assert state["verification_url"] == "https://verify.stripe.com/resume-test"


def test_legacy_identity_directory_is_migrated_to_agentverified(avid_home):
    legacy = avid_home / "identity" / "quantpay"
    legacy.mkdir(parents=True)
    (legacy / "state.json").write_text('{"avid":"qpid_legacy"}')
    assert qid.identity_dir() == avid_home / "identity" / "agentverified"
    assert not legacy.exists()
    assert qid.state_path().exists()


def test_id_help_is_identity_only(avid_home):
    help_text = qid.run_id_command("help")
    assert "AgentVerified ID" in help_text
    assert "/id reconnect" in help_text
    assert "ERC-8004" not in help_text
    assert "x402" not in help_text
    assert "/id bind" not in help_text
    assert "/id test" not in help_text


def test_invalid_management_token_is_discarded_without_losing_local_identity(avid_home, monkeypatch):
    qid.save_state({
        "agent_id": "11111111-1111-1111-1111-111111111111",
        "avid": "avid_AB8E4825B4D6D709F172232E",
        "assurance": "qpid2",
    })
    qid.ensure_holder_key()
    qid._atomic_private_json(qid.credential_path(), {"credential": {"id": "vc1"}})
    qid._atomic_private_json(qid.management_token_path(), {"access_token": "qpe_stale"})

    def fake_request(*args, **kwargs):
        return qid.httpx.Response(422, json={"message": "Invalid agent enrollment token"})

    monkeypatch.setattr(qid.httpx, "request", fake_request)
    result = qid.run_id_command("status")
    assert "AgentVerified ID" in result
    assert "Management connection: inactive" in result
    assert "Run /id reconnect" in result
    assert not qid.management_token_path().exists()
    assert qid.credential_path().exists()



def _seed_existing_identity(qid_home):
    qid.save_state({
        "agent_id": "11111111-1111-1111-1111-111111111111",
        "avid": "avid_AB8E4825B4D6D709F172232E",
        "assurance": "qpid2",
        "verification_session_id": "22222222-2222-2222-2222-222222222222",
    })
    qid.ensure_holder_key()
    qid._atomic_private_json(qid.credential_path(), {"credential": {"id": "vc-existing"}})


def test_start_existing_identity_points_to_reconnect_without_creating_enrollment(avid_home, monkeypatch):
    _seed_existing_identity(avid_home)

    def public_request(*args, **kwargs):
        raise AssertionError("/id start must not create another enrollment for an existing identity")

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    result = qid.run_id_command("start")
    assert "already exists" in result
    assert "/id reconnect" in result
    assert "avid_AB8E4825B4D6D709F172232E" in result


def test_wallet_surface_is_rejected_before_network_request(avid_home, monkeypatch):
    def public_request(*args, **kwargs):
        raise AssertionError("wallet compatibility must fail before a network request")

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    result = qid.run_id_command("start --wallet Loki Production Agent")
    assert "Wallet enrollment is no longer accepted" in result


def test_reconnect_requires_existing_identity(avid_home):
    result = qid.run_id_command("reconnect")
    assert "No existing AgentVerified ID to reconnect" in result
    assert "/id start" in result


def test_reconnect_reuses_existing_holder_key_and_identity(avid_home, monkeypatch):
    _seed_existing_identity(avid_home)
    key_before = qid.key_path().read_bytes()
    credential_before = qid.credential_path().read_bytes()
    captured = {}

    def public_request(self, method, path, *, json_body=None):
        assert method == "POST"
        assert path == "/agent-enrollments"
        captured.update(json_body or {})
        return {
            "deviceCode": "qpd_reconnect_device_code_abcdefghijklmnopqrstuvwxyz",
            "userCode": "AV-RECO-1234",
            "verificationUriComplete": "https://agentverified.sh/?avid_reconnect=AV-RECO-1234",
            "walletVerificationUriComplete": "https://agentverified.sh/?avid_reconnect=AV-RECO-1234",
            "consoleVerificationUriComplete": "https://console.agentverified.sh/?avid_reconnect=AV-RECO-1234",
            "expiresIn": 900,
        }

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    result = qid.run_id_command("reconnect")
    assert "AgentVerified reconnect started" in result
    assert captured["mode"] == "reconnect"
    assert captured["agentId"] == "11111111-1111-1111-1111-111111111111"
    assert captured["avid"] == "avid_AB8E4825B4D6D709F172232E"
    assert "d" not in captured["publicKeyJwk"]
    assert qid.key_path().read_bytes() == key_before
    assert qid.credential_path().read_bytes() == credential_before
    state = qid.load_state()
    assert state["enrollment_mode"] == "reconnect"
    assert state["reconnect_expected_avid"] == "avid_AB8E4825B4D6D709F172232E"


def test_reconnect_reports_api_version_skew_without_mutating_identity(avid_home, monkeypatch):
    _seed_existing_identity(avid_home)
    key_before = qid.key_path().read_bytes()
    credential_before = qid.credential_path().read_bytes()

    def public_request(self, method, path, *, json_body=None):
        raise qid.AgentVerifiedIdentityError(
            'AgentVerified enrollment returned HTTP 422: [{"code":"unrecognized_keys","keys":["mode","agentId","avid"]}]'
        )

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    result = qid.run_id_command("reconnect")
    assert "older than this Loki build" in result
    assert "Deploy the current AgentVerified API" in result
    assert qid.key_path().read_bytes() == key_before
    assert qid.credential_path().read_bytes() == credential_before


def test_reconnect_continue_preserves_identity_key_and_credential(avid_home, monkeypatch):
    _seed_existing_identity(avid_home)
    key_before = qid.key_path().read_bytes()
    credential_before = qid.credential_path().read_bytes()

    def public_request(self, method, path, *, json_body=None):
        if method == "POST" and path == "/agent-enrollments":
            return {
                "deviceCode": "qpd_reconnect_device_code_abcdefghijklmnopqrstuvwxyz",
                "userCode": "AV-RECO-1234",
                "verificationUriComplete": "https://agentverified.sh/?avid_reconnect=AV-RECO-1234",
                "expiresIn": 900,
            }
        if method == "POST" and path == "/agent-enrollments/token":
            assert json_body["holderProof"].count(".") == 2
            return {
                "status": "approved",
                "accessToken": "qpe_reconnected_agent_token",
                "tokenType": "Bearer",
                "expiresIn": 86400,
                "agentId": "11111111-1111-1111-1111-111111111111",
                "avid": "avid_AB8E4825B4D6D709F172232E",
                "assurance": "qpid2",
            }
        raise AssertionError(f"unexpected public request {method} {path}")

    def request(self, method, path, *, json_body=None):
        assert self.access_token == "qpe_reconnected_agent_token"
        assert method == "GET"
        assert path == "/agents/11111111-1111-1111-1111-111111111111"
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "avid": "avid_AB8E4825B4D6D709F172232E",
            "assurance": "qpid2",
        }

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    monkeypatch.setattr(qid.AgentVerifiedClient, "request", request)

    assert "reconnect started" in qid.run_id_command("reconnect")
    result = qid.run_id_command("continue")
    assert "management connection restored" in result
    assert "were not changed" in result
    state = qid.load_state()
    assert state["agent_id"] == "11111111-1111-1111-1111-111111111111"
    assert state["avid"] == "avid_AB8E4825B4D6D709F172232E"
    assert state["assurance"] == "qpid2"
    assert "enrollment_mode" not in state
    assert qid.key_path().read_bytes() == key_before
    assert qid.credential_path().read_bytes() == credential_before
    assert qid.management_token_path().exists()


def test_reconnect_identity_mismatch_fails_closed(avid_home, monkeypatch):
    _seed_existing_identity(avid_home)
    key_before = qid.key_path().read_bytes()
    credential_before = qid.credential_path().read_bytes()

    def public_request(self, method, path, *, json_body=None):
        if path == "/agent-enrollments":
            return {
                "deviceCode": "qpd_reconnect_device_code_abcdefghijklmnopqrstuvwxyz",
                "userCode": "AV-RECO-1234",
                "verificationUriComplete": "https://agentverified.sh/?avid_reconnect=AV-RECO-1234",
                "expiresIn": 900,
            }
        if path == "/agent-enrollments/token":
            return {
                "status": "approved",
                "accessToken": "qpe_should_never_be_saved",
                "agentId": "99999999-9999-9999-9999-999999999999",
                "avid": "avid_WRONG0000000000000000000",
            }
        raise AssertionError(path)

    monkeypatch.setattr(qid.AgentVerifiedClient, "public_request", public_request)
    qid.run_id_command("reconnect")
    result = qid.run_id_command("continue")
    assert "Reconnect identity mismatch" in result
    assert not qid.management_token_path().exists()
    state = qid.load_state()
    assert state["agent_id"] == "11111111-1111-1111-1111-111111111111"
    assert state["avid"] == "avid_AB8E4825B4D6D709F172232E"
    assert qid.key_path().read_bytes() == key_before
    assert qid.credential_path().read_bytes() == credential_before


def test_status_points_existing_identity_to_reconnect_when_management_inactive(avid_home):
    _seed_existing_identity(avid_home)
    result = qid.run_id_command("status")
    assert "Identity ready" in result
    assert "Management connection: inactive" in result
    assert "Run /id reconnect" in result
