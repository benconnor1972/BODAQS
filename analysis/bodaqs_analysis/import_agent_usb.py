"""Mounted logger discovery, local pairing, and acquisition into existing sources."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import TYPE_CHECKING, Iterable

from .import_agent_sources import SOURCE_TYPE_FILESYSTEM_ARCHIVE

if TYPE_CHECKING:
    from .import_agent import ImportAgentSupervisor, ImportSourceConfig

MARKER_FILENAME = ".bodaqs-logger.json"
_DEVICE_ID = re.compile(r"esp32s3-[0-9a-f]{12}\Z")


@dataclass(frozen=True)
class UsbLogger:
    device_id: str
    logger_id: str
    display_name: str
    volume_root: Path
    recordings_root: Path


def mounted_volume_roots() -> list[Path]:
    """Enumerate mounted roots only; never mount, format, or modify devices."""
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetLogicalDrives.restype = ctypes.c_ulong
        kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        mask = kernel.GetLogicalDrives()
        return [Path(f"{chr(65 + index)}:/") for index in range(26)
                if mask & (1 << index) and kernel.GetDriveTypeW(f"{chr(65 + index)}:\\") in (2, 3)]
    if sys.platform == "darwin":
        return list(Path("/Volumes").iterdir())
    roots = set()
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 6:
            path = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])
            roots.add(Path(path))
    return sorted(roots)


def enclosing_volume_root(folder: Path, *, roots: Iterable[Path] | None = None) -> Path:
    """Find the closest mounted boundary, including nested mount points."""
    selected = folder.expanduser().resolve()
    candidates = [Path(root).resolve() for root in (mounted_volume_roots() if roots is None else roots)]
    enclosing = [root for root in candidates if selected.is_relative_to(root)]
    if not enclosing:
        raise ValueError("Selected card folder is not on an available mounted volume")
    return max(enclosing, key=lambda root: len(root.parts))


def read_usb_logger(root: Path) -> UsbLogger | None:
    root = root.resolve()
    if not root.is_dir():
        return None
    marker = root / MARKER_FILENAME
    if marker.is_symlink():
        raise ValueError("Logger identity marker must not be a symbolic link")
    try:
        if not stat.S_ISREG(marker.lstat().st_mode):
            raise ValueError("Logger identity marker must be a regular file")
        with marker.open("rb") as source:
            data = source.read(4097)
    except FileNotFoundError:
        return None
    if len(data) > 4096:
        raise ValueError("Logger identity marker exceeds 4096 bytes")
    obj = json.loads(data)
    if (not isinstance(obj, dict) or obj.get("schema") != "bodaqs.logger.usb"
            or type(obj.get("version")) is not int or obj["version"] != 1):
        raise ValueError("Unsupported logger identity schema/version")
    device_id = obj.get("device_id")
    if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
        raise ValueError("Invalid immutable logger device_id")
    for key in ("logger_id", "display_name", "recordings_path"):
        value = obj.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 255 or any(ord(c) < 32 for c in value):
            raise ValueError(f"Invalid logger {key}")
    relative = obj["recordings_path"]
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
        raise ValueError("Recording directory must stay inside the card")
    directory = root
    for part in path.parts:
        directory /= part
        if directory.is_symlink():
            raise ValueError("Recording directory must not traverse symbolic links")
    directory = directory.resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        raise ValueError("Recording directory is unavailable or outside the card")
    return UsbLogger(device_id, obj["logger_id"], obj["display_name"], root, directory)


class UsbLoggerService:
    """A per-window scan session. Pairings persist locally, mount paths do not."""

    def __init__(self, pairings_path: str | Path):
        self.path = Path(pairings_path).expanduser().resolve()
        self._completed: dict[str, tuple] = {}

    def pairings(self) -> dict[str, str]:
        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if (not isinstance(obj, dict) or obj.get("schema") != "bodaqs.usb_pairings"
                or type(obj.get("version")) is not int or obj["version"] != 1):
            raise ValueError("Unsupported USB pairing settings")
        pairs = obj.get("sources")
        if not isinstance(pairs, dict) or any(not _DEVICE_ID.fullmatch(k) or not isinstance(v, str)
                                              for k, v in pairs.items()):
            raise ValueError("Invalid USB pairing settings")
        return pairs

    def pair(self, device: UsbLogger, source: ImportSourceConfig) -> None:
        if source.source_type != SOURCE_TYPE_FILESYSTEM_ARCHIVE:
            raise ValueError("Pair a USB logger with a local archive source")
        if self.path.is_relative_to(device.volume_root):
            raise ValueError("USB pairing settings must be stored on the computer")
        source.require_local_paths_outside(device.volume_root)
        pairs = self.pairings()
        pairs[device.device_id] = str(source.config_path.resolve())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({"schema": "bodaqs.usb_pairings", "version": 1,
                                         "sources": pairs}, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        self._completed.pop(device.device_id, None)

    def scan(self, *, roots: Iterable[Path] | None = None,
             supervisor: ImportAgentSupervisor | None = None) -> dict:
        issues, devices = [], []
        for root in mounted_volume_roots() if roots is None else roots:
            try:
                device = read_usb_logger(Path(root))
                if device is not None and device.volume_root not in {d.volume_root for d in devices}:
                    devices.append(device)
            except (OSError, ValueError, UnicodeError) as error:
                issues.append(f"{root}: {error}")
        counts: dict[str, int] = {}
        for device in devices:
            counts[device.device_id] = counts.get(device.device_id, 0) + 1
        for identity, count in counts.items():
            if count > 1:
                issues.append(f"Ambiguous USB logger identity {identity}; no source selected")
        devices = [device for device in devices if counts[device.device_id] == 1]
        self._completed = {key: value for key, value in self._completed.items()
                           if key in {d.device_id for d in devices}}
        pairs = self.pairings()
        acquisitions = {}
        if supervisor is not None:
            sources = {str(supervisor.get_state(key).runner.source.config_path.resolve()):
                       supervisor.get_state(key) for key in supervisor.source_ids()}
            for device in devices:
                state = sources.get(pairs.get(device.device_id, ""))
                if state is None or state.paused:
                    continue
                try:
                    files = tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                                         for p in device.recordings_root.iterdir()
                                         if not p.is_symlink() and p.is_file() and p.suffix.lower() in {".zip", ".bdq"}))
                    fingerprint = (str(device.volume_root), id(state.runner), files)
                    if self._completed.get(device.device_id) == fingerprint:
                        continue
                    result = state.runner.acquire_folder(device.recordings_root, volume_root=device.volume_root)
                    acquisitions[device.device_id] = result
                    if not result["errors"] and not result["deferred"]:
                        self._completed[device.device_id] = fingerprint
                except (OSError, ValueError, RuntimeError) as error:
                    issues.append(f"{device.display_name}: {error}")
        return {"devices": devices, "unpaired": [d for d in devices if d.device_id not in pairs],
                "acquisitions": acquisitions, "issues": issues}
