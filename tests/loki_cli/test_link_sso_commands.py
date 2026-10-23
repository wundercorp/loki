from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlparse

from loki_cli.commands import resolve_command
from loki_cli import link_connection, wundercorp_sso


def _jwt(payload: dict) -> str:
    import base64

    def enc(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{enc({'alg': 'none'})}.{enc(payload)}.sig"


def test_registry_exposes_sso_and_link_commands():
    sso = resolve_command("sso")
    link = resolve_command("link")
    wallet = resolve_command("wallet")
    assert sso is not None
    assert sso.cli_only is True
    assert sso.subcommands == ("status", "login", "logout")
    assert link is not None
    assert link.cli_only is True
    assert wallet is link
    assert "connect" in link.subcommands
    assert "address" in link.subcommands


def test_sso_authorization_url_uses_registered_loopback_and_pkce(monkeypatch):
    monkeypatch.delenv("LOKI_WUNDERCORP_SSO_DOMAIN", raising=False)
    monkeypatch.delenv("LOKI_WUNDERCORP_SSO_CLIENT_ID", raising=False)
    monkeypatch.delenv("LOKI_WUNDERCORP_SSO_REDIRECT_URI", raising=False)
    url = wundercorp_sso._authorization_url("state-value", "challenge-value")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://auth.wundercorp.co/oauth2/authorize"
    assert query["client_id"] == ["5kg855gamgk38cicro6pfbglcu"]
    assert query["redirect_uri"] == ["http://127.0.0.1:48741/auth/callback"]
    assert query["scope"] == ["openid email profile"]
    assert query["state"] == ["state-value"]
    assert query["code_challenge"] == ["challenge-value"]
    assert query["code_challenge_method"] == ["S256"]


def test_sso_refresh_uses_migrated_client_id(tmp_path, monkeypatch):
    monkeypatch.setattr(wundercorp_sso, "get_loki_home", lambda: tmp_path)
    monkeypatch.delenv("LOKI_WUNDERCORP_SSO_CLIENT_ID", raising=False)
    wundercorp_sso._save_state({"refresh_token": "refresh-token"})
    captured = {}
    new_access = _jwt({"token_use": "access", "client_id": "5kg855gamgk38cicro6pfbglcu", "exp": int(time.time()) + 3600})

    def fake_token_request(data, timeout_seconds=20.0):
        captured.update(data)
        return {"access_token": new_access}

    monkeypatch.setattr(wundercorp_sso, "_token_request", fake_token_request)

    assert wundercorp_sso.refresh_sso_session() == new_access
    assert captured["client_id"] == "5kg855gamgk38cicro6pfbglcu"
    stored = json.loads((tmp_path / "wundercorp-sso.json").read_text())
    assert stored["_client_id"] == "5kg855gamgk38cicro6pfbglcu"


def test_sso_rejects_access_token_from_previous_client_id(monkeypatch):
    monkeypatch.delenv("LOKI_WUNDERCORP_SSO_CLIENT_ID", raising=False)
    state = {
        "access_token": _jwt({
            "token_use": "access",
            "client_id": "42s62lgsghpne2r3gf8ret6ojf",
            "exp": int(time.time()) + 3600,
        })
    }

    assert wundercorp_sso._access_token_usable(state) is False


def test_sso_status_marks_previous_client_session_signed_out(tmp_path, monkeypatch):
    monkeypatch.setattr(wundercorp_sso, "get_loki_home", lambda: tmp_path)
    monkeypatch.delenv("LOKI_WUNDERCORP_SSO_CLIENT_ID", raising=False)
    wundercorp_sso._save_state({
        "access_token": _jwt({
            "token_use": "access",
            "client_id": "42s62lgsghpne2r3gf8ret6ojf",
            "exp": int(time.time()) + 3600,
        }),
        "refresh_token": "old-refresh-token",
    })

    status = wundercorp_sso.sso_status()

    assert status["signed_in"] is False
    assert status["access_token_valid"] is False


def test_sso_refresh_preserves_refresh_token(tmp_path, monkeypatch):
    monkeypatch.setattr(wundercorp_sso, "get_loki_home", lambda: tmp_path)
    old_refresh = "refresh-original"
    wundercorp_sso._save_state({
        "access_token": _jwt({"token_use": "access", "exp": int(time.time()) - 60}),
        "refresh_token": old_refresh,
    })
    new_access = _jwt({"token_use": "access", "exp": int(time.time()) + 3600})
    monkeypatch.setattr(wundercorp_sso, "_token_request", lambda data, timeout_seconds=20.0: {"access_token": new_access})
    assert wundercorp_sso.refresh_sso_session() == new_access
    stored = json.loads((tmp_path / "wundercorp-sso.json").read_text())
    assert stored["refresh_token"] == old_refresh
    assert stored["access_token"] == new_access


def test_link_connect_reuses_sso_and_polls(monkeypatch):
    statuses = iter([{"connected": False}, {"connected": False}, {"connected": True, "scope": "payment_methods.agentic userinfo:read"}])
    monkeypatch.setattr(link_connection, "link_status", lambda interactive_sso=False: next(statuses))
    monkeypatch.setattr(link_connection, "_request", lambda method, path, interactive_sso=False, retry_auth=True: {"authorization_url": "https://login.link.com/auth?x=1"})
    opened = []
    monkeypatch.setattr(link_connection.webbrowser, "open", opened.append)
    monkeypatch.setattr(link_connection.time, "sleep", lambda seconds: None)
    result = link_connection.connect_link(timeout_seconds=5)
    assert result["connected"] is True
    assert opened == ["https://login.link.com/auth?x=1"]


def test_link_status_copy_for_disconnected():
    assert link_connection.format_link_status({"connected": False}) == (
        "Link: not connected\nRun /link connect to connect your Link wallet."
    )


def test_link_address_uses_shipping_addresses_endpoint(monkeypatch):
    from loki_cli import cli_commands_mixin as commands_mixin
    from loki_cli.cli_commands_mixin import CLICommandsMixin

    calls = []
    outputs = []

    monkeypatch.setattr(
        link_connection,
        "link_shipping_addresses",
        lambda: calls.append("shipping-addresses") or {
            "addresses": [{"city": "New York", "country": "US"}]
        },
    )
    monkeypatch.setattr(commands_mixin, "_cp", lambda *lines: outputs.extend(lines))

    class Worker:
        def __init__(self, produce):
            self.produce = produce

        def start(self):
            outputs.append(self.produce())

    class Stub:
        _app = True

        def _side_worker(self, produce, **kwargs):
            return Worker(produce)

    CLICommandsMixin._handle_link_command(Stub(), "/link address")

    assert calls == ["shipping-addresses"]
    assert any('"city": "New York"' in output for output in outputs)


def test_link_cli_routes_all_general_commands(monkeypatch):
    from loki_cli import cli_commands_mixin as commands_mixin
    from loki_cli.cli_commands_mixin import CLICommandsMixin

    calls = []
    outputs = []

    monkeypatch.setattr(commands_mixin, "_cp", lambda *lines: outputs.extend(lines))
    monkeypatch.setattr(link_connection, "connect_link", lambda: calls.append("connect") or {"connected": True})
    monkeypatch.setattr(link_connection, "disconnect_link", lambda: calls.append("disconnect") or {"connected": False, "revoked": True})
    monkeypatch.setattr(link_connection, "link_status", lambda interactive_sso=False: calls.append(("status", interactive_sso)) or {"connected": True})
    monkeypatch.setattr(link_connection, "link_user_info", lambda: calls.append("user") or {"user": {}})
    monkeypatch.setattr(link_connection, "link_payment_methods", lambda: calls.append("payment-methods") or {"payment_methods": []})
    monkeypatch.setattr(link_connection, "link_shipping_addresses", lambda: calls.append("address") or {"addresses": []})

    class Worker:
        def __init__(self, produce):
            self.produce = produce

        def start(self):
            outputs.append(self.produce())

    class Stub:
        _app = True

        def _side_worker(self, produce, **kwargs):
            return Worker(produce)

    stub = Stub()
    for command in (
        "/link status",
        "/link connect",
        "/link disconnect",
        "/link user",
        "/link payment-methods",
        "/link address",
    ):
        CLICommandsMixin._handle_link_command(stub, command)

    assert calls == [
        ("status", False),
        "connect",
        "disconnect",
        "user",
        "payment-methods",
        "address",
    ]


def test_link_shipping_addresses_helper_calls_shipping_endpoint(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"addresses": []}

    monkeypatch.setattr(link_connection, "_request", fake_request)
    assert link_connection.link_shipping_addresses() == {"addresses": []}
    assert calls == [(
        "GET",
        "/api/link/shipping-addresses",
        {"interactive_sso": False},
    )]


def test_registry_exposes_go_shopping_command():
    go = resolve_command("go")
    assert go is not None
    assert go.cli_only is True
    assert go.subcommands == ("shopping", "ops", "status", "off")


def test_link_connection_spend_helpers_forward_json(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"id": "spend_123", "status": "pending"}

    monkeypatch.setattr(link_connection, "_request", fake_request)
    result = link_connection.create_spend_request({"amount": 999, "currency": "usd", "context": "x" * 100})
    assert result["id"] == "spend_123"
    assert calls == [(
        "POST",
        "/api/link/spend-requests",
        {"interactive_sso": False, "json_body": {"amount": 999, "currency": "usd", "context": "x" * 100}},
    )]


def test_go_shopping_enables_required_toolsets_and_prompt(monkeypatch):
    import loki_cli.config as config_module
    import loki_cli.tools_config as tools_config
    import loki_cli.cli_commands_mixin as commands_mixin
    from loki_cli.cli_commands_mixin import CLICommandsMixin

    config = {"platform_toolsets": {"cli": []}, "agent": {}, "browser": {}}
    saved = {}

    class Agent:
        ephemeral_system_prompt = None
        valid_tool_names = {
            "mcp__guardian_search__search_web",
            "mcp__guardian_search__search_shopping",
            "mcp__guardian_search__discover_sites",
            "browser_exec",
            "webmcp_lookup",
            "webmcp_list_tools",
            "webmcp_call",
            "link_wallet_status",
            "link_spend_create",
            "link_spend_request_approval",
            "link_spend_wait",
            "link_checkout_fill",
        }

        def _invalidate_system_prompt(self):
            return None

    class Worker:
        def __init__(self):
            self.started = False

        def start(self):
            self.started = True

    class Stub:
        def __init__(self):
            self.agent = Agent()
            self.enabled_toolsets = []
            self.disabled_toolsets = []
            self._app = True
            self.mutations = []
            self.reset_count = 0
            self.worker = Worker()

        def _run_tools_config(self, **kwargs):
            self.mutations.append(kwargs)
            for name in kwargs["names"]:
                if name not in config["platform_toolsets"]["cli"]:
                    config["platform_toolsets"]["cli"].append(name)

        def new_session(self):
            self.reset_count += 1

        def _side_worker(self, *args, **kwargs):
            return self.worker

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(config_module, "save_config", lambda value: saved.update(value))
    monkeypatch.setattr(
        tools_config,
        "_get_platform_tools",
        lambda cfg, platform, **kwargs: set(cfg.get("platform_toolsets", {}).get(platform, [])),
    )
    monkeypatch.setattr(commands_mixin, "_refresh_cli_toolsets", lambda cli: None)
    monkeypatch.setattr("tools.registry.invalidate_check_fn_cache", lambda: None)

    stub = Stub()
    CLICommandsMixin._handle_go_command(stub, "/go shopping")

    assert stub.mutations == [{
        "tools_action": "enable",
        "names": ["terminal", "web", "browser", "webmcp", "guardian_search", "link-wallet"],
        "platform": "cli",
    }]
    assert saved["browser"]["backend"] == "browser-use"
    assert stub.reset_count == 1
    assert stub._go_mode == "shopping"
    assert "[LOKI_GO_SHOPPING]" in stub.agent.ephemeral_system_prompt
    assert stub.worker.started is True


def test_go_shopping_fails_closed_when_required_toolset_cannot_enable(monkeypatch):
    from loki_cli import cli_commands_mixin as commands_mixin
    from loki_cli import config as config_module
    from loki_cli import tools_config
    from loki_cli.cli_commands_mixin import CLICommandsMixin

    config = {"platform_toolsets": {"cli": []}, "browser": {}}
    outputs = []

    class Stub:
        def __init__(self):
            self.agent = None
            self._app = True
            self.reset_count = 0

        def _run_tools_config(self, **kwargs):
            for name in kwargs["names"]:
                if name != "link-wallet":
                    config["platform_toolsets"]["cli"].append(name)

        def new_session(self):
            self.reset_count += 1

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(config_module, "save_config", lambda value: None)
    monkeypatch.setattr(
        tools_config,
        "_get_platform_tools",
        lambda cfg, platform, **kwargs: set(cfg.get("platform_toolsets", {}).get(platform, [])),
    )
    monkeypatch.setattr(commands_mixin, "_cp", lambda *lines: outputs.append(lines))
    monkeypatch.setattr("tools.registry.invalidate_check_fn_cache", lambda: None)

    stub = Stub()
    CLICommandsMixin._handle_go_command(stub, "/go shopping")

    assert stub.reset_count == 0
    assert any("Missing required toolsets: link-wallet" in line for call in outputs for line in call)


def test_go_shopping_fails_closed_when_runtime_tools_are_missing(monkeypatch):
    import loki_cli.config as config_module
    import loki_cli.tools_config as tools_config
    import loki_cli.cli_commands_mixin as commands_mixin
    from loki_cli.cli_commands_mixin import CLICommandsMixin

    config = {
        "platform_toolsets": {"cli": ["terminal", "web", "browser", "webmcp", "guardian_search", "link-wallet"]},
        "agent": {},
        "browser": {"backend": "browser-use"},
    }
    outputs = []

    class Agent:
        ephemeral_system_prompt = None
        valid_tool_names = {"browser_exec", "link_wallet_status"}

        def _invalidate_system_prompt(self):
            return None

    class Stub:
        def __init__(self):
            self.agent = Agent()
            self._app = True
            self.reset_count = 0
            self._go_mode = None

        def _run_tools_config(self, **kwargs):
            raise AssertionError("toolsets were already configured")

        def new_session(self):
            self.reset_count += 1

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(config_module, "save_config", lambda value: None)
    monkeypatch.setattr(
        tools_config,
        "_get_platform_tools",
        lambda cfg, platform, **kwargs: set(cfg["platform_toolsets"][platform]),
    )
    monkeypatch.setattr(commands_mixin, "_refresh_cli_toolsets", lambda cli: None)
    monkeypatch.setattr(commands_mixin, "_cp", lambda *lines: outputs.append(lines))
    monkeypatch.setattr("tools.registry.invalidate_check_fn_cache", lambda: None)

    stub = Stub()
    CLICommandsMixin._handle_go_command(stub, "/go shopping")

    assert stub.reset_count == 1
    assert stub._go_mode is None
    flattened = "\n".join(line for call in outputs for line in call)
    assert "fresh agent is missing required runtime tools" in flattened
    assert "link_spend_create" in flattened
    assert "link_checkout_fill" in flattened


def test_go_shopping_eagerly_initializes_lazy_agent(monkeypatch):
    import loki_cli.config as config_module
    import loki_cli.tools_config as tools_config
    import loki_cli.cli_commands_mixin as commands_mixin
    from loki_cli.cli_commands_mixin import CLICommandsMixin

    config = {
        "platform_toolsets": {"cli": ["terminal", "web", "browser", "webmcp", "guardian_search", "link-wallet"]},
        "agent": {},
        "browser": {"backend": "browser-use"},
    }
    outputs = []

    class Agent:
        ephemeral_system_prompt = None
        valid_tool_names = {
            "mcp__guardian_search__search_web",
            "mcp__guardian_search__search_shopping",
            "mcp__guardian_search__discover_sites",
            "browser_exec",
            "webmcp_lookup",
            "webmcp_list_tools",
            "webmcp_call",
            "link_wallet_status",
            "link_spend_create",
            "link_spend_request_approval",
            "link_spend_wait",
            "link_checkout_fill",
        }

        def _invalidate_system_prompt(self):
            return None

    class Stub:
        def __init__(self):
            self.agent = None
            self._app = True
            self.enabled_toolsets = list(config["platform_toolsets"]["cli"])
            self.disabled_toolsets = []
            self.reset_count = 0
            self.init_count = 0
            self.worker = type("Worker", (), {"start": lambda self: None})()

        def _run_tools_config(self, **kwargs):
            raise AssertionError("toolsets were already configured")

        def new_session(self):
            self.reset_count += 1
            self.agent = None

        def _init_agent(self):
            self.init_count += 1
            self.agent = Agent()
            return True

        def _side_worker(self, *args, **kwargs):
            return self.worker

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(config_module, "save_config", lambda value: None)
    monkeypatch.setattr(
        tools_config,
        "_get_platform_tools",
        lambda cfg, platform, **kwargs: set(cfg["platform_toolsets"][platform]),
    )
    monkeypatch.setattr(commands_mixin, "_refresh_cli_toolsets", lambda cli: None)
    monkeypatch.setattr(commands_mixin, "_cp", lambda *lines: outputs.append(lines))
    monkeypatch.setattr("tools.registry.invalidate_check_fn_cache", lambda: None)

    stub = Stub()
    CLICommandsMixin._handle_go_command(stub, "/go shopping")

    assert stub.reset_count == 1
    assert stub.init_count == 1
    assert stub._go_mode == "shopping"
    assert "[LOKI_GO_SHOPPING]" in stub.agent.ephemeral_system_prompt
    assert any("/go shopping enabled" in line for call in outputs for line in call)


def test_go_shopping_reenables_globally_disabled_toolsets(monkeypatch):
    import loki_cli.config as config_module
    import loki_cli.tools_config as tools_config
    import loki_cli.cli_commands_mixin as commands_mixin
    from loki_cli.cli_commands_mixin import CLICommandsMixin

    config = {
        "platform_toolsets": {"cli": ["terminal", "web", "browser", "webmcp", "guardian_search", "link-wallet"]},
        "agent": {"disabled_toolsets": ["browser", "link-wallet"]},
        "browser": {"backend": "browser-use"},
    }

    class Agent:
        ephemeral_system_prompt = None
        valid_tool_names = {
            "mcp__guardian_search__search_web", "mcp__guardian_search__search_shopping", "mcp__guardian_search__discover_sites",
            "browser_exec", "webmcp_lookup", "webmcp_list_tools", "webmcp_call", "link_wallet_status", "link_spend_create",
            "link_spend_request_approval", "link_spend_wait", "link_checkout_fill",
        }
        def _invalidate_system_prompt(self):
            return None

    class Stub:
        def __init__(self):
            self.agent = Agent()
            self._app = True
            self.enabled_toolsets = list(config["platform_toolsets"]["cli"])
            self.disabled_toolsets = list(config["agent"]["disabled_toolsets"])
            self.mutations = []
            self.worker = type("Worker", (), {"start": lambda self: None})()

        def _run_tools_config(self, **kwargs):
            self.mutations.append(kwargs)
            config["agent"]["disabled_toolsets"] = [
                name for name in config["agent"]["disabled_toolsets"]
                if name not in kwargs["names"]
            ]

        def new_session(self):
            return None

        def _side_worker(self, *args, **kwargs):
            return self.worker

    monkeypatch.setattr(config_module, "load_config", lambda: config)
    monkeypatch.setattr(config_module, "save_config", lambda value: None)
    monkeypatch.setattr(
        tools_config,
        "_get_platform_tools",
        lambda cfg, platform, **kwargs: set(cfg["platform_toolsets"][platform]),
    )
    monkeypatch.setattr(commands_mixin, "_refresh_cli_toolsets", lambda cli: None)
    monkeypatch.setattr(commands_mixin, "_cp", lambda *lines: None)
    monkeypatch.setattr("tools.registry.invalidate_check_fn_cache", lambda: None)

    stub = Stub()
    CLICommandsMixin._handle_go_command(stub, "/go shopping")

    assert stub.mutations == [{
        "tools_action": "enable",
        "names": ["browser", "link-wallet"],
        "platform": "cli",
    }]
    assert config["agent"]["disabled_toolsets"] == []
    assert stub._go_mode == "shopping"
