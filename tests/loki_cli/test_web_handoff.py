from __future__ import annotations

import zipfile
from pathlib import Path

from loki_cli import web_handoff


def test_build_archive_filters_heavy_and_sensitive_paths(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("print('ok')\n")
    (project / ".env").write_text("SECRET=value\n")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "dependency.js").write_text("large dependency")

    archive_path, temporary, included = web_handoff._build_archive(project)
    try:
        assert temporary is True
        assert included == 1
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.namelist() == ["project/src/main.py"]
    finally:
        archive_path.unlink(missing_ok=True)


def test_build_archive_accepts_existing_zip(tmp_path):
    archive_path = tmp_path / "ready.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.md", "hello")

    result_path, temporary, included = web_handoff._build_archive(archive_path)

    assert result_path == archive_path.resolve()
    assert temporary is False
    assert included == 0


def test_pkce_pair_matches_s256():
    verifier, challenge = web_handoff._pkce_pair()
    import base64
    import hashlib

    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert challenge == expected
