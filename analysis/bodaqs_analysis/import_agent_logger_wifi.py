from __future__ import annotations

import http.client
import json
import os
import socket
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .import_agent_sources import (
    LOGGER_WIFI_CLEANUP_DELETE,
    LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED,
    LOGGER_WIFI_CLEANUP_NONE,
    SUPPORTED_LOGGER_WIFI_CLEANUP_MODES,
    normalize_logger_wifi_base_url,
)


class LoggerWifiApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error: Optional[str] = None,
        response_body: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        self.error = error
        self.response_body = response_body
        parts = []
        if status_code is not None:
            parts.append(f"HTTP {status_code}")
        if error:
            parts.append(error)
        parts.append(message)
        super().__init__(": ".join(parts))


@dataclass(frozen=True)
class LoggerWifiApiClient:
    base_url: str
    request_timeout_s: float = 5.0
    download_timeout_s: float = 60.0

    def __post_init__(self) -> None:
        normalized = normalize_logger_wifi_base_url(self.base_url)
        if normalized is None:
            raise ValueError("base_url must be a non-empty absolute http(s) URL")
        object.__setattr__(self, "base_url", normalized)
        if float(self.request_timeout_s) <= 0:
            raise ValueError("request_timeout_s must be > 0")
        if float(self.download_timeout_s) <= 0:
            raise ValueError("download_timeout_s must be > 0")

    def get_device(self) -> dict[str, Any]:
        obj = self._request_json("GET", "/api/v1/device")
        self._require_schema(obj, "bodaqs.logger.device")
        if not str(obj.get("logger_id") or "").strip():
            raise LoggerWifiApiError("/api/v1/device did not include a non-empty logger_id")
        return obj

    def get_status(self) -> dict[str, Any]:
        obj = self._request_json("GET", "/api/v1/status")
        self._require_schema(obj, "bodaqs.logger.status")
        return obj

    def enter_upload_mode(self) -> dict[str, Any]:
        obj = self._request_json("POST", "/api/v1/upload-mode/enter")
        self._require_schema(obj, "bodaqs.logger.upload_mode")
        return obj

    def exit_upload_mode(self) -> dict[str, Any]:
        obj = self._request_json("POST", "/api/v1/upload-mode/exit")
        self._require_schema(obj, "bodaqs.logger.upload_mode")
        return obj

    def list_sessions(self) -> list[dict[str, Any]]:
        obj = self._request_json("GET", "/api/v1/sessions")
        self._require_schema(obj, "bodaqs.logger.sessions")
        sessions = obj.get("sessions")
        if not isinstance(sessions, list):
            raise LoggerWifiApiError("/api/v1/sessions response did not include a sessions list")

        out: list[dict[str, Any]] = []
        for idx, item in enumerate(sessions):
            if not isinstance(item, Mapping):
                raise LoggerWifiApiError(f"/api/v1/sessions entry {idx} is not an object")
            session_id = str(item.get("session_id") or "").strip()
            if not session_id:
                raise LoggerWifiApiError(f"/api/v1/sessions entry {idx} is missing session_id")
            out.append(dict(item))
        return out

    def download_archive_to_part(
        self,
        session_id: str,
        target_path: str | Path,
        *,
        chunk_size: int = 1024 * 256,
    ) -> Path:
        session_id = str(session_id or "").strip()
        if not session_id:
            raise ValueError("session_id must be non-empty")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")

        target = Path(target_path).expanduser().resolve()
        part_path = Path(str(target) + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        if part_path.exists():
            part_path.unlink()

        request = Request(
            self._url("/api/v1/session/archive", {"id": session_id}),
            headers={"Accept": "application/zip"},
            method="GET",
        )

        try:
            with self._open(request, timeout_s=float(self.download_timeout_s)) as response:
                expected_size = self._content_length(response)
                bytes_written = 0
                with part_path.open("wb") as out:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out.write(chunk)
                        bytes_written += len(chunk)

                if expected_size is not None and bytes_written != expected_size:
                    raise LoggerWifiApiError(
                        f"Archive download was incomplete: expected {expected_size} bytes, got {bytes_written}",
                        error="download_incomplete",
                    )

            self._validate_zip(part_path)
            os.replace(part_path, target)
            return target
        except Exception as exc:
            if isinstance(exc, LoggerWifiApiError):
                raise
            raise LoggerWifiApiError(f"Archive download failed: {exc}", error="download_failed") from exc

    def ack_session(
        self,
        *,
        session_id: str,
        status: str = "imported",
        library_id: Optional[str] = None,
        run_id: Optional[str] = None,
        imported_at: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = {
            "session_id": session_id,
            "status": status,
            "library_id": library_id or "",
            "run_id": run_id or "",
            "imported_at": imported_at or "",
        }
        obj = self._request_json("POST", "/api/v1/session/ack", payload=payload)
        self._require_schema(obj, "bodaqs.logger.session_ack")
        return obj

    def cleanup_session(self, *, session_id: str, mode: str = LOGGER_WIFI_CLEANUP_NONE) -> dict[str, Any]:
        mode = str(mode or "").strip().lower()
        if mode not in SUPPORTED_LOGGER_WIFI_CLEANUP_MODES:
            choices = ", ".join(SUPPORTED_LOGGER_WIFI_CLEANUP_MODES)
            raise ValueError(f"cleanup mode must be one of: {choices}")
        if mode == LOGGER_WIFI_CLEANUP_NONE:
            raise ValueError("cleanup mode 'none' does not call the logger cleanup endpoint")

        obj = self._request_json(
            "POST",
            "/api/v1/session/delete",
            payload={"session_id": session_id, "mode": mode},
        )
        self._require_schema(obj, "bodaqs.logger.session_delete")
        return obj

    def move_session_to_uploaded(self, *, session_id: str) -> dict[str, Any]:
        return self.cleanup_session(session_id=session_id, mode=LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED)

    def delete_session(self, *, session_id: str) -> dict[str, Any]:
        return self.cleanup_session(session_id=session_id, mode=LOGGER_WIFI_CLEANUP_DELETE)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        data: Optional[bytes] = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(self._url(path), data=data, headers=headers, method=method.upper())
        with self._open(request, timeout_s=float(self.request_timeout_s)) as response:
            raw = response.read()
        return self._parse_json(raw, endpoint=path)

    def _open(self, request: Request, *, timeout_s: float) -> Any:
        try:
            return urlopen(request, timeout=timeout_s)
        except HTTPError as exc:
            body = self._read_error_body(exc)
            raise self._error_from_http_response(exc.code, body) from None
        except (URLError, socket.timeout, TimeoutError, http.client.HTTPException) as exc:
            raise LoggerWifiApiError(f"Could not reach logger: {exc}", error="connection_failed") from exc

    def _url(self, path: str, query: Optional[Mapping[str, Any]] = None) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = self.base_url + normalized_path
        if query:
            url += "?" + urlencode(query)
        return url

    def _parse_json(self, raw: bytes, *, endpoint: str) -> dict[str, Any]:
        text = raw.decode("utf-8", errors="replace")
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LoggerWifiApiError(
                f"{endpoint} returned invalid JSON: {exc}",
                error="invalid_json",
                response_body=text,
            ) from None
        if not isinstance(obj, dict):
            raise LoggerWifiApiError(
                f"{endpoint} returned JSON {type(obj).__name__}, expected object",
                error="invalid_json_shape",
                response_body=text,
            )
        api_version = obj.get("api_version")
        try:
            version_number = None if api_version is None else int(api_version)
        except (TypeError, ValueError):
            raise LoggerWifiApiError(f"{endpoint} returned invalid api_version: {api_version!r}") from None
        if version_number is not None and version_number != 1:
            raise LoggerWifiApiError(f"{endpoint} returned unsupported api_version: {api_version!r}")
        return obj

    def _require_schema(self, obj: Mapping[str, Any], expected_schema: str) -> None:
        schema = str(obj.get("schema") or "")
        if schema != expected_schema:
            raise LoggerWifiApiError(f"Unexpected logger response schema: {schema!r} (expected {expected_schema!r})")

    def _read_error_body(self, exc: HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _error_from_http_response(self, status_code: int, body: str) -> LoggerWifiApiError:
        try:
            obj = json.loads(body) if body else {}
        except json.JSONDecodeError:
            obj = {}

        if isinstance(obj, Mapping):
            error = str(obj.get("error") or "").strip() or None
            message = str(obj.get("message") or "").strip() or f"Logger returned HTTP {status_code}"
        else:
            error = None
            message = f"Logger returned HTTP {status_code}"
        return LoggerWifiApiError(message, status_code=status_code, error=error, response_body=body)

    def _content_length(self, response: Any) -> Optional[int]:
        value = response.headers.get("Content-Length")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _validate_zip(self, path: Path) -> None:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                bad_member = zf.testzip()
        except zipfile.BadZipFile as exc:
            raise LoggerWifiApiError(f"Downloaded archive is not a valid ZIP file: {exc}", error="invalid_archive")
        if bad_member:
            raise LoggerWifiApiError(
                f"Downloaded archive failed ZIP validation at member: {bad_member}",
                error="invalid_archive",
            )
