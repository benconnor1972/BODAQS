"""Transient, bounded background searches over canonical Scenario evaluations."""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from typing import Any, Mapping

from starlette.concurrency import run_in_threadpool

from bodaqs_analysis.library_api.errors import InvalidRequestError, LibraryApiError
from bodaqs_analysis.library_api.scenario_evaluation import _session_ref


def prepare_search(adapter: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    reference = payload.get("scenario_ref")
    if not isinstance(reference, Mapping):
        raise InvalidRequestError("scenario_ref is required.")
    scenario = adapter.load_scenario(str(reference.get("scenario_id") or ""))
    revision = reference.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision != scenario["revision"]:
        raise InvalidRequestError("Scenario revision has changed; reload before searching.")
    minimum = payload.get("minimum_total_duration_s", 0)
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum) or minimum < 0:
        raise InvalidRequestError("Minimum total duration must be a finite non-negative number.")
    raw = payload.get("sessions")
    if not isinstance(raw, list) or not raw or len(raw) > 10_000:
        raise InvalidRequestError("Search requires between 1 and 10,000 candidate sessions.")
    refs = [_session_ref(item) for item in raw]
    for ref in refs:
        if any(ref[key] in {".", ".."} or any(char in ref[key] for char in "/\\:") for key in ("run_id", "session_id")):
            raise InvalidRequestError("Run and session identifiers must be directory names.")
    refs = list({ref["session_ref_id"]: ref for ref in refs}.values())
    for library_id in {ref["library_id"] for ref in refs}:
        adapter._library_root(library_id)
    return {
        "schema": "bodaqs.scenario_session_query",
        "version": 1,
        "query_id": uuid.uuid4().hex,
        "status": "queued",
        "scenario": scenario,
        "minimum_total_duration_s": float(minimum),
        "candidates": refs,
        "candidate_session_count": len(refs),
        "processed_session_count": 0,
        "matched_session_count": 0,
        "unavailable_session_count": 0,
        "partial_session_count": 0,
        "results": [],
        "error": None,
        "created_at": time.monotonic(),
    }


def public_search(job: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"scenario", "candidates", "results", "task", "created_at"}}


async def run_search(job: dict[str, Any], adapter: Any, semaphore: asyncio.Semaphore) -> None:
    try:
        for ref in job["candidates"]:
            if job["status"] == "cancelled":
                return
            async with semaphore:
                if job["status"] == "cancelled":
                    return
                job["status"] = "running"
                try:
                    response = await run_in_threadpool(adapter.evaluate_scenario, {
                        "scenario": job["scenario"], "sessions": [ref],
                        "options": {"include_criterion_diagnostics": False},
                    })
                    result = response["sessions"][0]
                except LibraryApiError:
                    result = {"status": "unavailable", "episode_count": 0, "matched_duration_s": 0}
            if job["status"] == "cancelled":
                return
            status = result["status"]
            # Incomplete evaluations are not evidence of a complete session match.
            if status == "partial":
                job["partial_session_count"] += 1
            elif status != "succeeded":
                job["unavailable_session_count"] += 1
            elif result["episode_count"] > 0 and result["matched_duration_s"] >= job["minimum_total_duration_s"]:
                job["results"].append({"session_ref": ref, "matched_duration_s": result["matched_duration_s"]})
                job["matched_session_count"] += 1
            job["processed_session_count"] += 1
        job["status"] = "completed"
    except Exception as exc:
        if job["status"] != "cancelled":
            job["status"] = "failed"
            job["error"] = str(exc)
