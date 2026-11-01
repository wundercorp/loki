from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import tempfile
import webbrowser
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

_DEFAULT_WEB_URL = "https://chat.loki.computer"
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_SOURCE_FILE_BYTES = 128 * 1024 * 1024
_EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".next",
    ".turbo",
    ".cache",
    "dist",
    "build",
}
_SENSITIVE_BASENAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    "credentials",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


class HandoffError(RuntimeError):
    pass


@dataclass
class _LoopbackResult:
    code: str = ""
    state: str = ""
    error: str = ""


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if name in _SENSITIVE_BASENAMES:
        return True
    return path.suffix.lower() in _SENSITIVE_SUFFIXES


def _iter_source_files(root: Path) -> Iterable[Path]:
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directory_names[:] = [
            name
            for name in directory_names
            if name not in _EXCLUDED_DIRECTORY_NAMES
            and not (current_path / name).is_symlink()
        ]
        for file_name in file_names:
            source = current_path / file_name
            if source.is_symlink() or _is_sensitive(source):
                continue
            try:
                size = source.stat().st_size
            except OSError:
                continue
            if size > _MAX_SOURCE_FILE_BYTES:
                continue
            yield source


def _build_archive(source: Path) -> tuple[Path, bool, int]:
    source = source.expanduser().resolve()
    if not source.exists():
        raise HandoffError(f"Path does not exist: {source}")
    if source.is_file():
        if source.suffix.lower() != ".zip":
            raise HandoffError("A file handoff must be an existing .zip archive or a directory.")
        if source.stat().st_size > _MAX_ARCHIVE_BYTES:
            raise HandoffError("ZIP archive is larger than the 100 MB upload limit.")
        return source, False, 0
    if not source.is_dir():
        raise HandoffError(f"Unsupported handoff path: {source}")

    fd, raw_path = tempfile.mkstemp(prefix="loki-handoff-", suffix=".zip")
    os.close(fd)
    archive_path = Path(raw_path)
    included = 0
    root_name = source.name or "workspace"
    try:
        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for file_path in _iter_source_files(source):
                relative = file_path.relative_to(source)
                archive.write(file_path, arcname=str(Path(root_name) / relative))
                included += 1
        if included == 0:
            raise HandoffError("No uploadable files were found in the selected directory.")
        if archive_path.stat().st_size > _MAX_ARCHIVE_BYTES:
            raise HandoffError(
                "Generated ZIP is larger than the 100 MB upload limit. "
                "Use a smaller directory or create a filtered ZIP first."
            )
        return archive_path, True, included
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


def _native_login(base_url: str, *, open_browser: bool = True) -> str:
    verifier, challenge = _pkce_pair()
    expected_state = secrets.token_urlsafe(32)
    result = _LoopbackResult()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            values = parse_qs(parsed.query)
            result.code = values.get("code", [""])[0]
            result.state = values.get("state", [""])[0]
            result.error = values.get("error", [""])[0]
            ok = bool(result.code) and result.state == expected_state and not result.error
            body = (
                "<html><body><h2>Loki handoff authenticated.</h2>"
                "<p>You can close this tab and return to the terminal.</p></body></html>"
                if ok
                else "<html><body><h2>Loki handoff could not authenticate.</h2></body></html>"
            ).encode("utf-8")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 600
    host, port = server.server_address[:2]
    redirect_uri = f"http://{host}:{port}/callback"
    query = urlencode(
        {
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": redirect_uri,
            "state": expected_state,
        }
    )
    authorize_url = f"{base_url}/auth/native/authorize?{query}"

    print(f"Authenticate in your browser: {authorize_url}")
    if open_browser:
        webbrowser.open(authorize_url, new=2)
    try:
        server.handle_request()
    finally:
        server.server_close()

    if result.error:
        raise HandoffError(f"Authentication failed: {result.error}")
    if not result.code or result.state != expected_state:
        raise HandoffError("Authentication callback was missing a valid code or state.")

    try:
        response = httpx.post(
            f"{base_url}/auth/native/token",
            json={"code": result.code, "code_verifier": verifier},
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise HandoffError(f"Could not redeem the web login: {exc}") from exc
    if response.status_code != 200:
        raise HandoffError(f"Web login token exchange failed with HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HandoffError("Web login token exchange returned invalid JSON.") from exc
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise HandoffError("Web login token exchange returned no access token.")
    return access_token


def _upload_context(base_url: str, access_token: str, archive_path: Path, label: str) -> dict:
    try:
        with archive_path.open("rb") as handle:
            response = httpx.post(
                f"{base_url}/api/context/upload",
                headers={"Authorization": f"Bearer {access_token}"},
                files={"file": (archive_path.name, handle, "application/zip")},
                data={"label": label},
                timeout=120.0,
            )
    except httpx.RequestError as exc:
        raise HandoffError(f"Could not upload workspace context: {exc}") from exc
    if response.status_code != 200:
        detail = ""
        try:
            detail = str(response.json().get("detail") or "")
        except ValueError:
            detail = response.text.strip()
        suffix = f": {detail}" if detail else ""
        raise HandoffError(f"Workspace upload failed with HTTP {response.status_code}{suffix}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HandoffError("Workspace upload returned invalid JSON.") from exc
    if not payload.get("context_id"):
        raise HandoffError("Workspace upload returned no context ID.")
    return payload


def handoff_command(args) -> int:
    base_url = str(getattr(args, "url", _DEFAULT_WEB_URL) or _DEFAULT_WEB_URL).strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print(f"✗ Invalid Loki web URL: {base_url}", file=sys.stderr)
        return 2

    source = Path(getattr(args, "path", ".") or ".")
    label = str(getattr(args, "label", "") or "").strip()
    open_browser = not bool(getattr(args, "no_open", False))
    archive_path: Path | None = None
    temporary_archive = False
    try:
        archive_path, temporary_archive, included = _build_archive(source)
        if source.expanduser().resolve().is_dir():
            print(f"Prepared {included:,} files for handoff.")
        access_token = _native_login(base_url, open_browser=open_browser)
        if not label:
            label = source.expanduser().resolve().name or "workspace"
        uploaded = _upload_context(base_url, access_token, archive_path, label)
        chat_path = str(uploaded.get("chat_url") or f"/chat?context={uploaded['context_id']}")
        chat_url = urljoin(f"{base_url}/", chat_path.lstrip("/"))
        print(f"Workspace uploaded: {uploaded.get('file_count', 0):,} files")
        print(f"Web handoff: {chat_url}")
        if open_browser:
            webbrowser.open(chat_url, new=2)
        return 0
    except HandoffError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    finally:
        if temporary_archive and archive_path is not None:
            archive_path.unlink(missing_ok=True)
