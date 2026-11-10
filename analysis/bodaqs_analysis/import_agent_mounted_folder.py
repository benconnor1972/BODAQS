"""Read-only acquisition from a mounted card into an existing local inbox."""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any


def acquire_mounted_folder(
    folder: Path,
    inbox: Path,
    *,
    settle_time_s: float,
) -> dict[str, Any]:
    """Copy settled ZIP/BDQ inputs atomically; never write to the selected card.

    A changed or disconnected source leaves no importable partial file. Completed
    copies use content-qualified names so separate cards cannot overwrite an
    earlier acquisition with the same filename. Import deduplication remains the
    existing runner's responsibility.
    """
    folder, inbox = folder.resolve(), inbox.resolve()
    if not math.isfinite(settle_time_s) or settle_time_s < 0:
        raise ValueError("settle_time_s must be finite and non-negative")
    if inbox == folder or inbox.is_relative_to(folder) or folder.is_relative_to(inbox):
        raise ValueError("Selected folder and local inbox must be separate")
    if not folder.is_dir():
        raise ValueError("Selected recording folder is unavailable")
    inbox.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"copied": [], "already_copied": [], "deferred": [], "errors": []}
    # Recordings are flat in the selected folder; never follow card symlinks.
    paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".zip", ".bdq"})
    for path in paths:
        temporary: Path | None = None
        try:
            if path.is_symlink() or not path.is_file():
                continue
            before = path.stat()
            if time.time() - before.st_mtime < settle_time_s:
                result["deferred"].append(path.name)
                continue
            digest = hashlib.sha256()
            with path.open("rb") as source, tempfile.NamedTemporaryFile(
                dir=inbox, prefix=".usb-copy-", suffix=".part", delete=False
            ) as output:
                temporary = Path(output.name)
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino
            ) or temporary.stat().st_size != before.st_size:
                raise OSError("Recording changed while copying; retry after the transfer finishes")
            target = inbox / f"{path.stem}__usb_{digest.hexdigest()[:16]}{path.suffix.lower()}"
            if target.is_symlink():
                raise OSError("Refusing a symbolic-link inbox destination")
            if target.exists():
                # Never overwrite an existing inbox entry, including a corrupt
                # or manually modified copy whose name still claims this hash.
                with target.open("rb") as existing:
                    existing_digest = hashlib.file_digest(existing, "sha256").hexdigest()
                if existing_digest != digest.hexdigest():
                    raise OSError("Conflicting local acquisition; resolve the inbox conflict before retrying")
                result["already_copied"].append(str(target))
            else:
                # Acquisition has finished and checked source stability. Make
                # this complete copy immediately eligible, ordered by local
                # acquisition time. Reacquired duplicates must sort behind
                # pending older copies when the runner has a scan limit.
                ready_at = time.time() - settle_time_s - 1.0
                os.utime(temporary, (ready_at, ready_at))
                os.replace(temporary, target)
                result["copied"].append(str(target))
        except OSError as error:
            result["errors"].append({"file": path.name, "error": str(error)})
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return result
