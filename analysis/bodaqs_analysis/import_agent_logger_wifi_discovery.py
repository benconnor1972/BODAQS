from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from .import_agent_logger_wifi import LoggerWifiApiClient


BODAQS_LOGGER_SERVICE_TYPE = "_bodaqs-logger._tcp.local."
DEFAULT_LOGGER_WIFI_AP_BASE_URL = "http://192.168.4.1"


class LoggerWifiDiscoveryUnavailable(RuntimeError):
    pass


class LoggerWifiDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoggerWifiDiscoveryResult:
    service_name: str
    base_url: str
    addresses: tuple[str, ...]
    port: int
    logger_id: Optional[str] = None
    display_name: Optional[str] = None
    hostname: Optional[str] = None
    api_version: Optional[int] = None
    upload_mode: Optional[bool] = None
    properties: Mapping[str, str] | None = None


def _optional_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def _decode_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _decode_properties(properties: Mapping[Any, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (properties or {}).items():
        out[_decode_text(key).strip()] = _decode_text(value).strip()
    return out


def _bool_property(value: Any) -> Optional[bool]:
    text = _optional_text(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None


def _int_property(value: Any) -> Optional[int]:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _addresses_from_service_info(info: Any) -> tuple[str, ...]:
    parsed_addresses = getattr(info, "parsed_addresses", None)
    if callable(parsed_addresses):
        addresses = tuple(str(item) for item in parsed_addresses() if _optional_text(item))
        if addresses:
            return addresses

    out: list[str] = []
    for raw in getattr(info, "addresses", []) or []:
        try:
            if len(raw) == 4:
                out.append(socket.inet_ntop(socket.AF_INET, raw))
            elif len(raw) == 16:
                out.append(socket.inet_ntop(socket.AF_INET6, raw))
        except (OSError, TypeError, ValueError):
            continue
    return tuple(out)


def _preferred_address(addresses: tuple[str, ...]) -> Optional[str]:
    for address in addresses:
        try:
            if ipaddress.ip_address(address).version == 4:
                return address
        except ValueError:
            continue
    return addresses[0] if addresses else None


def _base_url_for_address(address: str, port: int) -> str:
    parsed = ipaddress.ip_address(address)
    host = f"[{address}]" if parsed.version == 6 else address
    port_part = "" if int(port) == 80 else f":{int(port)}"
    return f"http://{host}{port_part}"


def _host_port_from_base_url(base_url: str) -> tuple[str, int]:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        port = int(parsed.port)
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80
    return host, port


def probe_logger_wifi_base_url(
    base_url: str,
    *,
    logger_id: Optional[str] = None,
    request_timeout_s: float = 1.0,
    service_name: str = "direct",
) -> Optional[LoggerWifiDiscoveryResult]:
    if request_timeout_s <= 0:
        raise ValueError("request_timeout_s must be > 0")

    wanted_logger_id = _optional_text(logger_id)
    try:
        client = LoggerWifiApiClient(
            base_url,
            request_timeout_s=float(request_timeout_s),
            download_timeout_s=max(float(request_timeout_s), 1.0),
        )
        device = client.get_device()
        found_logger_id = _optional_text(device.get("logger_id"))
        if wanted_logger_id is not None and found_logger_id != wanted_logger_id:
            return None

        try:
            status = client.get_status()
        except Exception:
            status = {}

        host, port = _host_port_from_base_url(client.base_url)
        upload_mode = (
            _bool_property(status.get("upload_mode"))
            if isinstance(status, Mapping)
            else None
        )
        return LoggerWifiDiscoveryResult(
            service_name=service_name,
            base_url=client.base_url,
            addresses=(host,) if host else (),
            port=port,
            logger_id=found_logger_id,
            display_name=_optional_text(device.get("display_name")) or found_logger_id,
            hostname=_optional_text(device.get("hostname")),
            api_version=_int_property(device.get("api_version")),
            upload_mode=upload_mode,
            properties={"probe": "direct"},
        )
    except Exception:
        return None


def logger_wifi_discovery_result_from_service_info(
    info: Any,
    *,
    service_name: Optional[str] = None,
) -> Optional[LoggerWifiDiscoveryResult]:
    addresses = _addresses_from_service_info(info)
    address = _preferred_address(addresses)
    if address is None:
        return None

    port = int(getattr(info, "port", 80) or 80)
    properties = _decode_properties(getattr(info, "properties", None))
    server = _optional_text(getattr(info, "server", None))

    return LoggerWifiDiscoveryResult(
        service_name=service_name or _optional_text(getattr(info, "name", None)) or "",
        base_url=_base_url_for_address(address, port),
        addresses=addresses,
        port=port,
        logger_id=_optional_text(properties.get("logger_id")),
        display_name=_optional_text(properties.get("display_name")),
        hostname=_optional_text(properties.get("hostname")) or server,
        api_version=_int_property(properties.get("api")),
        upload_mode=_bool_property(properties.get("upload_mode")),
        properties=properties,
    )


def _import_zeroconf_symbols() -> tuple[Any, Any]:
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError as exc:
        raise LoggerWifiDiscoveryUnavailable(
            "mDNS discovery requires the 'zeroconf' Python package."
        ) from exc
    return ServiceBrowser, Zeroconf


class _BodaqsLoggerServiceListener:
    def __init__(self) -> None:
        self.results_by_name: dict[str, LoggerWifiDiscoveryResult] = {}

    def add_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self._remember_service(zeroconf, service_type, name)

    def update_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self._remember_service(zeroconf, service_type, name)

    def remove_service(self, _zeroconf: Any, _service_type: str, name: str) -> None:
        self.results_by_name.pop(name, None)

    def _remember_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        info = zeroconf.get_service_info(service_type, name, timeout=1000)
        if info is None:
            return
        result = logger_wifi_discovery_result_from_service_info(info, service_name=name)
        if result is not None:
            self.results_by_name[name] = result


def discover_logger_wifi_sources(
    *,
    logger_id: Optional[str] = None,
    timeout_s: float = 3.0,
    service_type: str = BODAQS_LOGGER_SERVICE_TYPE,
    include_default_ap: bool = False,
    default_ap_base_url: str = DEFAULT_LOGGER_WIFI_AP_BASE_URL,
    default_ap_timeout_s: float = 1.0,
) -> list[LoggerWifiDiscoveryResult]:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")

    wanted_logger_id = _optional_text(logger_id)
    mdns_unavailable: Optional[LoggerWifiDiscoveryUnavailable] = None
    results: list[LoggerWifiDiscoveryResult] = []
    try:
        ServiceBrowser, Zeroconf = _import_zeroconf_symbols()
        zeroconf = Zeroconf()
        listener = _BodaqsLoggerServiceListener()
        browser = None
        try:
            browser = ServiceBrowser(zeroconf, service_type, listener)
            time.sleep(float(timeout_s))
        finally:
            if browser is not None and hasattr(browser, "cancel"):
                browser.cancel()
            zeroconf.close()

        results = sorted(listener.results_by_name.values(), key=lambda item: (item.logger_id or "", item.base_url))
    except LoggerWifiDiscoveryUnavailable as exc:
        if not include_default_ap:
            raise
        mdns_unavailable = exc

    if wanted_logger_id is not None:
        results = [item for item in results if item.logger_id == wanted_logger_id]

    if include_default_ap and not results:
        ap_result = probe_logger_wifi_base_url(
            default_ap_base_url,
            logger_id=wanted_logger_id,
            request_timeout_s=float(default_ap_timeout_s),
            service_name="default-ap",
        )
        if ap_result is not None:
            results = [ap_result]

    if mdns_unavailable is not None and not results:
        raise mdns_unavailable
    return results


def discover_single_logger_wifi_source(
    *,
    logger_id: str,
    timeout_s: float = 3.0,
    service_type: str = BODAQS_LOGGER_SERVICE_TYPE,
    include_default_ap: bool = False,
    default_ap_base_url: str = DEFAULT_LOGGER_WIFI_AP_BASE_URL,
    default_ap_timeout_s: float = 1.0,
) -> Optional[LoggerWifiDiscoveryResult]:
    wanted_logger_id = _optional_text(logger_id)
    if wanted_logger_id is None:
        raise ValueError("logger_id must be non-empty")

    matches = discover_logger_wifi_sources(
        logger_id=wanted_logger_id,
        timeout_s=timeout_s,
        service_type=service_type,
        include_default_ap=include_default_ap,
        default_ap_base_url=default_ap_base_url,
        default_ap_timeout_s=default_ap_timeout_s,
    )
    if len(matches) > 1:
        raise LoggerWifiDiscoveryError(
            f"Discovered {len(matches)} Wi-Fi loggers with logger_id={wanted_logger_id!r}; "
            "logger IDs must be unique before automatic import can continue."
        )
    return matches[0] if matches else None
