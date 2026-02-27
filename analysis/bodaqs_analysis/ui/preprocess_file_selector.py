# bodaqs_analysis/ui/preprocess_file_selector.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import hashlib
import json
import os
import time

import ipywidgets as W


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        # Best-effort only
        pass


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _iter_manifest_json_files(artifacts_dir: Path) -> Iterable[Path]:
    """
    Best-effort manifest discovery:
    - scan for *.json under artifacts_dir
    - parse and keep those that look like manifests (contain 'source' dict)
    """
    if not artifacts_dir.exists():
        return []
    # Conservative: scan only json files; artifacts trees are typically manageable
    return artifacts_dir.rglob("*.json")


def _extract_sha256_from_manifest(obj: Any) -> Optional[str]:
    """
    Return sha256 if obj looks like a manifest with a source sha256.
    We keep this permissive to avoid depending on exact manifest schema/filename.
    """
    if not isinstance(obj, dict):
        return None
    src = obj.get("source")
    if not isinstance(src, dict):
        return None
    sha = src.get("sha256")
    if isinstance(sha, str) and len(sha) >= 32:
        return sha.strip()
    return None


def load_processed_sha256_set(artifacts_dir: Path) -> Set[str]:
    """
    Scan artifacts_dir for manifest json files and collect source.sha256 values.
    """
    out: Set[str] = set()
    for p in _iter_manifest_json_files(artifacts_dir):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        sha = _extract_sha256_from_manifest(obj)
        if sha:
            out.add(sha)
    return out


@dataclass
class SelectorState:
    last_dir: str = ""


class PreprocessLogSelector:
    """
    Step 1 UI:
      - Choose log directory
      - Show CSV files in that directory in a list box
      - Checkbox: hide/show files already processed (based on sha256)
      - Remember last-used dir and cache file hashes for speed
    """

    def __init__(
        self,
        *,
        artifacts_dir: Path = Path("artifacts"),
        state_file: Path = Path(".bodaqs_preprocess_last_dir.json"),
        sha_cache_file: Path = Path(".bodaqs_preprocess_sha_cache.json"),
        file_glob: str = "*.CSV",
        include_lowercase_csv: bool = True,
        show_mtime: bool = True,
        show_size: bool = True,
        max_list_height_px: int = 260,
    ) -> None:
        self.artifacts_dir = Path(artifacts_dir)
        self.state_file = Path(state_file)
        self.sha_cache_file = Path(sha_cache_file)
        self.file_glob = file_glob
        self.include_lowercase_csv = include_lowercase_csv
        self.show_mtime = show_mtime
        self.show_size = show_size

        self._state = SelectorState(**_read_json(self.state_file, {"last_dir": ""}))
        self._sha_cache: Dict[str, Dict[str, Any]] = _read_json(self.sha_cache_file, {})
        # runtime
        self._processed_sha: Set[str] = set()
        self._dir: Optional[Path] = None
        self._items: List[Path] = []
        self._display_to_path: Dict[str, Path] = {}

        # ---- Widgets ----
        self.w_dir = W.Text(
            value=self._state.last_dir or str(Path.cwd()),
            description="Log dir",
            layout=W.Layout(width="100%"),
        )
        self.b_browse = W.Button(description="Browse…", icon="folder-open", button_style="")
        self.b_refresh = W.Button(description="Refresh", icon="refresh", button_style="info")

        self.w_show_processed = W.Checkbox(value=False, description="Show files already processed")
        self.b_select_all = W.Button(description="Select all visible", icon="check", button_style="")
        self.b_clear = W.Button(description="Clear selection", icon="times", button_style="")

        self.w_files = W.SelectMultiple(
            options=[],
            value=(),
            description="Files",
            layout=W.Layout(width="100%", height=f"{max_list_height_px}px"),
        )

        self.w_status = W.HTML("")
        self.w_out = W.Output(layout=W.Layout(border="1px solid #ddd", padding="8px"))

        # Wire up events
        self.b_browse.on_click(lambda _: self._on_browse())
        self.b_refresh.on_click(lambda _: self.refresh())
        self.w_show_processed.observe(lambda _: self.refresh(), names="value")
        self.b_select_all.on_click(lambda _: self._on_select_all())
        self.b_clear.on_click(lambda _: self._on_clear())

        # Build UI
        self.ui = W.VBox(
            [
                W.HBox([self.w_dir, self.b_browse, self.b_refresh]),
                W.HBox([self.w_show_processed, self.b_select_all, self.b_clear]),
                self.w_files,
                self.w_status,
                self.w_out,
            ],
            layout=W.Layout(width="100%"),
        )

        # initial refresh
        self.refresh()

    # ---------- Public API ----------
    def get_selected_files(self) -> List[Path]:
        sel = list(self.w_files.value or ())
        # value contains display strings (options), so map back to paths
        out: List[Path] = []
        for s in sel:
            p = self._display_to_path.get(str(s))
            if p:
                out.append(p)
        return sorted(out)

    def refresh(self) -> None:
        d = Path(self.w_dir.value).expanduser()
        self._dir = d if d.exists() else None

        # load processed sha set (can be a bit expensive; ok on refresh)
        self._processed_sha = load_processed_sha256_set(self.artifacts_dir)

        files: List[Path] = []
        if self._dir and self._dir.exists():
            files.extend(sorted(self._dir.glob(self.file_glob)))
            if self.include_lowercase_csv and self.file_glob.upper() == "*.CSV":
                files.extend(sorted(self._dir.glob("*.csv")))
            # de-dup
            files = sorted({p.resolve() for p in files})

        # classify processed/new using sha (with cache)
        show_processed = bool(self.w_show_processed.value)

        new_files: List[Path] = []
        processed_files: List[Path] = []
        n_hash_misses = 0

        t0 = time.time()
        for p in files:
            sha, from_cache = self._get_sha_cached(p)
            if not from_cache:
                n_hash_misses += 1

            if sha in self._processed_sha:
                processed_files.append(p)
            else:
                new_files.append(p)
        t1 = time.time()

        visible = files if show_processed else new_files

        # update listbox options
        options: List[str] = []
        self._display_to_path.clear()
        for p in visible:
            label = self._format_file_label(p, processed=(p in processed_files))
            options.append(label)
            self._display_to_path[label] = p

        # Keep selection only if still visible
        old_sel = set(map(str, self.w_files.value or ()))
        new_sel = tuple([o for o in options if o in old_sel])

        self.w_files.options = options
        self.w_files.value = new_sel

        # status
        hidden_processed = len(processed_files) if not show_processed else 0
        self.w_status.value = (
            f"<b>Found:</b> {len(files)} CSV(s) &nbsp;&nbsp;"
            f"<b>New:</b> {len(new_files)} &nbsp;&nbsp;"
            f"<b>Processed:</b> {len(processed_files)}"
            + (f" &nbsp;&nbsp; <b>Hidden processed:</b> {hidden_processed}" if hidden_processed else "")
        )

        # remember dir
        if self._dir:
            self._state.last_dir = str(self._dir)
            _write_json(self.state_file, {"last_dir": self._state.last_dir})

        # cache write-through (only if we hashed anything new)
        if n_hash_misses:
            _write_json(self.sha_cache_file, self._sha_cache)

        # brief debug output
        with self.w_out:
            self.w_out.clear_output()
            if self._dir is None:
                print("⚠️ Log directory does not exist:", self.w_dir.value)
            else:
                print(f"Scanned: {self._dir}")
                print(f"Artifacts dir: {self.artifacts_dir}  (processed sha entries: {len(self._processed_sha)})")
                if n_hash_misses:
                    print(f"Hashed {n_hash_misses} file(s) (cache misses) in {t1 - t0:.2f}s")
                else:
                    print("No hashing needed (all hits from local cache).")

    # ---------- UI handlers ----------
    def _on_select_all(self) -> None:
        self.w_files.value = tuple(self.w_files.options or ())

    def _on_clear(self) -> None:
        self.w_files.value = ()

    def _on_browse(self) -> None:
        import tkinter as tk
        from tkinter import filedialog

        start_dir = self.w_dir.value if self.w_dir.value and Path(self.w_dir.value).exists() else str(Path.cwd())

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title="Select log directory", initialdir=start_dir)
        root.destroy()

        if chosen:
            self.w_dir.value = chosen
            self.refresh()

    # ---------- SHA cache ----------
    def _cache_key(self, p: Path) -> str:
        try:
            st = p.stat()
            return f"{str(p.resolve())}|{st.st_size}|{int(st.st_mtime)}"
        except Exception:
            return str(p.resolve())

    def _get_sha_cached(self, p: Path) -> Tuple[str, bool]:
        """
        Returns (sha256, from_cache).
        Cache is keyed by (path|size|mtime) to survive edits reliably.
        """
        key = self._cache_key(p)
        rec = self._sha_cache.get(key)
        if isinstance(rec, dict):
            sha = rec.get("sha256")
            if isinstance(sha, str) and sha:
                return sha, True

        sha = _sha256_file(p)
        self._sha_cache[key] = {"sha256": sha}
        return sha, False

    # ---------- formatting ----------
    def _format_file_label(self, p: Path, *, processed: bool) -> str:
        parts = [p.name]

        if self.show_size:
            try:
                sz = p.stat().st_size
                parts.append(f"{sz/1024:.0f} KB" if sz < 1024**2 else f"{sz/1024**2:.2f} MB")
            except Exception:
                pass

        if self.show_mtime:
            try:
                ts = p.stat().st_mtime
                parts.append(time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)))
            except Exception:
                pass

        # You asked to hide processed files when unchecked, so this is only informational
        # when show_processed is enabled.
        if processed:
            parts.append("processed")

        return " | ".join(parts)