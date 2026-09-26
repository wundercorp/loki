"""The commit_count == 0 path must repair Node deps, not just Python (#77211).

A previous ``loki update`` whose npm install failed printed "Fix npm and
re-run `loki update`" — but re-running hit the "Already up to date!" early
return before the Node refresh, so the advice could never work. The repair
now runs through ``_repair_node_deps_on_current_checkout``, which delegates
to ``_update_node_dependencies`` (self-gating on the lockfile hash, recorded
only after a successful install, so healthy installs stay a cheap no-op).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from loki_cli import update_cmd


def test_current_checkout_repairs_failed_node_deps(capsys):
    """A recorded failure surfaces the fix-npm hint, not 'Already up to date!'."""
    completion = MagicMock()
    with patch.object(
        update_cmd, "_update_node_dependencies", return_value=["tui-ui, web workspaces"]
    ), patch.object(update_cmd, "_m") as m:
        update_cmd._repair_node_deps_on_current_checkout(completion)

    m.return_value._build_web_ui.assert_not_called()
    completion.assert_called_once()
    assert "could not be repaired" in completion.call_args[0][0]
    out = capsys.readouterr().out
    assert "Node.js refresh failed for: tui-ui, web workspaces" in out
    assert "Fix npm and re-run `loki update`." in out


def test_current_checkout_healthy_node_deps_reports_up_to_date():
    """A clean refresh (or lockfile-hash no-op) still says 'Already up to date!'."""
    completion = MagicMock()
    with patch.object(
        update_cmd, "_update_node_dependencies", return_value=[]
    ), patch.object(update_cmd, "_m") as m, patch.object(
        update_cmd, "_rebuild_desktop_after_update", return_value=True
    ):
        update_cmd._repair_node_deps_on_current_checkout(completion)

    # The refresh pairs with the web build like every other call site.
    m.return_value._build_web_ui.assert_called_once()
    completion.assert_called_once_with("✓ Already up to date!")


def test_current_checkout_web_build_failure_is_partial():
    completion = MagicMock()
    with patch.object(
        update_cmd, "_update_node_dependencies", return_value=[]
    ), patch.object(update_cmd, "_m") as m, patch.object(
        update_cmd, "_rebuild_desktop_after_update", return_value=True
    ):
        m.return_value._build_web_ui.return_value = False
        complete = update_cmd._repair_node_deps_on_current_checkout(completion)

    assert complete is False
    m.return_value._build_web_ui.assert_called_once_with(
        m.return_value.PROJECT_ROOT / "web", require_fresh=True
    )
    completion.assert_called_once()
    assert "web UI could not be rebuilt" in completion.call_args[0][0]
