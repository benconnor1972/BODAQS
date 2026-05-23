from __future__ import annotations

import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence


WINDOWS_STARTUP_VALUE_NAME = "BODAQS Import Manager"
LEGACY_WINDOWS_STARTUP_VALUE_NAMES = ("BODAQS Import Agent",)
WINDOWS_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

MACOS_LAUNCH_AGENT_LABEL = "org.bodaqs.importmanager"
MACOS_LAUNCH_AGENTS_DIRNAME = "LaunchAgents"


@dataclass(frozen=True)
class StartupCommand:
    """Platform-neutral representation of a start-at-login launch command.

    Holds an already-resolved absolute argv. Windows consumers read
    ``windows_command_line`` (a single quoted string for the registry);
    macOS consumers read ``argv`` (a list for the LaunchAgent plist).
    """

    argv: tuple[str, ...]

    @property
    def windows_command_line(self) -> str:
        return subprocess.list2cmdline(list(self.argv))


def _resolve_argv(argv: Sequence[str | Path]) -> tuple[str, ...]:
    return tuple(
        str(Path(item).expanduser().resolve()) if isinstance(item, Path) else str(item)
        for item in argv
    )


# ---------------------------------------------------------------------------
# Windows registry implementation (preserved verbatim in behavior)
# ---------------------------------------------------------------------------


def windows_startup_supported(*, platform: Optional[str] = None) -> bool:
    resolved_platform = platform or sys.platform
    return resolved_platform.startswith("win")


def build_windows_startup_command(argv: Sequence[str | Path]) -> str:
    return subprocess.list2cmdline(list(_resolve_argv(argv)))


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
# macOS LaunchAgent implementation
# ---------------------------------------------------------------------------


def macos_startup_supported(*, platform: Optional[str] = None) -> bool:
    resolved_platform = platform or sys.platform
    return resolved_platform == "darwin"


def macos_launch_agent_plist_path(
    *,
    label: str = MACOS_LAUNCH_AGENT_LABEL,
    home: Optional[str | Path] = None,
) -> Path:
    home_path = Path.home() if home is None else Path(home).expanduser()
    return home_path / "Library" / MACOS_LAUNCH_AGENTS_DIRNAME / f"{label}.plist"


def build_macos_launch_agent_plist(
    *,
    label: str,
    program_arguments: Sequence[str],
    run_at_load: bool = True,
) -> str:
    """Render a LaunchAgent plist as XML text. Pure — easy to test."""
    if not str(label).strip():
        raise ValueError("A non-empty label is required for the LaunchAgent plist")
    if not program_arguments:
        raise ValueError("ProgramArguments must contain at least one entry")
    payload = {
        "Label": label,
        "ProgramArguments": [str(arg) for arg in program_arguments],
        "RunAtLoad": bool(run_at_load),
    }
    return plistlib.dumps(payload).decode("utf-8")


def read_macos_startup_registration(
    *,
    label: str = MACOS_LAUNCH_AGENT_LABEL,
    home: Optional[str | Path] = None,
    platform: Optional[str] = None,
) -> Optional[str]:
    if not macos_startup_supported(platform=platform):
        return None
    plist_path = macos_launch_agent_plist_path(label=label, home=home)
    if not plist_path.exists():
        return None
    try:
        payload = plistlib.loads(plist_path.read_bytes())
    except Exception:
        return None
    args = payload.get("ProgramArguments")
    if not isinstance(args, list) or not args:
        return None
    return subprocess.list2cmdline([str(arg) for arg in args])


def _macos_launchctl_user_target() -> Optional[str]:
    try:
        import os

        return f"gui/{os.getuid()}"
    except Exception:
        return None


def sync_macos_startup_registration(
    *,
    enabled: bool,
    program_arguments: Optional[Sequence[str]] = None,
    label: str = MACOS_LAUNCH_AGENT_LABEL,
    home: Optional[str | Path] = None,
    platform: Optional[str] = None,
    run_subprocess: Any = None,
    launchctl_target: Optional[str] = None,
) -> Optional[str]:
    """Write or remove the per-user LaunchAgent plist.

    Best-effort ``launchctl bootstrap``/``bootout`` is attempted but a
    failure there is *not* fatal — the next login picks up the plist regardless.

    ``run_subprocess`` is injectable for tests; defaults to ``subprocess.run``.
    ``home`` is injectable for tests; defaults to ``Path.home()``.
    """
    if not macos_startup_supported(platform=platform):
        return None

    plist_path = macos_launch_agent_plist_path(label=label, home=home)
    runner = run_subprocess if run_subprocess is not None else subprocess.run
    target = launchctl_target if launchctl_target is not None else _macos_launchctl_user_target()

    if enabled:
        if not program_arguments:
            raise ValueError(
                "program_arguments must be non-empty when enabling macOS startup registration"
            )
        plist_text = build_macos_launch_agent_plist(
            label=label,
            program_arguments=program_arguments,
        )
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist_text, encoding="utf-8")
        if target:
            try:
                runner(
                    ["launchctl", "bootstrap", target, str(plist_path)],
                    check=False,
                )
            except Exception:
                pass
    else:
        if target:
            try:
                runner(
                    ["launchctl", "bootout", f"{target}/{label}"],
                    check=False,
                )
            except Exception:
                pass
        try:
            plist_path.unlink()
        except FileNotFoundError:
            pass

    return read_macos_startup_registration(
        label=label,
        home=home,
        platform=platform,
    )


# ---------------------------------------------------------------------------
# Platform-neutral wrappers — these are what the UI calls.
# ---------------------------------------------------------------------------


def startup_supported(*, platform: Optional[str] = None) -> bool:
    return windows_startup_supported(platform=platform) or macos_startup_supported(platform=platform)


def build_startup_command(argv: Sequence[str | Path]) -> StartupCommand:
    return StartupCommand(argv=_resolve_argv(argv))


def sync_startup_registration(
    *,
    enabled: bool,
    command: Optional[StartupCommand] = None,
    app_label: str = MACOS_LAUNCH_AGENT_LABEL,
    platform: Optional[str] = None,
    registry_module: Any = None,
    home: Optional[str | Path] = None,
    run_subprocess: Any = None,
    launchctl_target: Optional[str] = None,
) -> Optional[str]:
    if windows_startup_supported(platform=platform):
        return sync_windows_startup_registration(
            enabled=enabled,
            command=command.windows_command_line if command is not None else None,
            registry_module=registry_module,
            platform=platform,
        )
    if macos_startup_supported(platform=platform):
        return sync_macos_startup_registration(
            enabled=enabled,
            program_arguments=list(command.argv) if command is not None else None,
            label=app_label,
            home=home,
            platform=platform,
            run_subprocess=run_subprocess,
            launchctl_target=launchctl_target,
        )
    return None


def read_startup_registration(
    *,
    app_label: str = MACOS_LAUNCH_AGENT_LABEL,
    platform: Optional[str] = None,
    registry_module: Any = None,
    home: Optional[str | Path] = None,
) -> Optional[str]:
    if windows_startup_supported(platform=platform):
        return read_windows_startup_registration(
            registry_module=registry_module,
            platform=platform,
        )
    if macos_startup_supported(platform=platform):
        return read_macos_startup_registration(
            label=app_label,
            home=home,
            platform=platform,
        )
    return None
