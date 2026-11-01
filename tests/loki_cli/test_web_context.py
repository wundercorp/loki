from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from loki_cli import web_context


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_extract_context_archive_and_resolve_single_root(tmp_path, monkeypatch):
    monkeypatch.setattr(web_context, "get_loki_home", lambda: tmp_path / "home")
    archive_path = tmp_path / "project.zip"
    _write_zip(
        archive_path,
        {
            "project/README.md": b"hello",
            "project/src/main.py": b"print('ok')\n",
        },
    )

    manifest = web_context.extract_context_archive(
        archive_path,
        user_id="cognito-user-a",
        original_filename="project.zip",
    )

    workspace = web_context.resolve_context_workspace("cognito-user-a", manifest.context_id)
    assert workspace.name == "project"
    assert (workspace / "README.md").read_text() == "hello"
    assert manifest.file_count == 2
    assert manifest.expanded_bytes == len(b"hello") + len(b"print('ok')\n")


def test_context_is_scoped_to_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(web_context, "get_loki_home", lambda: tmp_path / "home")
    archive_path = tmp_path / "project.zip"
    _write_zip(archive_path, {"project/file.txt": b"secret"})

    manifest = web_context.extract_context_archive(
        archive_path,
        user_id="owner-a",
        original_filename="project.zip",
    )

    with pytest.raises(web_context.ContextNotFound):
        web_context.resolve_context_workspace("owner-b", manifest.context_id)


def test_extract_context_rejects_parent_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(web_context, "get_loki_home", lambda: tmp_path / "home")
    archive_path = tmp_path / "bad.zip"
    _write_zip(archive_path, {"../outside.txt": b"no"})

    with pytest.raises(web_context.ContextArchiveError, match="unsafe path"):
        web_context.extract_context_archive(
            archive_path,
            user_id="owner",
            original_filename="bad.zip",
        )

    assert not (tmp_path / "outside.txt").exists()


def test_extract_context_rejects_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(web_context, "get_loki_home", lambda: tmp_path / "home")
    archive_path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("project/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../outside")

    with pytest.raises(web_context.ContextArchiveError, match="symbolic links"):
        web_context.extract_context_archive(
            archive_path,
            user_id="owner",
            original_filename="symlink.zip",
        )


def test_extract_context_enforces_expanded_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(web_context, "get_loki_home", lambda: tmp_path / "home")
    monkeypatch.setattr(web_context, "_CONTEXT_EXPANDED_MAX_BYTES", 5)
    archive_path = tmp_path / "large.zip"
    _write_zip(archive_path, {"project/file.txt": b"123456"})

    with pytest.raises(web_context.ContextArchiveError, match="Expanded archive"):
        web_context.extract_context_archive(
            archive_path,
            user_id="owner",
            original_filename="large.zip",
        )


def test_context_upload_router_uses_local_owner_when_auth_is_off(tmp_path, monkeypatch):
    import io

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from loki_cli.web_routers.context import router

    monkeypatch.setattr(web_context, "get_loki_home", lambda: tmp_path / "home")
    app = FastAPI()
    app.state.auth_required = False
    app.include_router(router)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project/README.md", "hello")

    client = TestClient(app)
    response = client.post(
        "/api/context/upload",
        files={"file": ("project.zip", archive_buffer.getvalue(), "application/zip")},
        data={"label": "Project"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Project"
    assert payload["file_count"] == 1
    detail = client.get(f"/api/context/{payload['context_id']}")
    assert detail.status_code == 200
    assert detail.json()["context_id"] == payload["context_id"]
