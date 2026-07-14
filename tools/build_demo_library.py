from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


RECIPE_SCHEMA = "bodaqs.demo_library_recipe"
RECIPE_VERSION = 1
DEMO_MANIFEST_SCHEMA = "bodaqs.demo_library_manifest"
DEMO_MANIFEST_VERSION = 1
LIBRARY_DEFINITION_FILENAME = "library_definition.json"


@dataclass(frozen=True)
class SessionRef:
    run_id: str
    session_id: str

    @property
    def key(self) -> str:
        return f"{self.run_id}::{self.session_id}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a curated, relocatable BODAQS demonstration library from an existing library."
    )
    parser.add_argument("recipe", help="Path to a demo-library recipe JSON file.")
    parser.add_argument("--force", action="store_true", help="Replace the output directory if it already exists.")
    args = parser.parse_args()

    recipe_path = Path(args.recipe).expanduser().resolve()
    recipe = _read_json_object(recipe_path)
    validate_recipe(recipe, recipe_path=recipe_path)

    output_root = Path(recipe["output_root"]).expanduser().resolve()
    if output_root.exists() and any(output_root.iterdir()):
        if not args.force:
            raise SystemExit(f"Output root already exists and is not empty: {output_root}")
        _clear_output_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    report = build_demo_library(recipe, output_root=output_root)
    manifest_path = output_root / "demo_manifest.json"
    _write_json(manifest_path, report)

    print(f"Demo library written to: {output_root}")
    print(f"Manifest written to: {manifest_path}")
    print(f"Included sessions: {len(report['sessions'])}")
    print(f"Warnings: {len(report['warnings'])}")
    for warning in report["warnings"]:
        print(f"  - {warning}")
    return 0


def validate_recipe(recipe: Mapping[str, Any], *, recipe_path: Path) -> None:
    if recipe.get("schema") != RECIPE_SCHEMA:
        raise ValueError(f"Unexpected recipe schema in {recipe_path}: {recipe.get('schema')!r}")
    if int(recipe.get("version", -1)) != RECIPE_VERSION:
        raise ValueError(f"Unexpected recipe version in {recipe_path}: {recipe.get('version')!r}")
    for field in ("source_libraries_root", "source_library_id", "output_root", "demo_library_id", "demo_display_name"):
        if not _text(recipe.get(field)):
            raise ValueError(f"Recipe must include non-empty {field!r}")


def build_demo_library(recipe: Mapping[str, Any], *, output_root: Path) -> dict[str, Any]:
    source_libraries_root = Path(recipe["source_libraries_root"]).expanduser().resolve()
    source_library_id = str(recipe["source_library_id"]).strip()
    demo_library_id = str(recipe["demo_library_id"]).strip()
    demo_display_name = str(recipe["demo_display_name"]).strip()
    anonymize = recipe.get("anonymize") if isinstance(recipe.get("anonymize"), Mapping) else {}
    include_referenced_sessions = bool(recipe.get("include_referenced_sessions", True))
    include_bookmarks_for_sessions = bool(recipe.get("include_bookmarks_for_sessions", True))

    source_library_root = _find_library_root(source_libraries_root, source_library_id)
    if source_library_root is None:
        raise FileNotFoundError(f"Could not find source library {source_library_id!r} under {source_libraries_root}")

    warnings: list[str] = []
    selected_sessions = _recipe_sessions(recipe.get("sessions"))
    selected_sessions.update(_recipe_run_sessions(source_library_root, recipe.get("runs"), warnings=warnings))
    selected_study_set_ids = _string_list(recipe.get("study_sets"))
    selected_track_ids = set(_string_list(recipe.get("tracks")))
    selected_bookmark_ids = set(_string_list(recipe.get("bookmarks")))
    selected_filter_ids = set(_string_list(recipe.get("session_filters")))

    study_set_docs: list[tuple[str, dict[str, Any]]] = []
    for study_set_id in selected_study_set_ids:
        study_set_path = _root_json_path(source_libraries_root, "study_sets", study_set_id)
        if not study_set_path.exists():
            warnings.append(f"Study set not found and was skipped: {study_set_id}")
            continue
        doc = _read_json_object(study_set_path)
        study_set_docs.append((study_set_id, doc))
        if include_referenced_sessions:
            for session in doc.get("sessions") or []:
                if not isinstance(session, Mapping):
                    continue
                if str(session.get("library_id") or "") != source_library_id:
                    continue
                run_id = _text(session.get("run_id"))
                session_id = _text(session.get("session_id"))
                if run_id and session_id:
                    selected_sessions.add(SessionRef(run_id, session_id))
        for track in doc.get("tracks") or []:
            if isinstance(track, Mapping) and _text(track.get("track_id")):
                selected_track_ids.add(str(track["track_id"]).strip())

    if not selected_sessions:
        raise ValueError("Recipe did not resolve any sessions to include.")

    output_library_root = output_root / "libraries" / demo_library_id
    _copy_library_shared_assets(source_library_root, output_library_root)
    copied_sessions = _copy_selected_sessions(
        source_library_root,
        output_library_root,
        selected_sessions=selected_sessions,
        warnings=warnings,
    )
    _write_demo_library_definition(
        source_library_root,
        output_library_root,
        library_id=demo_library_id,
        display_name=demo_display_name,
    )

    session_keys = {session.key for session in copied_sessions}
    old_ref_to_new = {
        f"{source_library_id}|||{session.key}": f"{demo_library_id}|||{session.key}" for session in copied_sessions
    }

    copied_study_sets = _copy_study_sets(
        output_root,
        study_set_docs=study_set_docs,
        source_library_id=source_library_id,
        demo_library_id=demo_library_id,
        session_keys=session_keys,
        old_ref_to_new=old_ref_to_new,
        anonymize=anonymize,
        warnings=warnings,
    )
    copied_tracks = _copy_root_assets(
        source_libraries_root,
        output_root,
        dirname="tracks",
        object_ids=selected_track_ids,
        source_library_id=source_library_id,
        demo_library_id=demo_library_id,
        old_ref_to_new=old_ref_to_new,
        anonymize=anonymize,
        warnings=warnings,
    )
    if include_bookmarks_for_sessions:
        selected_bookmark_ids.update(
            _bookmark_ids_for_sessions(source_libraries_root, set(old_ref_to_new))
        )
    copied_bookmarks = _copy_root_assets(
        source_libraries_root,
        output_root,
        dirname="bookmarks",
        object_ids=selected_bookmark_ids,
        source_library_id=source_library_id,
        demo_library_id=demo_library_id,
        old_ref_to_new=old_ref_to_new,
        anonymize=anonymize,
        warnings=warnings,
    )
    copied_filters = _copy_root_assets(
        source_libraries_root,
        output_root,
        dirname="session_filters",
        object_ids=selected_filter_ids,
        source_library_id=source_library_id,
        demo_library_id=demo_library_id,
        old_ref_to_new=old_ref_to_new,
        anonymize=anonymize,
        warnings=warnings,
    )

    _rewrite_json_files(
        output_root,
        source_library_id=source_library_id,
        demo_library_id=demo_library_id,
        old_ref_to_new=old_ref_to_new,
        anonymize=anonymize,
        source_paths=[source_libraries_root, source_library_root],
    )

    integrity_warnings = _validate_output(output_library_root, copied_sessions)
    warnings.extend(integrity_warnings)
    warnings.extend(_validate_study_set_references(output_root, output_library_root, demo_library_id=demo_library_id))

    return {
        "schema": DEMO_MANIFEST_SCHEMA,
        "version": DEMO_MANIFEST_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "library": {
            "library_id": demo_library_id,
            "display_name": demo_display_name,
            "root": str(output_library_root),
        },
        "source": {
            "libraries_root": str(source_libraries_root),
            "library_id": source_library_id,
        },
        "sessions": [{"run_id": session.run_id, "session_id": session.session_id} for session in copied_sessions],
        "study_sets": copied_study_sets,
        "tracks": copied_tracks,
        "bookmarks": copied_bookmarks,
        "session_filters": copied_filters,
        "warnings": sorted(set(warnings)),
    }


def _find_library_root(libraries_root: Path, library_id: str) -> Path | None:
    for search_root in (libraries_root / "libraries", libraries_root):
        if not search_root.exists():
            continue
        for definition_path in sorted(search_root.glob(f"*/{LIBRARY_DEFINITION_FILENAME}")):
            try:
                definition = _read_json_object(definition_path)
            except Exception:
                continue
            if str(definition.get("library_id") or "") == library_id:
                return definition_path.parent.resolve()
    return None


def _copy_library_shared_assets(source_library_root: Path, output_library_root: Path) -> None:
    output_library_root.mkdir(parents=True, exist_ok=True)
    for child in source_library_root.iterdir():
        if child.name in {"runs", "syn", LIBRARY_DEFINITION_FILENAME}:
            continue
        target = output_library_root / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        elif child.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _copy_selected_sessions(
    source_library_root: Path,
    output_library_root: Path,
    *,
    selected_sessions: set[SessionRef],
    warnings: list[str],
) -> list[SessionRef]:
    copied: list[SessionRef] = []
    by_run: dict[str, list[str]] = {}
    for session in sorted(selected_sessions, key=lambda item: (item.run_id, item.session_id)):
        source_session_dir = source_library_root / "runs" / session.run_id / "sessions" / session.session_id
        if not source_session_dir.exists():
            warnings.append(f"Session not found and was skipped: {session.key}")
            continue
        target_session_dir = output_library_root / "runs" / session.run_id / "sessions" / session.session_id
        shutil.copytree(source_session_dir, target_session_dir, dirs_exist_ok=True)
        by_run.setdefault(session.run_id, []).append(session.session_id)
        copied.append(session)

    for run_id, session_ids in by_run.items():
        source_manifest_path = source_library_root / "runs" / run_id / "manifest.json"
        target_manifest_path = output_library_root / "runs" / run_id / "manifest.json"
        if source_manifest_path.exists():
            manifest = _read_json_object(source_manifest_path)
        else:
            manifest = {"run_id": run_id}
            warnings.append(f"Run manifest missing; created a minimal manifest for {run_id}")
        manifest["sessions"] = sorted(session_ids)
        _write_json(target_manifest_path, manifest)

    return copied


def _write_demo_library_definition(
    source_library_root: Path,
    output_library_root: Path,
    *,
    library_id: str,
    display_name: str,
) -> None:
    source_definition_path = source_library_root / LIBRARY_DEFINITION_FILENAME
    definition = _read_json_object(source_definition_path) if source_definition_path.exists() else {}
    definition.update(
        {
            "schema": "bodaqs.import_agent_library",
            "version": 1,
            "library_id": library_id,
            "display_name": display_name,
            "artifacts_dir": str(output_library_root),
        }
    )
    _write_json(output_library_root / LIBRARY_DEFINITION_FILENAME, definition)


def _copy_study_sets(
    output_root: Path,
    *,
    study_set_docs: Sequence[tuple[str, dict[str, Any]]],
    source_library_id: str,
    demo_library_id: str,
    session_keys: set[str],
    old_ref_to_new: Mapping[str, str],
    anonymize: Mapping[str, Any],
    warnings: list[str],
) -> list[str]:
    copied: list[str] = []
    out_dir = output_root / "study_sets"
    for study_set_id, doc in study_set_docs:
        filtered = _filter_study_set_sessions(doc, session_keys=session_keys, warnings=warnings)
        rewritten = _rewrite_payload(
            filtered,
            source_library_id=source_library_id,
            demo_library_id=demo_library_id,
            old_ref_to_new=old_ref_to_new,
            anonymize=anonymize,
            source_paths=[],
        )
        _write_json(out_dir / f"{study_set_id}.json", rewritten)
        copied.append(study_set_id)
    return copied


def _filter_study_set_sessions(
    doc: Mapping[str, Any],
    *,
    session_keys: set[str],
    warnings: list[str],
) -> dict[str, Any]:
    updated = dict(doc)
    updated["sessions"] = [
        dict(session)
        for session in doc.get("sessions") or []
        if isinstance(session, Mapping) and str(session.get("session_key") or "") in session_keys
    ]
    valid_refs = {
        str(session.get("session_ref_id"))
        for session in updated["sessions"]
        if isinstance(session, Mapping) and session.get("session_ref_id")
    }
    groupings = []
    for grouping in doc.get("groupings") or []:
        if not isinstance(grouping, Mapping):
            continue
        kept_refs = [ref for ref in grouping.get("session_refs") or [] if str(ref) in valid_refs]
        if kept_refs:
            next_grouping = dict(grouping)
            next_grouping["session_refs"] = kept_refs
            groupings.append(next_grouping)
    updated["groupings"] = groupings
    if len(updated["sessions"]) != len(doc.get("sessions") or []):
        warnings.append(f"Study set {doc.get('study_set_id') or '<unknown>'} was filtered to selected demo sessions.")
    return updated


def _copy_root_assets(
    source_root: Path,
    output_root: Path,
    *,
    dirname: str,
    object_ids: set[str],
    source_library_id: str,
    demo_library_id: str,
    old_ref_to_new: Mapping[str, str],
    anonymize: Mapping[str, Any],
    warnings: list[str],
) -> list[str]:
    copied: list[str] = []
    if not object_ids:
        return copied
    out_dir = output_root / dirname
    for object_id in sorted(object_ids):
        source_path = _root_json_path(source_root, dirname, object_id)
        if not source_path.exists():
            warnings.append(f"{dirname} asset not found and was skipped: {object_id}")
            continue
        payload = _read_json_object(source_path)
        rewritten = _rewrite_payload(
            payload,
            source_library_id=source_library_id,
            demo_library_id=demo_library_id,
            old_ref_to_new=old_ref_to_new,
            anonymize=anonymize,
            source_paths=[source_root],
        )
        _write_json(out_dir / source_path.name, rewritten)
        copied.append(object_id)
    return copied


def _bookmark_ids_for_sessions(source_root: Path, old_ref_ids: set[str]) -> set[str]:
    out: set[str] = set()
    bookmarks_dir = source_root / "bookmarks"
    if not bookmarks_dir.exists():
        return out
    for path in bookmarks_dir.glob("*.json"):
        try:
            payload = _read_json_object(path)
        except Exception:
            continue
        if str(payload.get("session_ref_id") or "") in old_ref_ids:
            out.add(path.stem)
    return out


def _rewrite_json_files(
    root: Path,
    *,
    source_library_id: str,
    demo_library_id: str,
    old_ref_to_new: Mapping[str, str],
    anonymize: Mapping[str, Any],
    source_paths: Sequence[Path],
) -> None:
    for path in root.rglob("*.json"):
        if "recipes" in path.relative_to(root).parts:
            continue
        payload = _read_json_object(path)
        rewritten = _rewrite_payload(
            payload,
            source_library_id=source_library_id,
            demo_library_id=demo_library_id,
            old_ref_to_new=old_ref_to_new,
            anonymize=anonymize,
            source_paths=source_paths,
        )
        _write_json(path, rewritten)


def _rewrite_payload(
    value: Any,
    *,
    source_library_id: str,
    demo_library_id: str,
    old_ref_to_new: Mapping[str, str],
    anonymize: Mapping[str, Any],
    source_paths: Sequence[Path],
) -> Any:
    replace_text = anonymize.get("replace_text") if isinstance(anonymize.get("replace_text"), Mapping) else {}
    remove_absolute_paths = bool(anonymize.get("remove_absolute_paths", True))

    def rewrite(item: Any, key: str | None = None) -> Any:
        if isinstance(item, Mapping):
            return {str(k): rewrite(v, str(k)) for k, v in item.items()}
        if isinstance(item, list):
            return [rewrite(v, key) for v in item]
        if isinstance(item, str):
            text = item
            if key == "library_id" and text == source_library_id:
                text = demo_library_id
            for old, new in old_ref_to_new.items():
                text = text.replace(old, new)
            for old, new in replace_text.items():
                text = text.replace(str(old), str(new))
            if remove_absolute_paths:
                for source_path in source_paths:
                    source_text = str(source_path)
                    if source_text and source_text in text:
                        text = text.replace(source_text, "<source-library>")
            return text
        return item

    return rewrite(value)


def _validate_output(library_root: Path, sessions: Sequence[SessionRef]) -> list[str]:
    warnings: list[str] = []
    definition_path = library_root / LIBRARY_DEFINITION_FILENAME
    if not definition_path.exists():
        warnings.append("Output library is missing library_definition.json")
    for session in sessions:
        base = library_root / "runs" / session.run_id / "sessions" / session.session_id
        for relative in ("manifest.json", "session/meta.json", "session/df.parquet"):
            if not (base / relative).exists():
                warnings.append(f"{session.key} is missing {relative}")
    return warnings


def _validate_study_set_references(output_root: Path, library_root: Path, *, demo_library_id: str) -> list[str]:
    warnings: list[str] = []
    study_sets_dir = output_root / "study_sets"
    if not study_sets_dir.exists():
        return warnings
    for study_set_path in sorted(study_sets_dir.glob("*.json")):
        try:
            study_set = _read_json_object(study_set_path)
        except Exception as exc:
            warnings.append(f"Could not validate study set {study_set_path.name}: {exc}")
            continue
        for session in study_set.get("sessions") or []:
            if not isinstance(session, Mapping):
                continue
            if str(session.get("library_id") or "") != demo_library_id:
                warnings.append(
                    f"Study set {study_set_path.stem} contains a non-demo library reference: {session.get('library_id')}"
                )
                continue
            run_id = _text(session.get("run_id"))
            session_id = _text(session.get("session_id"))
            if not run_id or not session_id:
                warnings.append(f"Study set {study_set_path.stem} contains an incomplete session reference.")
                continue
            session_dir = library_root / "runs" / run_id / "sessions" / session_id
            if not session_dir.exists():
                warnings.append(f"Study set {study_set_path.stem} references a missing copied session: {run_id}::{session_id}")
    return warnings


def _recipe_sessions(value: Any) -> set[SessionRef]:
    sessions: set[SessionRef] = set()
    if not isinstance(value, list):
        return sessions
    for item in value:
        if not isinstance(item, Mapping):
            continue
        run_id = _text(item.get("run_id"))
        session_id = _text(item.get("session_id"))
        if run_id and session_id:
            sessions.add(SessionRef(run_id, session_id))
    return sessions


def _recipe_run_sessions(source_library_root: Path, value: Any, *, warnings: list[str]) -> set[SessionRef]:
    sessions: set[SessionRef] = set()
    if not isinstance(value, list):
        return sessions
    for item in value:
        run_id = _resolve_recipe_run_id(source_library_root, item, warnings=warnings)
        if not run_id:
            continue
        sessions_dir = source_library_root / "runs" / run_id / "sessions"
        if not sessions_dir.exists():
            warnings.append(f"Run has no sessions directory and was skipped: {run_id}")
            continue
        for session_dir in sorted(path for path in sessions_dir.iterdir() if path.is_dir()):
            sessions.add(SessionRef(run_id, session_dir.name))
    return sessions


def _resolve_recipe_run_id(source_library_root: Path, item: Any, *, warnings: list[str]) -> str | None:
    if isinstance(item, Mapping):
        explicit_run_id = _text(item.get("run_id"))
        if explicit_run_id:
            return explicit_run_id
        wanted = _text(item.get("description") or item.get("display_name") or item.get("name"))
    else:
        wanted = _text(item)
    if not wanted:
        return None

    runs_dir = source_library_root / "runs"
    direct_path = runs_dir / wanted
    if direct_path.exists() and direct_path.is_dir():
        return wanted
    if not runs_dir.exists():
        warnings.append(f"Source library has no runs directory: {source_library_root}")
        return None

    wanted_folded = wanted.casefold()
    exact_matches: list[tuple[str, str]] = []
    fuzzy_matches: list[tuple[str, str]] = []
    for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        description = ""
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            try:
                description = str(_read_json_object(manifest_path).get("description") or "")
            except Exception:
                description = ""
        description_folded = description.casefold()
        if description_folded == wanted_folded:
            exact_matches.append((run_dir.name, description))
        elif wanted_folded in description_folded or (description_folded and description_folded in wanted_folded):
            fuzzy_matches.append((run_dir.name, description))

    matches = exact_matches or fuzzy_matches
    if len(matches) == 1:
        run_id, description = matches[0]
        if fuzzy_matches and not exact_matches:
            warnings.append(f"Run recipe item {wanted!r} was resolved fuzzily to {run_id}: {description}")
        return run_id
    if len(matches) > 1:
        options = ", ".join(f"{run_id} ({description})" for run_id, description in matches[:8])
        warnings.append(f"Run recipe item {wanted!r} matched multiple runs and was skipped: {options}")
    else:
        warnings.append(f"Run recipe item {wanted!r} did not match any run and was skipped.")
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _root_json_path(root: Path, dirname: str, object_id: str) -> Path:
    return root / dirname / f"{object_id}.json"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clear_output_root(path: Path) -> None:
    resolved = path.resolve()
    if resolved.anchor == str(resolved):
        raise ValueError(f"Refusing to delete filesystem root: {resolved}")
    if resolved.name.lower() in {"", "libraries", "bodaqs-data"}:
        raise ValueError(f"Refusing to delete broad output root: {resolved}")
    generated_names = {
        "bookmarks",
        "demo_manifest.json",
        "libraries",
        "session_filters",
        "study_sets",
        "tracks",
    }
    for child in resolved.iterdir():
        if child.name not in generated_names:
            continue
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()


def _remove_tree(path: Path) -> None:
    def handle_readonly(func: Any, item: str, _exc_info: Any) -> None:
        os.chmod(item, stat.S_IWRITE)
        func(item)

    shutil.rmtree(path, onerror=handle_readonly)


if __name__ == "__main__":
    raise SystemExit(main())
