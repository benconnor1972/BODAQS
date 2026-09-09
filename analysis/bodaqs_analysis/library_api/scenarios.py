"""Root-scoped persisted Scenario definitions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import InvalidScenarioError, RevisionConflictError, ScenarioNotFoundError
from .ids import is_valid_object_id, make_unique_object_id


SCENARIO_SCHEMA = "bodaqs.scenario"
SCENARIO_VERSION = 1
SCENARIOS_DIR = Path("scenarios")
MAX_CRITERIA = 4
_GROUP_OPS = {"and", "or"}
_NUMERIC_OPS = {"lt", "lte", "gt", "gte", "between", "outside"}
_OTHER_OPS = {"eq", "in", "present"}


def list_scenarios(libraries_root: str | Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(_scenarios_dir(libraries_root).glob("*.json"), key=lambda item: item.name.lower()):
        raw = _read_json(path)
        out.append(normalize_scenario(raw, scenario_id=str(raw.get("scenario_id") or path.stem)))
    return out


def load_scenario(libraries_root: str | Path, scenario_id: str) -> dict[str, Any]:
    path = _scenario_path(libraries_root, scenario_id)
    if not path.exists():
        raise ScenarioNotFoundError(details={"scenario_id": scenario_id})
    return normalize_scenario(_read_json(path), scenario_id=scenario_id)


def create_scenario(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidScenarioError("Scenario payload must be a JSON object.")
    existing = [item["scenario_id"] for item in list_scenarios(libraries_root)]
    display_name = _required_text(payload.get("display_name"), "display_name")
    requested = _optional_text(payload.get("scenario_id"))
    scenario_id = requested or make_unique_object_id(display_name, existing, fallback="scenario")
    if scenario_id in existing:
        raise InvalidScenarioError("Scenario id already exists.", details={"scenario_id": scenario_id})
    now = _utcnow()
    doc = normalize_scenario(payload, scenario_id=scenario_id, revision=1, now=now)
    _write(libraries_root, doc)
    return doc


def update_scenario(
    libraries_root: str | Path,
    scenario_id: str,
    *,
    expected_revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    current = load_scenario(libraries_root, scenario_id)
    if int(expected_revision) != int(current["revision"]):
        raise RevisionConflictError(
            "Scenario was modified after it was loaded.",
            details={
                "scenario_id": scenario_id,
                "expected_revision": int(expected_revision),
                "current_revision": int(current["revision"]),
            },
        )
    doc = normalize_scenario(
        payload,
        scenario_id=scenario_id,
        revision=int(current["revision"]) + 1,
        now=_utcnow(),
        previous=current,
    )
    _write(libraries_root, doc)
    return doc


def delete_scenario(libraries_root: str | Path, scenario_id: str) -> dict[str, Any]:
    path = _scenario_path(libraries_root, scenario_id)
    if not path.exists():
        raise ScenarioNotFoundError(details={"scenario_id": scenario_id})
    path.unlink()
    return {"deleted": True, "scenario_id": scenario_id}


def normalize_scenario(
    payload: Mapping[str, Any],
    *,
    scenario_id: str | None = None,
    revision: int | None = None,
    now: str | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidScenarioError("Scenario payload must be a JSON object.")
    doc = dict(payload)
    if doc.get("schema") not in (None, SCENARIO_SCHEMA):
        raise InvalidScenarioError("Scenario schema is not supported.", details={"schema": doc.get("schema")})
    if doc.get("version") not in (None, SCENARIO_VERSION):
        raise InvalidScenarioError("Scenario version is not supported.", details={"version": doc.get("version")})
    doc["schema"] = SCENARIO_SCHEMA
    doc["version"] = SCENARIO_VERSION
    resolved_id = scenario_id or _optional_text(doc.get("scenario_id"))
    if resolved_id is not None:
        if not is_valid_object_id(resolved_id):
            raise InvalidScenarioError("Scenario id is not filename-safe.", details={"scenario_id": resolved_id})
        doc["scenario_id"] = resolved_id
    elif "scenario_id" in doc:
        doc.pop("scenario_id")
    doc["display_name"] = _required_text(doc.get("display_name"), "display_name")
    doc["description"] = _optional_text(doc.get("description")) or ""
    doc["category"] = _optional_text(doc.get("category")) or ""
    if revision is not None:
        doc["revision"] = revision
    elif scenario_id is not None and not isinstance(doc.get("revision"), int):
        raise InvalidScenarioError("Scenario revision must be an integer.")

    seen: set[str] = set()
    counter = [0]
    doc["predicate"] = _normalize_predicate(doc.get("predicate"), "predicate", seen, counter)
    if counter[0] > MAX_CRITERIA:
        raise InvalidScenarioError(
            f"A Scenario may contain at most {MAX_CRITERIA} criteria.",
            details={"criterion_count": counter[0], "maximum": MAX_CRITERIA},
        )
    doc["episode_policy"] = _normalize_episode_policy(doc.get("episode_policy"))
    eligibility = doc.get("eligibility_policy")
    if eligibility is not None and not isinstance(eligibility, Mapping):
        raise InvalidScenarioError("eligibility_policy must be an object.")
    activity = _optional_text((eligibility or {}).get("activity")) or "require_active"
    if activity not in {"require_active", "ignore"}:
        raise InvalidScenarioError("eligibility_policy.activity is not supported.", details={"activity": activity})
    doc["eligibility_policy"] = {"activity": activity}

    provenance = dict(doc.get("provenance")) if isinstance(doc.get("provenance"), Mapping) else {}
    old_provenance = previous.get("provenance") if isinstance(previous, Mapping) else None
    if isinstance(old_provenance, Mapping):
        provenance.setdefault("created_at", old_provenance.get("created_at"))
        provenance.setdefault("created_by", old_provenance.get("created_by"))
    if now is not None:
        provenance.setdefault("created_at", now)
        provenance.setdefault("created_by", "user")
        provenance["updated_at"] = now
    doc["provenance"] = provenance
    display_state = dict(doc.get("display_state")) if isinstance(doc.get("display_state"), Mapping) else {}
    display_state.setdefault("bodaqs_web_v1", {})
    doc["display_state"] = display_state
    return doc


def _normalize_predicate(value: Any, context: str, seen: set[str], counter: list[int]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidScenarioError(f"{context} must be an object.")
    op = _required_text(value.get("op"), f"{context}.op")
    if op in _GROUP_OPS:
        children = value.get("children")
        if not isinstance(children, list) or not children:
            raise InvalidScenarioError(f"{context}.children must be a non-empty list.")
        return {"op": op, "children": [_normalize_predicate(child, f"{context}.children[{i}]", seen, counter) for i, child in enumerate(children)]}
    if op not in _NUMERIC_OPS | _OTHER_OPS:
        raise InvalidScenarioError(f"{context}.op is not supported.", details={"op": op})
    criterion_id = _required_text(value.get("criterion_id"), f"{context}.criterion_id")
    if criterion_id in seen:
        raise InvalidScenarioError("criterion_id values must be unique.", details={"criterion_id": criterion_id})
    seen.add(criterion_id)
    counter[0] += 1
    series = value.get("series")
    if not isinstance(series, Mapping):
        raise InvalidScenarioError(f"{context}.series must be an object.")
    stream_name = _required_text(series.get("stream_name"), f"{context}.series.stream_name")
    has_column = _optional_text(series.get("column")) is not None
    has_selector = isinstance(series.get("selector"), Mapping) and bool(series.get("selector"))
    if has_column == has_selector:
        raise InvalidScenarioError(f"{context}.series must specify exactly one of column or selector.")
    normalized_series: dict[str, Any] = {"stream_name": stream_name}
    if has_column:
        normalized_series["column"] = _optional_text(series.get("column"))
    else:
        normalized_series["selector"] = dict(series["selector"])
    out: dict[str, Any] = {"criterion_id": criterion_id, "series": normalized_series, "op": op}
    if op in {"between", "outside"}:
        bounds = value.get("range")
        if not isinstance(bounds, Mapping):
            raise InvalidScenarioError(f"{context}.range must be an object.")
        lower = _finite_number(bounds.get("lower"), f"{context}.range.lower")
        upper = _finite_number(bounds.get("upper"), f"{context}.range.upper")
        if lower > upper:
            raise InvalidScenarioError(f"{context}.range.lower must be <= range.upper.")
        out["range"] = {"lower": lower, "upper": upper, "include_lower": bool(bounds.get("include_lower", True)), "include_upper": bool(bounds.get("include_upper", True))}
    elif op != "present":
        if "value" not in value:
            raise InvalidScenarioError(f"{context}.value is required.")
        out["value"] = value.get("value") if op in {"eq", "in"} else _finite_number(value.get("value"), f"{context}.value")
        if op == "in" and not isinstance(out["value"], list):
            raise InvalidScenarioError(f"{context}.value must be a list for 'in'.")
    return out


def _normalize_episode_policy(value: Any) -> dict[str, float | None]:
    if value is not None and not isinstance(value, Mapping):
        raise InvalidScenarioError("episode_policy must be an object.")
    source = value or {}
    out: dict[str, float | None] = {}
    defaults = {"minimum_duration_s": 0.0, "minimum_distance_m": None, "bridge_gap_s": 0.0, "bridge_gap_m": None}
    for field, default in defaults.items():
        raw = source.get(field, default)
        if raw is None:
            out[field] = None
            continue
        number = _finite_number(raw, f"episode_policy.{field}")
        if number < 0:
            raise InvalidScenarioError(f"episode_policy.{field} must be non-negative.")
        out[field] = number
    return out


def _scenarios_dir(root: str | Path) -> Path:
    return Path(root) / SCENARIOS_DIR


def _scenario_path(root: str | Path, scenario_id: str) -> Path:
    if not is_valid_object_id(str(scenario_id)):
        raise InvalidScenarioError("Scenario id is not filename-safe.", details={"scenario_id": scenario_id})
    return _scenarios_dir(root) / f"{scenario_id}.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScenarioNotFoundError(details={"scenario_id": path.stem}) from exc
    except Exception as exc:
        raise InvalidScenarioError("Scenario JSON could not be read.", details={"path": str(path)}) from exc
    if not isinstance(value, Mapping):
        raise InvalidScenarioError("Scenario JSON must be an object.")
    return dict(value)


def _write(root: str | Path, payload: Mapping[str, Any]) -> None:
    directory = _scenarios_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = _scenario_path(root, str(payload["scenario_id"]))
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidScenarioError(f"Scenario missing non-empty {field!r}.")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _finite_number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidScenarioError(f"{field} must be a finite number.") from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise InvalidScenarioError(f"{field} must be a finite number.")
    return result


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
