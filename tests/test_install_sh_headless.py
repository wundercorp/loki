"""Regression coverage for the server/headless installer shape.

Headless installs are used by managed VMs/containers that run ``loki serve``.
They must not enter npm/browser/TUI setup: a browser-workspace registry failure
must never prevent the Python agent backend from being installed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def test_headless_flag_is_documented_and_forces_server_policy() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert "--headless|--server)" in text
    assert 'if [ "$HEADLESS" = true ]; then' in text
    assert "RUN_SETUP=false" in text
    assert "SKIP_BROWSER=true" in text
    assert "SKIP_COMPUTER_USE=true" in text
    assert "INCLUDE_DESKTOP=false" in text
    assert "NON_INTERACTIVE=true" in text
    assert "loki serve --host 127.0.0.1 --port 8081" in text


def test_headless_node_deps_stage_never_invokes_node_or_npm(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / "package.json").write_text('{"name":"headless-probe"}\n', encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tripwire = tmp_path / "tripwire"
    for name in ("node", "npm"):
        path = bin_dir / name
        path.write_text(
            "#!/bin/sh\n"
            f"echo {name} >> {tripwire}\n"
            "exit 99\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "LOKI_INSTALL_DIR": str(install_dir),
            "LOKI_HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:{env['PATH']}",
        }
    )
    proc = subprocess.run(
        [
            "bash",
            str(INSTALL_SH),
            "--headless",
            "--stage",
            "node-deps",
            "--json",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.splitlines()[-1])
    assert result == {"ok": True, "stage": "node-deps", "skipped": False}
    assert "Skipping Node/browser stage (--headless)" in proc.stdout
    assert not tripwire.exists(), tripwire.read_text(encoding="utf-8") if tripwire.exists() else ""


def test_headless_policy_wins_over_conflicting_later_flags() -> None:
    # --manifest exits before installation, which makes this a cheap argument
    # parsing regression test. Source the script and print the effective state.
    script = f'''\nsource "{INSTALL_SH}" --headless --include-desktop --manifest >/dev/null\nprintf '%s %s %s %s %s\\n' "$HEADLESS" "$SKIP_BROWSER" "$SKIP_COMPUTER_USE" "$INCLUDE_DESKTOP" "$RUN_SETUP"\n'''
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert proc.stdout.strip() == "true true true false false"
