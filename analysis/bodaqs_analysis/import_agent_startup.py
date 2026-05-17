from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


WINDOWS_STARTUP_VALUE_NAME = "BODAQS Import Agent"
WINDOWS_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def windows_startup_supported(*, platform: Optional[str] = None) -> bool:
    resolved_platform = platform or sys.platform
    return resolved_platform.startswith("win")


def build_windows_startup_command(argv: Sequence[str | Path]) -> str:
    args = [str(Path(item).expanduser().resolve()) if isinstance(item, Path) else str(item) for item in argv]
    return subprocess.list2cmdline(args)


def _load_winreg(registry_module: Any = None) -> Any:
    if registry_module is not None:
        return registry_module
    if not windows_startup_supported():
        return None
    import winreg  # type: ignore

    return winreg


def read_windows_startup_registration(
    *,
    value_name: str = WINDOWS_STARTUP_VALUE_NAME,
    registry_module: Any = None,
    platform: Optional[str] = None,
) -> Optional[str]:
    if not windows_startup_supported(platform=platform):
        return None
    reg = _load_winreg(registry_module)
    if reg is None:
        return None

    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY_PATH, 0, getattr(reg, "KEY_READ", 0))
    except FileNotFoundError:
        return None

    try:
        value, _kind = reg.QueryValueEx(key, value_name)
    except FileNotFoundError:
        return None
    finally:
        try:
            key.Close()
        except Exception:
            pass

    return str(value)


def sync_windows_startup_registration(
    *,
    enabled: bool,
    command: Optional[str] = None,
    value_name: str = WINDOWS_STARTUP_VALUE_NAME,
    registry_module: Any = None,
    platform: Optional[str] = None,
) -> Optional[str]:
    if not windows_startup_supported(platform=platform):
        return None
    reg = _load_winreg(registry_module)
    if reg is None:
        return None

    key = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER,
        WINDOWS_RUN_KEY_PATH,
        0,
        getattr(reg, "KEY_SET_VALUE", 0),
    )
    try:
        if enabled:
            if not str(command or "").strip():
                raise ValueError("A non-empty command is required when enabling Windows startup registration")
            reg.SetValueEx(key, value_name, 0, reg.REG_SZ, str(command))
        else:
            try:
                reg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass
    finally:
        try:
            key.Close()
        except Exception:
            pass

    return read_windows_startup_registration(
        value_name=value_name,
        registry_module=reg,
        platform=platform,
    )
