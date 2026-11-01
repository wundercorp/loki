from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from loki_constants import get_loki_home

_CONTEXT_ROOT_NAME = "web-contexts"
_CONTEXT_ARCHIVE_MAX_BYTES = 100 * 1024 * 1024
_CONTEXT_EXPANDED_MAX_BYTES = 512 * 1024 * 1024
_CONTEXT_FILE_MAX_BYTES = 128 * 1024 * 1024
_CONTEXT_MAX_FILES = 20_000
_MANIFEST_NAME = ".loki-context.json"


class ContextError(Exception):
    pass


class ContextNotFound(ContextError):
    pass


class ContextOwnershipError(ContextError):
    pass


class ContextArchiveError(ContextError):
    pass


@dataclass(frozen=True)
class ContextManifest:
    context_id: str
    owner_key: str
    name: str
    original_filename: str
    created_at: int
    file_count: int
    expanded_bytes: int
    workspace_rel: str

    def as_dict(self) -> dict:
        return {
            "context_id": self.context_id,
            "name": self.name,
            "original_filename": self.original_filename,
            "created_at": self.created_at,
            "file_count": self.file_count,
            "expanded_bytes": self.expanded_bytes,
        }


def context_root() -> Path:
    return get_loki_home() / _CONTEXT_ROOT_NAME


def owner_key(user_id: str) -> str:
    value = (user_id or "local").encode("utf-8", "surrogatepass")
    return hashlib.sha256(value).hexdigest()[:32]


def owner_root(user_id: str) -> Path:
    return context_root() / owner_key(user_id)


def context_dir(user_id: str, context_id: str) -> Path:
    if not context_id or len(context_id) > 64 or any(ch not in "0123456789abcdef" for ch in context_id.lower()):
        raise ContextNotFound("Unknown context")
    return owner_root(user_id) / context_id.lower()


def _manifest_path(user_id: str, context_id: str) -> Path:
    return context_dir(user_id, context_id) / _MANIFEST_NAME


def _load_manifest(user_id: str, context_id: str) -> ContextManifest:
    path = _manifest_path(user_id, context_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContextNotFound("Unknown context") from exc
    if str(data.get("owner_key") or "") != owner_key(user_id):
        raise ContextOwnershipError("Context does not belong to this user")
    return ContextManifest(
        context_id=str(data["context_id"]),
        owner_key=str(data["owner_key"]),
        name=str(data.get("name") or data.get("original_filename") or "context"),
        original_filename=str(data.get("original_filename") or "context.zip"),
        created_at=int(data.get("created_at") or 0),
        file_count=int(data.get("file_count") or 0),
        expanded_bytes=int(data.get("expanded_bytes") or 0),
        workspace_rel=str(data.get("workspace_rel") or "workspace"),
    )


def get_context(user_id: str, context_id: str) -> ContextManifest:
    return _load_manifest(user_id, context_id)


def resolve_context_workspace(user_id: str, context_id: str) -> Path:
    manifest = _load_manifest(user_id, context_id)
    base = context_dir(user_id, manifest.context_id).resolve()
    workspace = (base / manifest.workspace_rel).resolve()
    try:
        workspace.relative_to(base)
    except ValueError as exc:
        raise ContextArchiveError("Context workspace is invalid") from exc
    if not workspace.is_dir():
        raise ContextNotFound("Context workspace is missing")
    return workspace


def delete_context(user_id: str, context_id: str) -> None:
    target = context_dir(user_id, context_id)
    _load_manifest(user_id, context_id)
    shutil.rmtree(target)


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    if "\x00" in normalized:
        raise ContextArchiveError("Archive contains an invalid filename")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ContextArchiveError(f"Archive contains an unsafe path: {name!r}")
    return path


def _member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _workspace_relative(workspace: Path) -> str:
    entries = list(workspace.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return str(Path("workspace") / entries[0].name)
    return "workspace"


def extract_context_archive(
    archive_path: Path,
    *,
    user_id: str,
    original_filename: str,
    label: str = "",
) -> ContextManifest:
    if archive_path.stat().st_size > _CONTEXT_ARCHIVE_MAX_BYTES:
        raise ContextArchiveError("Archive is too large")

    context_id = uuid.uuid4().hex
    owner = owner_root(user_id)
    owner.mkdir(parents=True, exist_ok=True)
    staging = owner / f".{context_id}.extracting"
    final = owner / context_id
    workspace = staging / "workspace"
    workspace.mkdir(parents=True, exist_ok=False)

    file_count = 0
    expanded_bytes = 0
    try:
        try:
            archive = zipfile.ZipFile(archive_path, "r")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ContextArchiveError("The uploaded file is not a valid ZIP archive") from exc

        with archive:
            infos = archive.infolist()
            if len(infos) > _CONTEXT_MAX_FILES:
                raise ContextArchiveError("Archive contains too many entries")
            for info in infos:
                member_path = _safe_member_path(info.filename)
                if info.flag_bits & 0x1:
                    raise ContextArchiveError("Encrypted ZIP archives are not supported")
                if _member_is_symlink(info):
                    raise ContextArchiveError("ZIP archives containing symbolic links are not supported")
                if info.file_size > _CONTEXT_FILE_MAX_BYTES:
                    raise ContextArchiveError(f"Archive member is too large: {info.filename}")
                expanded_bytes += int(info.file_size)
                if expanded_bytes > _CONTEXT_EXPANDED_MAX_BYTES:
                    raise ContextArchiveError("Expanded archive is too large")
                destination = workspace.joinpath(*member_path.parts)
                resolved_parent = destination.parent.resolve()
                try:
                    resolved_parent.relative_to(workspace.resolve())
                except ValueError as exc:
                    raise ContextArchiveError(f"Archive contains an unsafe path: {info.filename!r}") from exc
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                file_count += 1
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

        workspace_rel = _workspace_relative(workspace)
        clean_label = (label or "").strip()[:120]
        manifest = ContextManifest(
            context_id=context_id,
            owner_key=owner_key(user_id),
            name=clean_label or Path(original_filename).stem or "context",
            original_filename=Path(original_filename).name or "context.zip",
            created_at=int(time.time()),
            file_count=file_count,
            expanded_bytes=expanded_bytes,
            workspace_rel=workspace_rel,
        )
        (staging / _MANIFEST_NAME).write_text(
            json.dumps(
                {
                    **manifest.as_dict(),
                    "owner_key": manifest.owner_key,
                    "workspace_rel": manifest.workspace_rel,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(staging, final)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
