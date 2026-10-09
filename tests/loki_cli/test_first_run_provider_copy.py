from pathlib import Path


def test_first_run_provider_copy_does_not_advertise_portal_oauth():
    source = (Path(__file__).parents[2] / "loki_cli" / "cli_agent_setup_mixin.py").read_text()
    assert "WunderCorp Portal OAuth is the fastest" not in source
    assert "OpenRouter is the quickest" in source


def test_cli_provider_picker_hides_legacy_wundercorp_portal():
    from loki_cli.main_provider_setup import _build_provider_picker_rows
    rows, _ = _build_provider_picker_rows({}, "", {}, {})
    assert all(key != "wundercorp" for key, _label, _members in rows)
