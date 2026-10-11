from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from loki_cli.web_routers import agentvm


def test_bootstrap_keeps_openrouter_secret_volatile_and_model_persistent(monkeypatch):
    removed_env = []
    saved_configs = []
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    monkeypatch.setattr(agentvm, "save_env_value", lambda *_: pytest.fail("AgentVM secret must not be persisted"))
    monkeypatch.setattr(agentvm, "remove_env_value", lambda key: removed_env.append(key))
    monkeypatch.setattr(agentvm, "save_config", lambda cfg, merge_existing=False: saved_configs.append((cfg, merge_existing)))

    result = asyncio.run(
        agentvm.agentvm_bootstrap(
            agentvm.AgentVMBootstrapRequest(
                apiKey="sk-or-v1-test-secret-value-1234567890",
                model="openai/gpt-5.2",
                persist=True,
            )
        )
    )

    assert removed_env == ["OPENROUTER_API_KEY"]
    assert agentvm.os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-test-secret-value-1234567890"
    assert saved_configs == [({"model": {"provider": "openrouter", "default": "openai/gpt-5.2"}}, True)]
    assert result["inference"] == {
        "configured": True,
        "provider": "openrouter",
        "model": "openai/gpt-5.2",
    }


def test_bootstrap_rejects_non_openrouter_key(monkeypatch):
    monkeypatch.setattr(agentvm, "save_env_value", lambda *_: pytest.fail("secret must not be persisted"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agentvm.agentvm_bootstrap(agentvm.AgentVMBootstrapRequest(apiKey="x" * 30)))
    assert exc.value.status_code == 400


def test_bootstrap_can_clear_walton_managed_openrouter_key(monkeypatch):
    cleared = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-stale-secret-value-1234567890")
    monkeypatch.setattr(agentvm, "remove_env_value", lambda key: cleared.append(key))
    result = asyncio.run(agentvm.agentvm_bootstrap(agentvm.AgentVMBootstrapRequest(clear=True)))
    assert cleared == ["OPENROUTER_API_KEY"]
    assert "OPENROUTER_API_KEY" not in agentvm.os.environ
    assert result["inference"]["configured"] is False


def test_session_only_bootstrap_does_not_persist_secret(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(agentvm, "save_env_value", lambda *_: pytest.fail("session key must not be persisted"))
    monkeypatch.setattr(agentvm, "remove_env_value", lambda *_: None)
    monkeypatch.setattr(agentvm, "save_config", lambda *_args, **_kwargs: None)
    result = asyncio.run(agentvm.agentvm_bootstrap(agentvm.AgentVMBootstrapRequest(
        apiKey="sk-or-v1-session-secret-value-1234567890",
        persist=False,
    )))
    assert agentvm.os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-session-secret-value-1234567890"
    assert result["inference"]["configured"] is True


def test_health_reports_runtime_and_inference(monkeypatch):
    monkeypatch.setattr(
        agentvm,
        "_inference_status",
        lambda: {"configured": True, "provider": "openrouter", "model": "openrouter/auto"},
    )
    result = asyncio.run(agentvm.agentvm_health())
    assert result == {
        "ok": True,
        "runtime": "loki",
        "inference": {"configured": True, "provider": "openrouter", "model": "openrouter/auto"},
    }


def test_execute_translates_walton_request_into_loki_oneshot(monkeypatch):
    monkeypatch.setattr(
        agentvm,
        "_inference_status",
        lambda: {"configured": True, "provider": "openrouter", "model": "openrouter/auto"},
    )
    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self, input=None):
            captured["stdin"] = input
            return b"hello from loki\n", b""

        def kill(self):
            captured["killed"] = True

    async def fake_create(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(agentvm.asyncio, "create_subprocess_exec", fake_create)

    result = asyncio.run(
        agentvm.agentvm_execute(
            agentvm.AgentVMExecuteRequest(
                mode="act",
                action="bot_chat",
                instruction="Ship it",
                identityInstructions="You are my build agent.",
                contextBeforeCursor="Earlier context",
            )
        )
    )

    args = captured["args"]
    assert args[:2] == (agentvm.sys.executable, "-c")
    assert "Ship it" not in " ".join(args)
    prompt = captured["stdin"].decode("utf-8")
    assert "Ship it" in prompt
    assert "You are my build agent." in prompt
    assert "Earlier context" in prompt
    assert result["text"] == "hello from loki"
    assert result["agentRuntimeReady"] is True


def test_execute_requires_inference(monkeypatch):
    monkeypatch.setattr(
        agentvm,
        "_inference_status",
        lambda: {"configured": False, "provider": None, "model": None},
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agentvm.agentvm_execute(agentvm.AgentVMExecuteRequest(instruction="hi")))
    assert exc.value.status_code == 409


def test_agentvm_health_is_public_but_mutating_routes_are_not():
    from loki_cli.dashboard_auth.public_paths import PUBLIC_API_PATHS

    assert "/api/agentvm/health" in PUBLIC_API_PATHS
    assert "/api/agentvm/bootstrap" not in PUBLIC_API_PATHS
    assert "/api/agentvm/execute" not in PUBLIC_API_PATHS
