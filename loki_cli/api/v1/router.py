from __future__ import annotations

from typing import Any

from loki_cli.web_routers import (
    actions,
    agentvm,
    analytics,
    audio,
    chat_ws,
    config_env,
    cron,
    dashboard_ui,
    files,
    git,
    local_models,
    mcp,
    memory_providers,
    messaging,
    models,
    oauth,
    ops,
    profiles,
    sessions,
    skills,
    status,
    tools,
)


def mount_api_routes(app: Any) -> None:
    app.include_router(agentvm.router)
    app.include_router(files.router)
    app.include_router(git.router)
    app.include_router(local_models.router)
    app.include_router(status.router)
    app.include_router(actions.router)
    app.include_router(audio.router)
    app.include_router(actions.status_router)
    app.include_router(sessions.list_router)
    app.include_router(profiles.sessions_router)
    app.include_router(sessions.search_router)
    app.include_router(memory_providers.router)
    app.include_router(config_env.config_router)
    app.include_router(models.router)
    app.include_router(config_env.router)
    app.include_router(messaging.router)
    app.include_router(oauth.router)
    app.include_router(sessions.manage_router)
    app.include_router(status.logs_router)
    app.include_router(cron.router)
    app.include_router(mcp.router)
    app.include_router(ops.router)
    app.include_router(skills.hub_router)
    app.include_router(profiles.router)
    app.include_router(skills.router)
    app.include_router(tools.router)
    app.include_router(analytics.router)
    app.include_router(chat_ws.router)
    app.include_router(dashboard_ui.router)
