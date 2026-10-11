"""Private loopback API used by AgentVM's authenticated HTTPS gateway.

These routes are intended for ``loki serve`` bound to 127.0.0.1. AgentVM owns
public authentication (Walton Ed25519 signatures) and forwards only verified
requests here. Provider credentials never transit the AgentVM control plane.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from loki_cli.config import load_config, remove_env_value, save_config, save_env_value

router = APIRouter()


class AgentVMBootstrapRequest(BaseModel):
    provider: str = "openrouter"
    apiKey: Optional[str] = Field(default=None, max_length=1024)
    model: str = "openrouter/auto"
    persist: bool = False
    clear: bool = False


class AgentVMExecuteRequest(BaseModel):
    mode: Optional[str] = None
    action: Optional[str] = None
    instruction: str = Field(default="Continue.", max_length=200_000)
    contextBeforeCursor: Optional[str] = Field(default=None, max_length=300_000)
    contextAfterCursor: Optional[str] = Field(default=None, max_length=300_000)
    executionPolicy: Optional[str] = None
    source: Optional[str] = None
    eventContext: Optional[str] = Field(default=None, max_length=100_000)
    requestedIntegration: Optional[str] = None
    requestedOutcome: Optional[str] = None
    commerceApproval: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    identityInstructions: Optional[str] = Field(default=None, max_length=50_000)


def _model_config() -> tuple[str, str]:
    try:
        cfg = load_config()
        model_cfg = cfg.get("model") if isinstance(cfg, dict) else None
        if isinstance(model_cfg, dict):
            return str(model_cfg.get("provider") or ""), str(model_cfg.get("default") or "")
    except Exception:
        pass
    return "", ""


def _inference_status() -> dict[str, Any]:
    provider, model = _model_config()
    openrouter_key = str(os.getenv("OPENROUTER_API_KEY") or "").strip()
    configured = provider == "openrouter" and bool(openrouter_key)
    return {
        "configured": configured,
        "provider": provider or None,
        "model": model or None,
    }


@router.get("/api/agentvm/health")
async def agentvm_health() -> dict[str, Any]:
    return {"ok": True, "runtime": "loki", "inference": _inference_status()}


@router.post("/api/agentvm/bootstrap")
async def agentvm_bootstrap(body: AgentVMBootstrapRequest) -> dict[str, Any]:
    provider = body.provider.strip().lower()
    if provider != "openrouter":
        raise HTTPException(status_code=400, detail="AgentVM bootstrap currently supports OpenRouter only.")

    model = body.model.strip() or "openrouter/auto"
    if body.clear:
        # AgentVM-managed credentials are intentionally volatile so provider snapshots
        # never clone a user's inference secret. Clear both any legacy persisted value
        # and the current process copy; Walton will rehydrate on the next paired sync.
        remove_env_value("OPENROUTER_API_KEY")
        os.environ.pop("OPENROUTER_API_KEY", None)
        return {
            "ok": True,
            "runtime": "loki",
            "inference": {"configured": False, "provider": "openrouter", "model": model},
        }

    api_key = (body.apiKey or "").strip()
    if not api_key.startswith("sk-or-"):
        raise HTTPException(status_code=400, detail="The OpenRouter API key format is invalid.")

    # AgentVM snapshots must never capture inference credentials. The paired Walton
    # device is the authority and rehydrates this process after boot/restart. Remove
    # any value persisted by older AgentVM builds, then keep the current key only in
    # this process environment. ``persist`` is accepted for wire compatibility but
    # deliberately ignored on this private AgentVM bridge.
    remove_env_value("OPENROUTER_API_KEY")
    os.environ["OPENROUTER_API_KEY"] = api_key
    # Partial merge preserves every unrelated user setting. The model is not secret.
    save_config({"model": {"provider": "openrouter", "default": model}}, merge_existing=True)

    return {
        "ok": True,
        "runtime": "loki",
        "inference": {"configured": True, "provider": "openrouter", "model": model},
    }


def _walton_prompt(body: AgentVMExecuteRequest) -> str:
    sections: list[str] = []
    if body.identityInstructions and body.identityInstructions.strip():
        sections.append("Agent identity instructions:\n" + body.identityInstructions.strip())
    metadata = [
        f"Mode: {body.mode}" if body.mode else "",
        f"Action: {body.action}" if body.action else "",
        f"Execution policy: {body.executionPolicy}" if body.executionPolicy else "",
        f"Requested integration: {body.requestedIntegration}" if body.requestedIntegration else "",
        f"Requested outcome: {body.requestedOutcome}" if body.requestedOutcome else "",
    ]
    metadata = [item for item in metadata if item]
    if metadata:
        sections.append("Walton request metadata:\n" + "\n".join(metadata))
    context = [value.strip() for value in (body.contextBeforeCursor, body.contextAfterCursor, body.eventContext) if value and value.strip()]
    if context:
        sections.append("Context from Walton:\n" + "\n\n".join(context))
    sections.append("User request:\n" + (body.instruction.strip() or "Continue."))
    return "\n\n".join(sections)


@router.post("/api/agentvm/execute")
async def agentvm_execute(body: AgentVMExecuteRequest) -> dict[str, Any]:
    inference = _inference_status()
    if not inference["configured"]:
        raise HTTPException(status_code=409, detail="Loki is running, but inference is not configured yet.")

    prompt = _walton_prompt(body)
    env = os.environ.copy()
    env["LOKI_INTERACTIVE"] = "0"
    try:
        # Feed the Walton prompt over stdin rather than argv: large editor context can
        # exceed Linux's per-argument limit, and user text should not appear in `ps`.
        runner = (
            "import sys; "
            "prompt=sys.stdin.read(); "
            "sys.argv=['loki','--oneshot',prompt]; "
            "from loki_cli.main import main; main()"
        )
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            runner,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(prompt.encode("utf-8")), timeout=300)
    except asyncio.TimeoutError:
        try:
            proc.kill()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        raise HTTPException(status_code=504, detail="Loki inference timed out.") from None
    except OSError:
        raise HTTPException(status_code=503, detail="Loki inference process could not start.") from None

    text = stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 or not text:
        # Keep local/provider diagnostics local. Provider responses can contain request
        # metadata and must never be reflected through the public AgentVM gateway.
        raise HTTPException(status_code=502, detail="Loki inference failed.")

    return {
        "text": text,
        "agentRuntimeReady": True,
        "runtime": "loki",
        "inference": inference,
    }
