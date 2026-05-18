from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlparse


SOURCE_TYPE_FILESYSTEM_ARCHIVE = "filesystem_archive"
SOURCE_TYPE_LOGGER_WIFI = "logger_wifi"
SUPPORTED_IMPORT_SOURCE_TYPES = (
    SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    SOURCE_TYPE_LOGGER_WIFI,
)

LOGGER_WIFI_CLEANUP_NONE = "none"
LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED = "move_to_uploaded"
LOGGER_WIFI_CLEANUP_DELETE = "delete"
SUPPORTED_LOGGER_WIFI_CLEANUP_MODES = (
    LOGGER_WIFI_CLEANUP_NONE,
    LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED,
    LOGGER_WIFI_CLEANUP_DELETE,
)


def _optional_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def _safe_positive_float(value: Any, *, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric") from None
    if number <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return number


def normalize_import_source_type(value: Any) -> str:
    source_type = (_optional_text(value) or SOURCE_TYPE_FILESYSTEM_ARCHIVE).lower()
    if source_type not in SUPPORTED_IMPORT_SOURCE_TYPES:
        choices = ", ".join(SUPPORTED_IMPORT_SOURCE_TYPES)
        raise ValueError(f"Unsupported import source type {source_type!r}; expected one of: {choices}")
    return source_type


def normalize_logger_wifi_base_url(value: Any) -> Optional[str]:
    text = _optional_text(value)
    if text is None:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("logger_wifi.base_url must be an absolute http(s) URL when provided")
    return text.rstrip("/")


@dataclass(frozen=True)
class LoggerWifiSourceConfig:
    logger_id: str
    base_url: Optional[str] = None
    request_timeout_s: float = 5.0
    download_timeout_s: float = 60.0
    require_upload_mode: bool = True
    cleanup_mode: str = LOGGER_WIFI_CLEANUP_NONE

    def __post_init__(self) -> None:
        if not self.logger_id.strip():
            raise ValueError("logger_wifi.logger_id must be a non-empty string")
        if self.base_url is not None:
            normalize_logger_wifi_base_url(self.base_url)
        if float(self.request_timeout_s) <= 0:
            raise ValueError("logger_wifi.request_timeout_s must be > 0")
        if float(self.download_timeout_s) <= 0:
            raise ValueError("logger_wifi.download_timeout_s must be > 0")
        if self.cleanup_mode not in SUPPORTED_LOGGER_WIFI_CLEANUP_MODES:
            choices = ", ".join(SUPPORTED_LOGGER_WIFI_CLEANUP_MODES)
            raise ValueError(f"logger_wifi.cleanup_mode must be one of: {choices}")


def parse_logger_wifi_source_config(value: Mapping[str, Any]) -> LoggerWifiSourceConfig:
    if not isinstance(value, Mapping):
        raise ValueError("logger_wifi config must be a JSON object")

    logger_id = _optional_text(value.get("logger_id"))
    if logger_id is None:
        raise ValueError("logger_wifi config missing non-empty 'logger_id'")

    cleanup_mode = (_optional_text(value.get("cleanup_mode")) or LOGGER_WIFI_CLEANUP_NONE).lower()
    if cleanup_mode not in SUPPORTED_LOGGER_WIFI_CLEANUP_MODES:
        choices = ", ".join(SUPPORTED_LOGGER_WIFI_CLEANUP_MODES)
        raise ValueError(f"logger_wifi.cleanup_mode must be one of: {choices}")

    return LoggerWifiSourceConfig(
        logger_id=logger_id,
        base_url=normalize_logger_wifi_base_url(value.get("base_url")),
        request_timeout_s=_safe_positive_float(
            value.get("request_timeout_s", 5.0),
            field_name="logger_wifi.request_timeout_s",
        ),
        download_timeout_s=_safe_positive_float(
            value.get("download_timeout_s", 60.0),
            field_name="logger_wifi.download_timeout_s",
        ),
        require_upload_mode=bool(value.get("require_upload_mode", True)),
        cleanup_mode=cleanup_mode,
    )


def logger_wifi_source_config_to_jsonable(config: LoggerWifiSourceConfig) -> dict[str, Any]:
    return {
        "logger_id": config.logger_id,
        "base_url": config.base_url,
        "request_timeout_s": float(config.request_timeout_s),
        "download_timeout_s": float(config.download_timeout_s),
        "require_upload_mode": bool(config.require_upload_mode),
        "cleanup_mode": config.cleanup_mode,
    }

