import binascii
import json
import socket
import struct
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _package_root in (_REPO_ROOT / "analysis", _REPO_ROOT / "import-manager"):
    _package_root_text = str(_package_root)
    if _package_root_text not in sys.path:
        sys.path.insert(0, _package_root_text)

import bodaqs_analysis.import_agent as import_agent_module
import bodaqs_analysis.import_agent_logger_wifi_discovery as discovery_module
from bodaqs_analysis.import_agent import run_sources_once
from bodaqs_analysis.import_agent_logger_wifi import LoggerWifiApiClient, LoggerWifiApiError
from bodaqs_analysis.import_agent_logger_wifi_discovery import (
    LoggerWifiDiscoveryError,
    LoggerWifiDiscoveryResult,
    LoggerWifiDiscoveryUnavailable,
    discover_logger_wifi_sources,
    discover_single_logger_wifi_source,
    logger_wifi_discovery_result_from_service_info,
    probe_logger_wifi_base_url,
)
from bodaqs_import_manager.import_agent_provisioning import (
    provision_import_agent_library,
    provision_import_agent_source,
)
from bodaqs_analysis.import_agent_sources import (
    LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED,
    SOURCE_TYPE_LOGGER_WIFI,
)


def _archive_bytes(stem: str = "2026-05-16_20-15-42") -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stem}.CSV", "time_s,value\n0.0,1\n")
        zf.writestr(f"{stem}.json", json.dumps({"session": {"session_id": stem}}))
    return buf.getvalue()


def _importable_archive_bytes(stem: str = "2026-05-16_20-15-42") -> bytes:
    sidecar = {
        "contract": {
            "name": "mtb_logger_timeseries",
            "version": "0.2.0",
            "sidecar_kind": "session",
        },
        "session": {
            "session_id": stem,
            "started_at_local": "2026-05-16T10:00:00+08:00",
            "timezone": "Australia/Perth",
        },
        "data_file": {
            "delimiter": ",",
            "header": True,
        },
        "streams": {
            "primary": {
                "type": "uniform",
                "time_column": "time_s",
                "time_encoding": "elapsed_s",
                "time_unit": "s",
                "sample_rate_hz": 33.3333333,
            }
        },
        "columns": {
            "time_s": {
                "class": "time",
                "dtype": "float64",
                "stream": "primary",
                "unit": "s",
            },
            "front_shock_dom_suspension [mm]": {
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "sensor": "front_shock",
                "end": "front",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            },
            "rear_shock_dom_suspension [mm]": {
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "sensor": "rear_shock",
                "end": "rear",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            },
            "mark": {
                "class": "event_flag",
                "dtype": "bool",
                "stream": "primary",
            },
        },
    }
    csv_text = "\n".join(
        [
            "time_s,front_shock_dom_suspension [mm],rear_shock_dom_suspension [mm],mark",
            "0.00,10.0,20.0,0",
            "0.03,11.0,21.0,1",
            "0.06,12.0,22.0,0",
        ]
    )

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stem}.CSV", csv_text)
        zf.writestr(f"{stem}.json", json.dumps(sidecar, indent=2))
    return buf.getvalue()


_BDQ_FILE_HEADER = struct.Struct("<8sHHIQII")
_BDQ_CHUNK_HEADER = struct.Struct("<4sHHIII")
_BDQ_DATA_HEADER = struct.Struct("<IIQHH")
_BDQ_FRAME = struct.Struct("<IffH")


def _bdq_crc32(payload: bytes) -> int:
    return binascii.crc32(payload) & 0xFFFFFFFF


def _bdq_chunk(chunk_type: int, sequence: int, payload: bytes) -> bytes:
    return _BDQ_CHUNK_HEADER.pack(b"BDQC", 1, chunk_type, sequence, len(payload), _bdq_crc32(payload)) + payload


def _bdq_json_chunk(chunk_type: int, sequence: int, payload: dict) -> bytes:
    return _bdq_chunk(chunk_type, sequence, json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _importable_bdq_bytes(stem: str = "260516_201542") -> bytes:
    metadata = {
        "format": "bdq.v1",
        "format_name": "BDQLOG v1",
        "device_id": "Prototype_E",
        "firmware_name": "BODAQS Firmware",
        "firmware_version": "0.3.0",
        "recording_id": stem,
        "path": f"/{stem}.bdq",
        "created_unix_us": 1_768_998_942_000_000,
        "sample_rate_hz": 33,
        "sample_period_us": 30_000,
        "timezone": "Australia/Perth",
        "started_at_utc": "2026-05-16T02:00:00Z",
        "started_at_local": "2026-05-16T10:00:00+08:00",
        "log_format": "bodaqs_compact_binary",
    }
    schema = {
        "schema_format": "bdq.channel_schema.v1",
        "frame_layout": "fixed_mixed_v1",
        "endianness": "little",
        "frame_size_bytes": _BDQ_FRAME.size,
        "timebase": {
            "type": "fixed_rate",
            "sample_rate_hz": 33,
            "sample_period_us": 30_000,
            "timestamp_per_sample": False,
        },
        "channels": [
            {
                "field": "sample_id",
                "quantity": "sample_index",
                "unit": "sample",
                "storage_type": "uint32",
                "byte_offset": 0,
                "source": "frame",
                "raw": False,
            },
            {
                "field": "front_suspension_disp",
                "quantity": "disp",
                "unit": "mm",
                "storage_type": "float32",
                "byte_offset": 4,
                "sensor": "front_shock",
                "source": "linear_calibrated",
                "raw": False,
            },
            {
                "field": "rear_suspension_disp",
                "quantity": "disp",
                "unit": "mm",
                "storage_type": "float32",
                "byte_offset": 8,
                "sensor": "rear_shock",
                "source": "linear_calibrated",
                "raw": False,
            },
            {
                "field": "flags",
                "quantity": "flags",
                "unit": "bitfield",
                "storage_type": "uint16",
                "byte_offset": 12,
                "source": "frame",
                "raw": False,
            },
        ],
        "sample_flags": {"mark": 1},
    }
    rows = [
        _BDQ_FRAME.pack(0, 10.0, 20.0, 0),
        _BDQ_FRAME.pack(1, 11.0, 21.0, 1),
        _BDQ_FRAME.pack(2, 12.0, 22.0, 0),
    ]
    data_payload = _BDQ_DATA_HEADER.pack(0, len(rows), 1_768_998_942_000_000, _BDQ_FRAME.size, 0) + b"".join(rows)
    header = _BDQ_FILE_HEADER.pack(b"BDQLOG\x00\x01", 1, 0, _BDQ_FILE_HEADER.size, metadata["created_unix_us"], 0, 0)
    return (
        header
        + _bdq_json_chunk(1, 0, metadata)
        + _bdq_json_chunk(2, 1, schema)
        + _bdq_chunk(3, 2, data_payload)
        + _bdq_json_chunk(5, 3, {"summary_format": "bdq.final_summary.v1", "samples_written": 3})
    )


def _provision_wifi_source(
    tmp_path: Path,
    base_url: str | None,
    *,
    cleanup_mode: str = "none",
    request_timeout_s: float = 5.0,
):
    library = provision_import_agent_library(tmp_path / "libraries", display_name="Test Library")
    logger_wifi = {
        "logger_id": "Prototype E",
        "request_timeout_s": request_timeout_s,
        "cleanup_mode": cleanup_mode,
    }
    if base_url is not None:
        logger_wifi["base_url"] = base_url
    source = provision_import_agent_source(
        tmp_path / "sources" / "Prototype E WiFi",
        artifacts_dir=library.artifacts_dir,
        library_id=library.library_id,
        display_name="Prototype E WiFi",
        source_type=SOURCE_TYPE_LOGGER_WIFI,
        logger_wifi=logger_wifi,
        logger_timezone="Australia/Perth",
        run_tz_label="AWST",
        settle_time_s=3600.0,
        include_events=False,
        include_metrics=False,
    )
    return source, library


def _unused_local_base_url() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()
    return f"http://{host}:{port}"


class _FakeLoggerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return None

    @property
    def state(self) -> dict:
        return self.server.state  # type: ignore[attr-defined]

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        self.state["requests"].append(("GET", parsed.path, parse_qs(parsed.query)))
        logger_id = self.state.get("logger_id", "Prototype E")

        if parsed.path == "/api/v1/device":
            if self.state.get("invalid_device_json"):
                body = b"{not-json"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json(
                200,
                {
                    "schema": "bodaqs.logger.device",
                    "api_version": 1,
                    "logger_id": logger_id,
                    "display_name": logger_id,
                    "hostname": "bodaqs-prototype-e",
                    "capabilities": ["upload_mode", "session_archive_zip", "session_data_bdq"],
                },
            )
            return

        if parsed.path == "/api/v1/status":
            self._send_json(
                200,
                {
                    "schema": "bodaqs.logger.status",
                    "api_version": 1,
                    "logger_id": logger_id,
                    "upload_mode": bool(self.state.get("upload_mode", True)),
                    "importable_session_count": 1,
                },
            )
            return

        if parsed.path == "/api/v1/sessions":
            if self.state.get("sessions_error"):
                self._send_json(
                    409,
                    {
                        "schema": "bodaqs.logger.error",
                        "api_version": 1,
                        "error": "upload_mode_required",
                        "message": "Upload mode is required for this endpoint.",
                    },
                )
                return
            self._send_json(
                200,
                    {
                        "schema": "bodaqs.logger.sessions",
                        "api_version": 1,
                        "logger_id": logger_id,
                        "sessions": self.state.get("sessions"),
                    },
                )
            return

        if parsed.path == "/api/v1/session/archive":
            query = parse_qs(parsed.query)
            self.state["archive_ids"].append(query.get("id", [""])[0])
            payload = self.state["archive_bytes"]
            if self.state.get("truncate_archive"):
                partial = payload[: max(1, len(payload) // 3)]
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(partial)
                self.close_connection = True
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/api/v1/session/data":
            query = parse_qs(parsed.query)
            self.state["data_ids"].append(query.get("id", [""])[0])
            payload = self.state["data_bytes"]
            if self.state.get("truncate_data"):
                partial = payload[: max(1, len(payload) // 3)]
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(partial)
                self.close_connection = True
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self._send_json(404, {"schema": "bodaqs.logger.error", "api_version": 1, "error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self._read_json_body()
        self.state["requests"].append(("POST", parsed.path, body))

        if parsed.path == "/api/v1/upload-mode/enter":
            self._send_json(
                200,
                {"schema": "bodaqs.logger.upload_mode", "api_version": 1, "logger_id": "Prototype E", "upload_mode": True},
            )
            return

        if parsed.path == "/api/v1/upload-mode/exit":
            self._send_json(
                200,
                {"schema": "bodaqs.logger.upload_mode", "api_version": 1, "logger_id": "Prototype E", "upload_mode": False},
            )
            return

        if parsed.path == "/api/v1/session/ack":
            self.state["acks"].append(body)
            self._send_json(
                200,
                {
                    "schema": "bodaqs.logger.session_ack",
                    "api_version": 1,
                    "logger_id": "Prototype E",
                    "session_id": body.get("session_id"),
                    "acknowledged": True,
                },
            )
            return

        if parsed.path == "/api/v1/session/delete":
            self.state["cleanups"].append(body)
            self._send_json(
                200,
                {
                    "schema": "bodaqs.logger.session_delete",
                    "api_version": 1,
                    "logger_id": "Prototype E",
                    "session_id": body.get("session_id"),
                    "mode": body.get("mode"),
                    "ok": True,
                },
            )
            return

        self._send_json(404, {"schema": "bodaqs.logger.error", "api_version": 1, "error": "not_found"})


class _FakeLoggerServer:
    def __init__(self, **state):
        default_sessions = [
            {
                "session_id": "Prototype E__2026-05-16_20-15-42",
                "session_stem": "2026-05-16_20-15-42",
                "data_format": "csv_zip",
                "archive_ready": True,
                "data_ready": True,
                "uploaded": False,
                "acknowledged": False,
            }
        ]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLoggerHandler)
        self.server.state = {
            "archive_bytes": _archive_bytes(),
            "data_bytes": _importable_bdq_bytes(),
            "archive_ids": [],
            "data_ids": [],
            "acks": [],
            "cleanups": [],
            "requests": [],
            "sessions": default_sessions,
            **state,
        }
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    @property
    def state(self) -> dict:
        return self.server.state

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


def test_logger_wifi_client_reads_status_sessions_and_posts_actions():
    with _FakeLoggerServer() as server:
        client = LoggerWifiApiClient(server.base_url)

        assert client.get_device()["logger_id"] == "Prototype E"
        assert client.get_status()["upload_mode"] is True
        sessions = client.list_sessions()
        enter = client.enter_upload_mode()
        exit_state = client.exit_upload_mode()
        ack = client.ack_session(
            session_id=sessions[0]["session_id"],
            library_id="default-library",
            run_id="run_001",
            imported_at="2026-05-18T12:00:00+08:00",
        )
        cleanup = client.cleanup_session(session_id=sessions[0]["session_id"], mode="move_to_uploaded")

    assert sessions[0]["session_id"] == "Prototype E__2026-05-16_20-15-42"
    assert enter["upload_mode"] is True
    assert exit_state["upload_mode"] is False
    assert ack["acknowledged"] is True
    assert cleanup["ok"] is True
    assert server.state["acks"][0]["run_id"] == "run_001"
    assert server.state["cleanups"][0]["mode"] == "move_to_uploaded"


def test_logger_wifi_client_downloads_archive_via_part_then_final(tmp_path):
    with _FakeLoggerServer() as server:
        client = LoggerWifiApiClient(server.base_url)
        target = tmp_path / "session.zip"

        result = client.download_archive_to_part("Prototype E__2026-05-16_20-15-42", target)

    assert result == target.resolve()
    assert target.exists()
    assert not Path(str(target.resolve()) + ".part").exists()
    assert server.state["archive_ids"] == ["Prototype E__2026-05-16_20-15-42"]
    with zipfile.ZipFile(target, "r") as zf:
        assert sorted(zf.namelist()) == ["2026-05-16_20-15-42.CSV", "2026-05-16_20-15-42.json"]


def test_logger_wifi_client_downloads_bdq_data_via_part_then_final(tmp_path):
    with _FakeLoggerServer() as server:
        client = LoggerWifiApiClient(server.base_url)
        target = tmp_path / "session.bdq"

        result = client.download_bdq_to_part("Prototype E__260516_201542", target)

    assert result == target.resolve()
    assert target.exists()
    assert not Path(str(target.resolve()) + ".part").exists()
    assert server.state["data_ids"] == ["Prototype E__260516_201542"]


def test_logger_wifi_client_failed_download_leaves_part_file(tmp_path):
    with _FakeLoggerServer(truncate_archive=True) as server:
        client = LoggerWifiApiClient(server.base_url)
        target = tmp_path / "session.zip"

        with pytest.raises(LoggerWifiApiError) as exc_info:
            client.download_archive_to_part("Prototype E__2026-05-16_20-15-42", target)

    assert "download" in str(exc_info.value).lower()
    assert not target.exists()
    assert Path(str(target.resolve()) + ".part").exists()


def test_logger_wifi_client_raises_api_error_details():
    with _FakeLoggerServer(sessions_error=True) as server:
        client = LoggerWifiApiClient(server.base_url)

        with pytest.raises(LoggerWifiApiError) as exc_info:
            client.list_sessions()

    assert exc_info.value.status_code == 409
    assert exc_info.value.error == "upload_mode_required"
    assert "Upload mode is required" in str(exc_info.value)


def test_logger_wifi_client_rejects_invalid_json():
    with _FakeLoggerServer(invalid_device_json=True) as server:
        client = LoggerWifiApiClient(server.base_url)

        with pytest.raises(LoggerWifiApiError) as exc_info:
            client.get_device()

    assert exc_info.value.error == "invalid_json"


def test_logger_wifi_client_does_not_call_cleanup_for_none_mode():
    with _FakeLoggerServer() as server:
        client = LoggerWifiApiClient(server.base_url)

        with pytest.raises(ValueError):
            client.cleanup_session(session_id="Prototype E__2026-05-16_20-15-42", mode="none")

    assert server.state["cleanups"] == []


class _FakeMdnsServiceInfo:
    name = "Prototype E._bodaqs-logger._tcp.local."
    server = "bodaqs-prototype-e.local."
    port = 80
    properties = {
        b"api": b"1",
        b"logger_id": b"Prototype E",
        b"upload_mode": b"true",
        b"hostname": b"bodaqs-prototype-e",
    }

    def parsed_addresses(self):
        return ["fe80::1234", "192.168.1.42"]


def test_logger_wifi_discovery_result_parses_mdns_service_info():
    result = logger_wifi_discovery_result_from_service_info(_FakeMdnsServiceInfo())

    assert result is not None
    assert result.logger_id == "Prototype E"
    assert result.base_url == "http://192.168.1.42"
    assert result.hostname == "bodaqs-prototype-e"
    assert result.api_version == 1
    assert result.upload_mode is True
    assert result.addresses == ("fe80::1234", "192.168.1.42")


def test_logger_wifi_direct_probe_reads_device_and_status():
    with _FakeLoggerServer(upload_mode=False) as server:
        result = probe_logger_wifi_base_url(
            server.base_url,
            logger_id="Prototype E",
            request_timeout_s=1.0,
        )

    assert result is not None
    assert result.base_url == server.base_url
    assert result.logger_id == "Prototype E"
    assert result.hostname == "bodaqs-prototype-e"
    assert result.upload_mode is False


def test_logger_wifi_direct_probe_rejects_logger_id_mismatch():
    with _FakeLoggerServer() as server:
        result = probe_logger_wifi_base_url(
            server.base_url,
            logger_id="Other Logger",
            request_timeout_s=1.0,
        )

    assert result is None


def test_logger_wifi_discovery_can_fall_back_to_default_ap_probe(monkeypatch):
    class EmptyServiceBrowser:
        def __init__(self, _zeroconf, _service_type, _listener):
            pass

        def cancel(self):
            pass

    class EmptyZeroconf:
        def close(self):
            pass

    def import_zeroconf_symbols():
        return EmptyServiceBrowser, EmptyZeroconf

    calls = []

    def probe(base_url, **kwargs):
        calls.append((base_url, kwargs))
        return LoggerWifiDiscoveryResult(
            service_name="default-ap",
            base_url=base_url,
            addresses=("192.168.4.1",),
            port=80,
            logger_id="Prototype E",
            upload_mode=True,
        )

    monkeypatch.setattr(discovery_module, "_import_zeroconf_symbols", import_zeroconf_symbols)
    monkeypatch.setattr(discovery_module, "probe_logger_wifi_base_url", probe)

    results = discover_logger_wifi_sources(
        logger_id="Prototype E",
        timeout_s=0.01,
        include_default_ap=True,
        default_ap_base_url="http://192.168.4.1",
        default_ap_timeout_s=0.25,
    )

    assert results == [
        LoggerWifiDiscoveryResult(
            service_name="default-ap",
            base_url="http://192.168.4.1",
            addresses=("192.168.4.1",),
            port=80,
            logger_id="Prototype E",
            upload_mode=True,
        )
    ]
    assert calls == [
        (
            "http://192.168.4.1",
            {
                "logger_id": "Prototype E",
                "request_timeout_s": 0.25,
                "service_name": "default-ap",
            },
        )
    ]


def test_logger_wifi_discovery_reports_unavailable_dependency(monkeypatch):
    def unavailable():
        raise LoggerWifiDiscoveryUnavailable("missing test zeroconf")

    monkeypatch.setattr(discovery_module, "_import_zeroconf_symbols", unavailable)

    with pytest.raises(LoggerWifiDiscoveryUnavailable):
        discover_logger_wifi_sources(timeout_s=0.1)


def test_logger_wifi_discovery_rejects_duplicate_logger_ids(monkeypatch):
    results = [
        LoggerWifiDiscoveryResult(
            service_name="one",
            base_url="http://192.168.1.42",
            addresses=("192.168.1.42",),
            port=80,
            logger_id="Prototype E",
        ),
        LoggerWifiDiscoveryResult(
            service_name="two",
            base_url="http://192.168.1.43",
            addresses=("192.168.1.43",),
            port=80,
            logger_id="Prototype E",
        ),
    ]

    monkeypatch.setattr(discovery_module, "discover_logger_wifi_sources", lambda **_kwargs: results)

    with pytest.raises(LoggerWifiDiscoveryError):
        discover_single_logger_wifi_source(logger_id="Prototype E", timeout_s=0.1)


def test_logger_wifi_source_acquires_imports_acknowledges_and_cleans_up(tmp_path):
    with _FakeLoggerServer(archive_bytes=_importable_archive_bytes()) as server:
        source, library = _provision_wifi_source(
            tmp_path,
            server.base_url,
            cleanup_mode=LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED,
        )

        report = run_sources_once([source.source_root])

    assert report["totals"]["seen"] == 1
    assert report["totals"]["imported"] == 1
    assert report["totals"]["failed"] == 0
    assert server.state["archive_ids"] == ["Prototype E__2026-05-16_20-15-42"]
    assert server.state["acks"][0]["session_id"] == "Prototype E__2026-05-16_20-15-42"
    assert server.state["acks"][0]["run_id"]
    assert server.state["cleanups"][0]["mode"] == LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED

    imported_record = report["sources"][0]["imported"][0]
    assert imported_record["remote_session_id"] == "Prototype E__2026-05-16_20-15-42"
    assert imported_record["remote_acknowledged"] is True
    assert imported_record["remote_cleanup_done"] is True
    assert len(list((source.source_root / "done").glob("*.zip"))) == 1
    assert (library.artifacts_dir / "runs" / imported_record["run_id"]).exists()

    state = json.loads((library.artifacts_dir / "library" / "import_agent_state_v1.json").read_text(encoding="utf-8"))
    remote_records = [
        record
        for key, record in state["records"].items()
        if key.startswith("logger_wifi:")
    ]
    assert remote_records[0]["status"] == "succeeded"
    assert remote_records[0]["remote_session_id"] == "Prototype E__2026-05-16_20-15-42"
    assert remote_records[0]["acknowledged"] is True


def test_logger_wifi_source_acquires_imports_bdq_session_data(tmp_path):
    sessions = [
        {
            "session_id": "Prototype E__260516_201542",
            "session_stem": "260516_201542",
            "data_format": "bdq",
            "data_path": "/260516_201542.bdq",
            "archive_ready": False,
            "data_ready": True,
            "data_size": len(_importable_bdq_bytes()),
            "uploaded": False,
            "acknowledged": False,
        }
    ]
    with _FakeLoggerServer(sessions=sessions, data_bytes=_importable_bdq_bytes()) as server:
        source, library = _provision_wifi_source(tmp_path, server.base_url)

        report = run_sources_once([source.source_root])

    assert report["totals"]["seen"] == 1
    assert report["totals"]["imported"] == 1
    assert report["totals"]["failed"] == 0
    assert server.state["archive_ids"] == []
    assert server.state["data_ids"] == ["Prototype E__260516_201542"]
    assert server.state["acks"][0]["session_id"] == "Prototype E__260516_201542"
    assert len(list((source.source_root / "done").glob("*.bdq"))) == 1

    imported_record = report["sources"][0]["imported"][0]
    session_manifest = (
        library.artifacts_dir
        / "runs"
        / imported_record["run_id"]
        / "sessions"
        / imported_record["session_id"]
        / "manifest.json"
    )
    manifest = json.loads(session_manifest.read_text(encoding="utf-8"))

    assert imported_record["input_kind"] == "bdq"
    assert imported_record["remote_data_format"] == "bdq"
    assert imported_record["remote_session_id"] == "Prototype E__260516_201542"
    assert manifest["source"]["path"] == "source/input.bdq"
    assert manifest["source"]["input_kind"] == "bdq"
    assert manifest["source"]["original_bdq_filename"].endswith(".bdq")
    assert (session_manifest.parent / "source" / "input.bdq").exists()

    state = json.loads((library.artifacts_dir / "library" / "import_agent_state_v1.json").read_text(encoding="utf-8"))
    remote_records = [
        record
        for key, record in state["records"].items()
        if key.startswith("logger_wifi:")
    ]
    assert remote_records[0]["status"] == "succeeded"
    assert remote_records[0]["data_format"] == "bdq"
    assert remote_records[0]["acknowledged"] is True


def test_logger_wifi_source_skips_duplicate_remote_session_after_success(tmp_path):
    with _FakeLoggerServer(archive_bytes=_importable_archive_bytes()) as server:
        source, _library = _provision_wifi_source(tmp_path, server.base_url)

        first_report = run_sources_once([source.source_root])
        second_report = run_sources_once([source.source_root])

    assert first_report["totals"]["imported"] == 1
    assert second_report["totals"]["imported"] == 0
    assert second_report["sources"][0]["remote"]["skipped"][0]["reason"] == "already_imported"
    assert server.state["archive_ids"] == ["Prototype E__2026-05-16_20-15-42"]
    assert len(server.state["acks"]) == 1


def test_logger_wifi_source_does_not_reack_remote_acknowledged_session(tmp_path):
    sessions = [
        {
            "session_id": "Prototype E__2026-05-16_20-15-42",
            "session_stem": "2026-05-16_20-15-42",
            "archive_ready": True,
            "uploaded": True,
            "acknowledged": True,
        }
    ]
    with _FakeLoggerServer(archive_bytes=_importable_archive_bytes(), sessions=sessions) as server:
        source, _library = _provision_wifi_source(tmp_path, server.base_url)

        report = run_sources_once([source.source_root])

    assert report["totals"]["imported"] == 1
    assert server.state["archive_ids"] == ["Prototype E__2026-05-16_20-15-42"]
    assert server.state["acks"] == []
    imported_record = report["sources"][0]["imported"][0]
    assert imported_record["remote_acknowledged"] is True
    assert imported_record["remote_already_acknowledged"] is True


def test_logger_wifi_source_discovers_logger_when_base_url_missing(tmp_path, monkeypatch):
    with _FakeLoggerServer(archive_bytes=_importable_archive_bytes()) as server:
        source, _library = _provision_wifi_source(tmp_path, None)

        monkeypatch.setattr(
            import_agent_module,
            "discover_single_logger_wifi_source",
            lambda **_kwargs: LoggerWifiDiscoveryResult(
                service_name="Prototype E._bodaqs-logger._tcp.local.",
                base_url=server.base_url,
                addresses=("127.0.0.1",),
                port=int(server.base_url.rsplit(":", 1)[1]),
                logger_id="Prototype E",
                upload_mode=True,
            ),
        )

        report = run_sources_once([source.source_root])

    assert report["totals"]["imported"] == 1
    assert report["sources"][0]["remote"]["discovery"]["state"] == "found"
    assert report["sources"][0]["remote"]["base_url"] is None
    assert report["sources"][0]["imported"][0]["remote_base_url"] == server.base_url
    assert server.state["acks"][0]["session_id"] == "Prototype E__2026-05-16_20-15-42"


def test_logger_wifi_source_falls_back_to_discovered_address_after_stale_base_url(tmp_path, monkeypatch):
    with _FakeLoggerServer(archive_bytes=_importable_archive_bytes()) as server:
        source, _library = _provision_wifi_source(
            tmp_path,
            _unused_local_base_url(),
            request_timeout_s=0.1,
        )

        monkeypatch.setattr(
            import_agent_module,
            "discover_single_logger_wifi_source",
            lambda **_kwargs: LoggerWifiDiscoveryResult(
                service_name="Prototype E._bodaqs-logger._tcp.local.",
                base_url=server.base_url,
                addresses=("127.0.0.1",),
                port=int(server.base_url.rsplit(":", 1)[1]),
                logger_id="Prototype E",
                upload_mode=True,
            ),
        )

        report = run_sources_once([source.source_root])

    assert report["totals"]["imported"] == 1
    assert report["sources"][0]["remote"]["discovery"]["state"] == "found"
    assert "configured_address_error" in report["sources"][0]["remote"]
    assert report["sources"][0]["imported"][0]["remote_base_url"] == server.base_url


def test_logger_wifi_source_waits_for_upload_mode_without_failure(tmp_path):
    with _FakeLoggerServer(upload_mode=False, archive_bytes=_importable_archive_bytes()) as server:
        source, _library = _provision_wifi_source(tmp_path, server.base_url)

        report = run_sources_once([source.source_root])

    assert report["totals"]["seen"] == 0
    assert report["totals"]["imported"] == 0
    assert report["totals"]["failed"] == 0
    assert report["sources"][0]["remote"]["status"]["state"] == "waiting_upload_mode"
    assert server.state["archive_ids"] == []
    assert server.state["acks"] == []


def test_logger_wifi_offline_source_reports_remote_error_without_import_failure(tmp_path):
    source, _library = _provision_wifi_source(
        tmp_path,
        _unused_local_base_url(),
        request_timeout_s=0.1,
    )

    report = run_sources_once([source.source_root])

    assert report["totals"]["seen"] == 0
    assert report["totals"]["imported"] == 0
    assert report["totals"]["failed"] == 0
    assert report["sources"][0]["remote"]["status"]["state"] == "error"
    assert report["sources"][0]["remote"]["failed"]
