from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from loki_cli.web_context import (
    ContextArchiveError,
    ContextNotFound,
    ContextOwnershipError,
    _CONTEXT_ARCHIVE_MAX_BYTES,
    delete_context,
    extract_context_archive,
    get_context,
)

router = APIRouter()
_UPLOAD_CHUNK_BYTES = 1024 * 1024


def _request_user_id(request: Request) -> str:
    session = getattr(request.state, "session", None)
    if session is not None and getattr(session, "user_id", ""):
        return str(session.user_id)
    if getattr(request.app.state, "auth_required", False):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return "local"


async def _stream_archive(file: UploadFile, target: Path) -> int:
    total = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > _CONTEXT_ARCHIVE_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="ZIP archive is too large")
                output.write(chunk)
        return total
    finally:
        await file.close()


@router.post("/api/context/upload")
async def upload_context(
    request: Request,
    file: UploadFile = File(...),
    label: str = Form(""),
):
    user_id = _request_user_id(request)
    filename = Path(file.filename or "context.zip").name
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=415, detail="Context upload must be a .zip archive")

    fd, raw_path = tempfile.mkstemp(prefix="loki-context-", suffix=".zip")
    os.close(fd)
    archive_path = Path(raw_path)
    try:
        await _stream_archive(file, archive_path)
        try:
            manifest = await asyncio.to_thread(
                extract_context_archive,
                archive_path,
                user_id=user_id,
                original_filename=filename,
                label=label,
            )
        except ContextArchiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        archive_path.unlink(missing_ok=True)

    return {
        "ok": True,
        **manifest.as_dict(),
        "chat_url": f"/chat?context={manifest.context_id}",
    }


@router.get("/api/context/{context_id}")
async def context_detail(request: Request, context_id: str):
    user_id = _request_user_id(request)
    try:
        manifest = get_context(user_id, context_id)
    except (ContextNotFound, ContextOwnershipError) as exc:
        raise HTTPException(status_code=404, detail="Context not found") from exc
    return manifest.as_dict()


@router.delete("/api/context/{context_id}")
async def remove_context(request: Request, context_id: str):
    user_id = _request_user_id(request)
    try:
        await asyncio.to_thread(delete_context, user_id, context_id)
    except (ContextNotFound, ContextOwnershipError) as exc:
        raise HTTPException(status_code=404, detail="Context not found") from exc
    return {"ok": True}
