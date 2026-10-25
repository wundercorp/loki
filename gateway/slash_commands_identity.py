"""Gateway /id command: AgentVerified ID lifecycle for the running Loki profile."""

from __future__ import annotations

import asyncio


class GatewayIdentityCommandsMixin:
    async def _handle_id_command(self, event) -> str:
        from loki_cli.quantpay_identity import run_id_command
        args = event.get_command_args() if hasattr(event, "get_command_args") else ""
        return await asyncio.to_thread(run_id_command, args)
