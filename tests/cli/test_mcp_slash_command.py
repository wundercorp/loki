from unittest.mock import MagicMock, patch

from cli import LokiCLI


def _cli():
    cli = LokiCLI.__new__(LokiCLI)
    cli._console_print = MagicMock()
    return cli


def test_mcp_slash_supercharger_configures_and_reloads():
    cli = _cli()
    cli._reload_mcp = MagicMock()
    with patch("loki_cli.mcp_config.configure_supercharger_mcp", return_value=(True, 7)) as configure:
        cli._handle_mcp_command("/mcp supercharger")
    configure.assert_called_once_with(token=None, url="https://mcp.supercharger.sh/")
    cli._reload_mcp.assert_called_once_with()


def test_mcp_slash_list_uses_existing_list_command():
    cli = _cli()
    with patch("loki_cli.mcp_config.cmd_mcp_list") as list_servers:
        cli._handle_mcp_command("/mcp")
    list_servers.assert_called_once_with()


def test_mcp_slash_help_is_self_documenting():
    cli = _cli()
    cli._handle_mcp_command("/mcp help")
    output = "\n".join(str(call.args[0]) for call in cli._console_print.call_args_list)
    assert "/mcp supercharger" in output
    assert "/mcp add <name> <url>" in output
    assert "/mcp reload" in output
