from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
import hashlib
import json
import time

import ipywidgets as W
import pandas as pd
from ipydatagrid import DataGrid, TextRenderer


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
    if not artifacts_dir.exists():
        return []
    return artifacts_dir.rglob("*.json")


def _extract_sha256_from_manifest(obj: Any) -> Optional[str]:
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


@dataclass(frozen=True)
class FileRow:
    path: Path
    file_name: str
    size_bytes: int
    size_kb: int
    modified_label: str
    processed: bool
    processed_label: str


class _GridSelectionShim:
    """
    Minimal compatibility shim for notebook code that expects
    `selector.w_files.options` and can set `selector.w_files.value`.
    """

    def __init__(self, owner: "PreprocessLogSelector") -> None:
        self._owner = owner

    @property
    def options(self) -> Tuple[str, ...]:
        return tuple(self._owner._visible_option_labels)

    @property
    def value(self) -> Tuple[str, ...]:
        selected = {str(p.resolve()) for p in self._owner.get_selected_files()}
        return tuple(
            label
            for label in self.options
            if label in selected
        )

    @value.setter
    def value(self, labels: Sequence[str]) -> None:
        self._owner._set_selected_from_option_labels(labels)


class PreprocessLogSelector:
    _COL_FILE = "File"
    _COL_SIZE = "Size (KB)"
    _COL_MODIFIED = "Modified"
    _COL_STATUS = "Status"

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
        self.max_list_height_px = max_list_height_px

        self._state = SelectorState(**_read_json(self.state_file, {"last_dir": ""}))
        self._sha_cache: Dict[str, Dict[str, Any]] = _read_json(self.sha_cache_file, {})
        self._processed_sha: Set[str] = set()
        self._dir: Optional[Path] = None
        self._items: List[Path] = []
        self._visible_df = self._empty_table_df()
        self._index_to_path: Dict[int, Path] = {}
        self._visible_option_labels: List[str] = []

        self.w_dir = W.Text(
            value=self._state.last_dir or str(Path.cwd()),
            description="Log dir",
            layout=W.Layout(width="100%"),
        )
        self.b_browse = W.Button(description="Browse...", icon="folder-open", button_style="")
        self.b_refresh = W.Button(description="Refresh", icon="refresh", button_style="info")
        self.w_show_processed = W.Checkbox(value=False, description="Show files already processed")
        self.b_select_all = W.Button(description="Select all visible", icon="check", button_style="")
        self.b_clear = W.Button(description="Clear selection", icon="times", button_style="")

        self.grid = DataGrid(
            self._visible_df,
            selection_mode="row",
            header_visibility="column",
            base_column_size=128,
            base_row_size=30,
            layout=W.Layout(width="100%", height=f"{max_list_height_px}px"),
            auto_fit_columns=False,
            column_widths={
                self._COL_FILE: 360,
                self._COL_SIZE: 110,
                self._COL_MODIFIED: 170,
                self._COL_STATUS: 120,
            },
            default_renderer=TextRenderer(
                font="13px Segoe UI, Tahoma, Arial, sans-serif",
                vertical_alignment="center",
                background_color="#ffffff",
            ),
            header_renderer=TextRenderer(
                font="600 12px Segoe UI, Tahoma, Arial, sans-serif",
                vertical_alignment="center",
                background_color="#f5f7fa",
            ),
            grid_style={
                "background_color": "#ffffff",
                "grid_line_color": "#e5e7eb",
                "header_background_color": "#f5f7fa",
                "header_grid_line_color": "#d9dde3",
                "selection_fill_color": "rgba(156, 163, 175, 0.18)",
                "selection_border_color": "#9ca3af",
                "header_selection_fill_color": "rgba(156, 163, 175, 0.18)",
                "header_selection_border_color": "#9ca3af",
            },
        )
        self.w_files = _GridSelectionShim(self)

        self.w_status = W.HTML("")
        self.w_out = W.Output(layout=W.Layout(border="1px solid #ddd", padding="8px"))

        self.b_browse.on_click(lambda _: self._on_browse())
        self.b_refresh.on_click(lambda _: self.refresh())
        self.w_show_processed.observe(lambda _: self.refresh(), names="value")
        self.b_select_all.on_click(lambda _: self.select_all_visible())
        self.b_clear.on_click(lambda _: self.clear_selection())

        self.ui = W.VBox(
            [
                W.HBox([self.w_dir, self.b_browse, self.b_refresh]),
                W.HBox([self.w_show_processed, self.b_select_all, self.b_clear]),
                self.grid,
                self.w_status,
                self.w_out,
            ],
            layout=W.Layout(width="100%"),
        )

        self.refresh()

    def get_selected_files(self) -> List[Path]:
        selected: List[Path] = []
        visible_df = self.grid.get_visible_data()
        seen: Set[str] = set()

        for rect in list(self.grid.selections or []):
            row_start = int(rect.get("r1", -1))
            row_end = int(rect.get("r2", -1))
            if row_start < 0 or row_end < row_start:
                continue

            for row_idx in range(row_start, row_end + 1):
                if row_idx < 0 or row_idx >= len(visible_df.index):
                    continue
                path = self._index_to_path.get(int(visible_df.index[row_idx]))
                if path is None:
                    continue
                path_str = str(path.resolve())
                if path_str in seen:
                    continue
                seen.add(path_str)
                selected.append(path.resolve())

        return sorted(selected)

    def select_all_visible(self) -> None:
        visible_df = self.grid.get_visible_data()
        self.grid.clear_selection()
        if visible_df.empty:
            return
        last_row = len(visible_df.index) - 1
        last_col = max(0, len(visible_df.columns) - 1)
        self.grid.select(0, 0, last_row, last_col, clear_mode="all")

    def clear_selection(self) -> None:
        self.grid.clear_selection()

    def refresh(self) -> None:
        previously_selected = {str(p.resolve()) for p in self.get_selected_files()}

        d = Path(self.w_dir.value).expanduser()
        self._dir = d if d.exists() else None
        self._processed_sha = load_processed_sha256_set(self.artifacts_dir)

        files: List[Path] = []
        if self._dir and self._dir.exists():
            files.extend(sorted(self._dir.glob(self.file_glob)))
            if self.include_lowercase_csv and self.file_glob.upper() == "*.CSV":
                files.extend(sorted(self._dir.glob("*.csv")))
            files = sorted({p.resolve() for p in files})

        show_processed = bool(self.w_show_processed.value)

        new_files: List[Path] = []
        processed_files: List[Path] = []
        rows: List[FileRow] = []
        n_hash_misses = 0

        t0 = time.time()
        for p in files:
            sha, from_cache = self._get_sha_cached(p)
            if not from_cache:
                n_hash_misses += 1

            processed = sha in self._processed_sha
            if processed:
                processed_files.append(p)
            else:
                new_files.append(p)

            rows.append(self._build_row(p, processed=processed))
        t1 = time.time()

        self._items = files
        visible_rows = rows if show_processed else [row for row in rows if not row.processed]
        self._set_table_rows(visible_rows)
        self._restore_selection(previously_selected)

        hidden_processed = len(processed_files) if not show_processed else 0
        self.w_status.value = (
            f"<b>Found:</b> {len(files)} CSV(s) &nbsp;&nbsp;"
            f"<b>New:</b> {len(new_files)} &nbsp;&nbsp;"
            f"<b>Processed:</b> {len(processed_files)}"
            + (f" &nbsp;&nbsp; <b>Hidden processed:</b> {hidden_processed}" if hidden_processed else "")
        )

        if self._dir:
            self._state.last_dir = str(self._dir)
            _write_json(self.state_file, {"last_dir": self._state.last_dir})

        if n_hash_misses:
            _write_json(self.sha_cache_file, self._sha_cache)

        with self.w_out:
            self.w_out.clear_output()
            if self._dir is None:
                print("Log directory does not exist:", self.w_dir.value)
            else:
                print(f"Scanned: {self._dir}")
                print(f"Artifacts dir: {self.artifacts_dir}  (processed sha entries: {len(self._processed_sha)})")
                if n_hash_misses:
                    print(f"Hashed {n_hash_misses} file(s) (cache misses) in {t1 - t0:.2f}s")
                else:
                    print("No hashing needed (all hits from local cache).")

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

    def _empty_table_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                self._COL_FILE,
                self._COL_SIZE,
                self._COL_MODIFIED,
                self._COL_STATUS,
            ]
        )

    def _build_row(self, p: Path, *, processed: bool) -> FileRow:
        try:
            stat = p.stat()
            size_bytes = int(stat.st_size)
            modified_ts = float(stat.st_mtime)
        except Exception:
            size_bytes = 0
            modified_ts = 0.0

        modified_label = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(modified_ts))
            if self.show_mtime and modified_ts
            else ""
        )
        return FileRow(
            path=p,
            file_name=p.name,
            size_bytes=size_bytes,
            size_kb=max(1, int(round(size_bytes / 1024))) if self.show_size and size_bytes else 0,
            modified_label=modified_label,
            processed=processed,
            processed_label="processed" if processed else "new",
        )

    def _set_table_rows(self, rows: Sequence[FileRow]) -> None:
        records: List[Dict[str, Any]] = []
        self._index_to_path = {}
        self._visible_option_labels = []

        for idx, row in enumerate(rows):
            self._index_to_path[idx] = row.path.resolve()
            self._visible_option_labels.append(str(row.path.resolve()))
            records.append(
                {
                    self._COL_FILE: row.file_name,
                    self._COL_SIZE: row.size_kb,
                    self._COL_MODIFIED: row.modified_label,
                    self._COL_STATUS: row.processed_label,
                }
            )

        df = pd.DataFrame.from_records(records, columns=self._empty_table_df().columns)
        df.index = pd.RangeIndex(start=0, stop=len(df), step=1)
        self._visible_df = df
        self.grid.data = df
        self.grid.clear_selection()

    def _restore_selection(self, selected_paths: Set[str]) -> None:
        if not selected_paths:
            return

        visible_df = self.grid.get_visible_data()
        matching_rows: List[int] = []
        for row_pos in range(len(visible_df.index)):
            path = self._index_to_path.get(int(visible_df.index[row_pos]))
            if path and str(path.resolve()) in selected_paths:
                matching_rows.append(row_pos)

        if not matching_rows:
            return

        self.grid.clear_selection()
        last_col = max(0, len(visible_df.columns) - 1)
        for row_pos in matching_rows:
            self.grid.select(row_pos, 0, row_pos, last_col, clear_mode="none")

    def _set_selected_from_option_labels(self, labels: Sequence[str]) -> None:
        visible_df = self.grid.get_visible_data()
        label_set = set(labels)
        matching_rows: List[int] = []

        for row_pos in range(len(visible_df.index)):
            path = self._index_to_path.get(int(visible_df.index[row_pos]))
            if path and str(path.resolve()) in label_set:
                matching_rows.append(row_pos)

        self.grid.clear_selection()
        if not matching_rows:
            return

        last_col = max(0, len(visible_df.columns) - 1)
        for row_pos in matching_rows:
            self.grid.select(row_pos, 0, row_pos, last_col, clear_mode="none")

    def _cache_key(self, p: Path) -> str:
        try:
            st = p.stat()
            return f"{str(p.resolve())}|{st.st_size}|{int(st.st_mtime)}"
        except Exception:
            return str(p.resolve())

    def _get_sha_cached(self, p: Path) -> Tuple[str, bool]:
        key = self._cache_key(p)
        rec = self._sha_cache.get(key)
        if isinstance(rec, dict):
            sha = rec.get("sha256")
            if isinstance(sha, str) and sha:
                return sha, True

        sha = _sha256_file(p)
        self._sha_cache[key] = {"sha256": sha}
        return sha, False
