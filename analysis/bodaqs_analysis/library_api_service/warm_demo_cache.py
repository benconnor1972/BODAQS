"""Warm shared Library API caches after deploying a hosted demo.

This module intentionally uses only the public read APIs.  It can therefore run
against the read-only hosted service and is safe to repeat after every deploy.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_BASE_URL = "http://127.0.0.1:8765"


class ApiRequestError(RuntimeError):
    """Raised when the hosted Library API rejects a warmup request."""


@dataclass
class WarmupSummary:
    catalog_count: int = 0
    study_set_count: int = 0
    session_count: int = 0
    adequacy_count: int = 0
    failures: list[str] = field(default_factory=list)


class LibraryApiClient:
    def __init__(self, base_url: str, *, timeout_s: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiRequestError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ApiRequestError(f"{method} {path} could not reach the API: {exc.reason}") from exc


def _records(value: Any) -> list[dict[str, Any]]:
    """Accept the API's list response and PowerShell-style wrapped list shape."""

    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and isinstance(value.get("value"), list):
        return [item for item in value["value"] if isinstance(item, dict)]
    return []


def _session_ref(row: dict[str, Any]) -> dict[str, str]:
    display = row.get("display") if isinstance(row.get("display"), dict) else {}
    label = str(display.get("label") or row.get("session_id") or row.get("session_key") or "session")
    return {
        "library_id": str(row["library_id"]),
        "run_id": str(row["run_id"]),
        "session_id": str(row["session_id"]),
        "session_key": str(row["session_key"]),
        "session_ref_id": str(row.get("session_ref_id") or ""),
        "label": label,
    }


def _view_ids(views: Iterable[dict[str, Any]]) -> list[str]:
    return [str(view["view_id"]) for view in views if str(view.get("view_id") or "").strip()]


def warm_hosted_demo(
    client: LibraryApiClient,
    *,
    study_set_ids: set[str] | None = None,
    include_individual_sessions: bool = True,
    session_limit: int | None = None,
    verbose: bool = False,
) -> WarmupSummary:
    """Warm catalog and adequacy entries for all selected demo scopes."""

    summary = WarmupSummary()
    health = client.get("/api/v1/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise ApiRequestError("Library API health endpoint did not report status=ok.")

    views = _records(client.get("/api/v1/analysis-views"))
    view_ids = _view_ids(views)
    if not view_ids:
        raise ApiRequestError("The Library API returned no analysis views to warm.")

    libraries = _records(client.get("/api/v1/libraries"))
    session_refs: list[dict[str, str]] = []
    for library in libraries:
        library_id = str(library.get("library_id") or "").strip()
        if not library_id:
            continue
        catalog = client.get(f"/api/v1/libraries/{library_id}/catalog")
        rows = catalog.get("rows", []) if isinstance(catalog, dict) else []
        if not isinstance(rows, list):
            rows = []
        summary.catalog_count += 1
        session_refs.extend(_session_ref(row) for row in rows if isinstance(row, dict))
        if verbose:
            print(f"Warmed catalog: {library_id} ({len(rows)} session(s))")

    study_set_summaries = _records(client.get("/api/v1/study-sets"))
    for study_set_summary in study_set_summaries:
        study_set_id = str(study_set_summary.get("study_set_id") or "").strip()
        if not study_set_id or (study_set_ids is not None and study_set_id not in study_set_ids):
            continue
        try:
            study_set = client.get(f"/api/v1/study-sets/{study_set_id}")
            if not isinstance(study_set, dict):
                raise ApiRequestError("Study set response was not an object.")
            for view_id in view_ids:
                client.post(
                    f"/api/v1/analysis-views/{view_id}/adequacy",
                    {"study_set_id": study_set_id, "study_set": study_set},
                )
                summary.adequacy_count += 1
            summary.study_set_count += 1
            if verbose:
                print(f"Warmed study set: {study_set_id} ({len(view_ids)} analysis view(s))")
        except ApiRequestError as exc:
            summary.failures.append(f"Study set {study_set_id}: {exc}")

    if include_individual_sessions:
        if session_limit is not None:
            session_refs = session_refs[:session_limit]
        for session_ref in session_refs:
            ref_label = session_ref["session_ref_id"] or session_ref["session_key"]
            try:
                for view_id in view_ids:
                    client.post(
                        f"/api/v1/analysis-views/{view_id}/adequacy",
                        {"sessions": [session_ref]},
                    )
                    summary.adequacy_count += 1
                summary.session_count += 1
                if verbose:
                    print(f"Warmed individual session: {ref_label} ({len(view_ids)} analysis view(s))")
            except ApiRequestError as exc:
                summary.failures.append(f"Session {ref_label}: {exc}")

    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Warm catalog and adequacy caches for a hosted BODAQS demo.")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL, help=f"Library API base URL (default: {DEFAULT_API_BASE_URL}).")
    parser.add_argument("--study-set-id", action="append", default=[], help="Warm only this saved study set. Repeat for more than one.")
    parser.add_argument("--skip-individual-sessions", action="store_true", help="Do not warm adequacy for each catalogued session.")
    parser.add_argument("--session-limit", type=int, help="Warm at most this many individual sessions (useful for a smoke test).")
    parser.add_argument("--timeout-s", type=float, default=30.0, help="Per-request timeout in seconds (default: 30).")
    parser.add_argument("--verbose", action="store_true", help="Print each warmed scope.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.session_limit is not None and args.session_limit < 0:
        print("--session-limit must be zero or greater.", file=sys.stderr)
        return 2

    client = LibraryApiClient(args.api_base_url, timeout_s=args.timeout_s)
    try:
        summary = warm_hosted_demo(
            client,
            study_set_ids=set(args.study_set_id) or None,
            include_individual_sessions=not args.skip_individual_sessions,
            session_limit=args.session_limit,
            verbose=args.verbose,
        )
    except ApiRequestError as exc:
        print(f"Cache warmup failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Cache warmup complete: "
        f"{summary.catalog_count} catalog(s), "
        f"{summary.study_set_count} study set(s), "
        f"{summary.session_count} individual session(s), "
        f"{summary.adequacy_count} adequacy request(s)."
    )
    if summary.failures:
        print(f"Completed with {len(summary.failures)} non-fatal failure(s):", file=sys.stderr)
        for failure in summary.failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
