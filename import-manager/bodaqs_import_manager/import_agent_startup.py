from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


# ---------------------------------------------------------------------------
# Windows constants and functions (unchanged)
# ---------------------------------------------------------------------------

WINDOWS_STARTUP_VALUE_NAME = "BODAQS Import Manager"
LEGACY_WINDOWS_STARTUP_VALUE_NAMES = ("BODAQS Import Agent",)
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


def _delete_windows_startup_value(reg: Any, key: Any, value_name: str) -> None:
    try:
        reg.DeleteValue(key, value_name)
    except FileNotFoundError:
        pass


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
    legacy_value_names = (
        LEGACY_WINDOWS_STARTUP_VALUE_NAMES if value_name == WINDOWS_STARTUP_VALUE_NAME else ()
    )

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
            for legacy_value_name in legacy_value_names:
                _delete_windows_startup_value(reg, key, legacy_value_name)
        else:
            _delete_windows_startup_value(reg, key, value_name)
            for legacy_value_name in legacy_value_names:
                _delete_windows_startup_value(reg, key, legacy_value_name)
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


# ---------------------------------------------------------------------------
# macOS constants and functions
# ---------------------------------------------------------------------------

MACOS_LAUNCH_AGENT_LABEL = "org.bodaqs.importmanager"
MACOS_LAUNCH_AGENTS_DIRNAME = "LaunchAgents"


def macos_startup_supported(*, platform: Optional[str] = None) -> bool:
    resolved_platform = platform or sys.platform
    return resolved_platform == "darwin"


def macos_launch_agent_path(
    *,
    home: Optional[str | Path] = None,
    label: str = MACOS_LAUNCH_AGENT_LABEL,
) -> Path:
    home_path = Path.home() if home is None else Path(home).expanduser()
    return home_path / "Library" / MACOS_LAUNCH_AGENTS_DIRNAME / f"{label}.plist"


def build_macos_launch_agent_plist(
    argv: Sequence[str | Path],
    *,
    label: str = MACOS_LAUNCH_AGENT_LABEL,
) -> dict[str, Any]:
    """Build a LaunchAgent plist dictionary from an argv list.

    The first element of *argv* is expected to be the executable or ``open``
    command.  When the first element is an ``.app`` bundle path, the caller
    should pass ``["open", "-a", "<app_path>", "--args", ...]`` so that
    LaunchAgent invokes the system ``open`` command.
    """
    program_args = [
        str(Path(item).expanduser().resolve()) if isinstance(item, Path) else str(item)
        for item in argv
    ]
    return {
        "Label": label,
        "ProgramArguments": program_args,
        "RunAtLoad": True,
        "KeepAlive": False,
    }


def _macos_load_launch_agent(plist_path: Path) -> None:
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _macos_unload_launch_agent(label: str) -> None:
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{label}"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_macos_startup_registration(
    *,
    home: Optional[str | Path] = None,
    label: str = MACOS_LAUNCH_AGENT_LABEL,
    platform: Optional[str] = None,
) -> Optional[str]:
    if not macos_startup_supported(platform=platform):
        return None
    plist_path = macos_launch_agent_path(home=home, label=label)
    if not plist_path.is_file():
        return None
    try:
        with plist_path.open("rb") as handle:
            data = plistlib.load(handle)
    except Exception:
        return None
    args = data.get("ProgramArguments")
    if not isinstance(args, list) or not args:
        return None
    return " ".join(str(a) for a in args)


def sync_macos_startup_registration(
    *,
    enabled: bool,
    argv: Optional[Sequence[str | Path]] = None,
    home: Optional[str | Path] = None,
    label: str = MACOS_LAUNCH_AGENT_LABEL,
    platform: Optional[str] = None,
    load_agent: bool = True,
) -> Optional[str]:
    if not macos_startup_supported(platform=platform):
        return None
    plist_path = macos_launch_agent_path(home=home, label=label)

    if not enabled:
        if load_agent:
            _macos_unload_launch_agent(label)
        try:
            plist_path.unlink()
        except FileNotFoundError:
            pass
        return None

    if not argv:
        raise ValueError("A non-empty argv is required when enabling macOS startup registration")

    plist_data = build_macos_launch_agent_plist(argv, label=label)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as handle:
        plistlib.dump(plist_data, handle)

    if load_agent:
        _macos_unload_launch_agent(label)
        _macos_load_launch_agent(plist_path)

    return read_macos_startup_registration(home=home, label=label, platform=platform)


# ---------------------------------------------------------------------------
# Generic platform wrappers
# ---------------------------------------------------------------------------

STARTUP_APP_LABEL = "BODAQS Import Manager"


def startup_supported(*, platform: Optional[str] = None) -> bool:
    resolved_platform = platform or sys.platform
    return windows_startup_supported(platform=resolved_platform) or macos_startup_supported(
        platform=resolved_platform
    )


def build_startup_command(argv: Sequence[str | Path], *, platform: Optional[str] = None) -> str:
    resolved_platform = platform or sys.platform
    if windows_startup_supported(platform=resolved_platform):
        return build_windows_startup_command(argv)
    # On macOS and other Unix, return a shell-quoted command string.
    args = [
        str(Path(item).expanduser().resolve()) if isinstance(item, Path) else str(item)
        for item in argv
    ]
    return subprocess.list2cmdline(args)


def read_startup_registration(
    *,
    platform: Optional[str] = None,
    home: Optional[str | Path] = None,
) -> Optional[str]:
    resolved_platform = platform or sys.platform
    if windows_startup_supported(platform=resolved_platform):
        return read_windows_startup_registration(platform=resolved_platform)
    if macos_startup_supported(platform=resolved_platform):
        return read_macos_startup_registration(home=home, platform=resolved_platform)
    return None


def sync_startup_registration(
    *,
    enabled: bool,
    command: Optional[str] = None,
    argv: Optional[Sequence[str | Path]] = None,
    app_label: str = STARTUP_APP_LABEL,
    platform: Optional[str] = None,
    home: Optional[str | Path] = None,
    registry_module: Any = None,
    load_agent: bool = True,
) -> Optional[str]:
    resolved_platform = platform or sys.platform
    if windows_startup_supported(platform=resolved_platform):
        return sync_windows_startup_registration(
            enabled=enabled,
            command=command,
            registry_module=registry_module,
            platform=resolved_platform,
        )
    if macos_startup_supported(platform=resolved_platform):
        return sync_macos_startup_registration(
            enabled=enabled,
            argv=argv,
            home=home,
            platform=resolved_platform,
            load_agent=load_agent,
        )
    return None
