import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from bodaqs_analysis.library_api import LibraryAdapter
from bodaqs_analysis.library_api.cache import CacheBuildLocks, PersistentJsonCache
from bodaqs_analysis.library_api_service import create_app
from bodaqs_analysis.library_api_service.cache_warming import IdleCacheWarmer
from test_scenario_api import _library, _scenario


def test_warming_builds_disk_evaluation_reused_with_and_without_diagnostics(tmp_path, monkeypatch):
    import bodaqs_analysis.library_api.adapter as module
    root, _, ref = _library(tmp_path)
    adapter = LibraryAdapter(root)
    saved = adapter.create_scenario(_scenario())
    adapter.get_catalog(ref["library_id"])
    task = next(task for task in adapter.cache_warming_tasks() if task["kind"] == "scenario")
    assert adapter.warm_cache_task(task) == "built"
    assert adapter.warm_cache_task(task) == "cached"
    assert adapter._cache.stats()["entry_count"] == 0
    monkeypatch.setattr(module, "evaluate_scenario", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Unexpected cold evaluation")))
    for diagnostics in [False, True]:
        result = adapter.evaluate_scenario({"scenario_ref": {"scenario_id": saved["scenario_id"], "revision": 1}, "sessions": [ref], "options": {"include_criterion_diagnostics": diagnostics}})
        assert result["sessions"][0]["episode_count"] > 0
        assert bool(result["sessions"][0]["criteria"]) is diagnostics


def test_warming_observes_import_lock_read_only_budget_and_obsolete_definition(tmp_path, monkeypatch):
    from bodaqs_analysis.artifacts import ArtifactStore
    root, library, ref = _library(tmp_path)
    adapter = LibraryAdapter(root)
    adapter.create_scenario(_scenario())
    adapter.get_catalog(ref["library_id"])
    tasks = adapter.cache_warming_tasks()
    activity = next(task for task in tasks if task["kind"] == "activity")
    lock = ArtifactStore(library).path_library_dir() / "import_agent.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("locked")
    assert adapter.warm_cache_task(activity) == "importing"
    lock.unlink()
    monkeypatch.setattr(adapter, "_ACTIVITY_INDEX_PERSISTENT_CACHE_MAX_ENTRIES", 0)
    assert adapter.warm_cache_task(activity) == "budget"
    adapter.write_catalog_revision = False
    assert adapter.warm_cache_task(activity) == "disabled"
    adapter.write_catalog_revision = True
    scenario_task = next(task for task in tasks if task["kind"] == "scenario")
    adapter.update_scenario("fast-riding", expected_revision=1, payload=_scenario())
    assert adapter.warm_cache_task(scenario_task) == "obsolete"


def test_worker_yields_to_foreground_before_starting_next_unit():
    entered = threading.Event()
    release = threading.Event()
    served = threading.Event()
    hold_foreground = threading.Event()
    class Adapter:
        calls = 0
        def cache_warming_tasks(self):
            return [{"kind": "activity"}, {"kind": "scenario"}]
        def warm_cache_task(self, _):
            self.calls += 1
            entered.set()
            assert release.wait(5)
            return "built"
    adapter = Adapter()
    worker = IdleCacheWarmer(lambda: adapter, idle_seconds=0)
    warm = threading.Thread(target=worker.run_one)
    warm.start()
    assert entered.wait(5)
    def foreground():
        with worker.foreground_sync():
            served.set()
            assert hold_foreground.wait(5)
    front = threading.Thread(target=foreground)
    front.start()
    with worker._condition:
        worker._condition.wait_for(lambda: worker._foreground == 1, timeout=5)
    assert not worker.run_one()
    assert not served.is_set()
    release.set()
    warm.join(5)
    assert served.wait(5)
    assert not worker.run_one()
    hold_foreground.set()
    front.join(5)
    assert worker.run_one()
    assert adapter.calls == 2


def test_worker_pause_read_only_and_idle_grace():
    class Adapter:
        def cache_warming_tasks(self):
            return [{"kind": "activity"}]
        def warm_cache_task(self, _):
            return "built"
    adapter = Adapter()
    worker = IdleCacheWarmer(lambda: adapter, idle_seconds=100)
    assert not worker.run_one()
    worker.idle_seconds = 0
    worker.set_enabled(False)
    assert not worker.run_one()
    worker.set_enabled(True)
    assert worker.run_one()
    readonly = IdleCacheWarmer(lambda: adapter, read_only=True, idle_seconds=0)
    readonly.set_enabled(True)
    assert not readonly.run_one()


def test_cancelled_foreground_wait_releases_priority_accounting():
    worker = IdleCacheWarmer(lambda: None)
    worker._running = True
    async def exercise():
        async def request():
            async with worker.foreground():
                raise AssertionError("Not yet ready")
        task = asyncio.create_task(request())
        await asyncio.sleep(0)
        assert worker.status()["foreground_count"] == 1
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert worker.status()["foreground_count"] == 0
    asyncio.run(exercise())


def test_warming_api_pause_and_read_only(tmp_path):
    root, _, _ = _library(tmp_path)
    with TestClient(create_app(root)) as client:
        assert client.get("/api/v1/cache/warming").json()["enabled"]
        assert not client.post("/api/v1/cache/warming", json={"enabled": False}).json()["enabled"]
        assert client.post("/api/v1/cache/warming", json={"enabled": "yes"}).status_code == 400
    with TestClient(create_app(root, read_only=True)) as client:
        assert not client.get("/api/v1/cache/warming").json()["enabled"]
        assert client.post("/api/v1/cache/warming", json={"enabled": True}).status_code == 403


def test_activity_and_preview_warming_reuse_existing_builders(tmp_path, monkeypatch):
    import bodaqs_analysis.library_api.adapter as module
    root, _, ref = _library(tmp_path)
    adapter = LibraryAdapter(root)
    activity = {"kind": "activity", "ref": ref}
    assert adapter.warm_cache_task(activity) == "built"
    assert adapter.warm_cache_task(activity) == "cached"
    request = {"session": ref, "signals": [{"column": "gps_speed_mps"}],
               "window": {"start_s": 0, "end_s": 5}, "resolution": {"target_points": 900},
               "include_events": False, "include_marks": False}
    preview = {"kind": "preview", "ref": ref, "request": request}
    assert adapter.warm_cache_task(preview) == "built"
    monkeypatch.setattr(module, "build_timeseries_window", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Unexpected preview rebuild")))
    foreground_request = {**request, "session": {**ref, "label": "User-visible label", "session_ref_id": "display identity"}}
    assert adapter.get_timeseries_window(ref["library_id"], foreground_request)["signals"]


def test_planner_is_bounded_and_favors_recent_use(tmp_path):
    root, _, _ = _library(tmp_path)
    adapter = LibraryAdapter(root)
    saved = adapter.create_scenario(_scenario())
    adapter._catalog_cache["default-library"] = {"rows": [
        {"run_id": "run", "session_id": str(i), "session_key": f"run::{i}", "timestamps": {"imported_at": str(i).zfill(3)}} for i in range(50)
    ]}
    adapter._session_usage["default-library:run::1"] = 100
    tasks = adapter.cache_warming_tasks()
    assert tasks[0]["ref"]["session_key"] == "run::1"
    assert len({task["ref"]["session_key"] for task in tasks}) == 16
    assert any(task.get("scenario", {}).get("scenario_id") == saved["scenario_id"] for task in tasks)


def test_cache_build_locks_coalesce_lookup_and_release_entries():
    locks = CacheBuildLocks()
    values = {}
    built = []
    def request(_):
        with locks.hold("test", "key"):
            if "key" not in values:
                built.append(1)
                values["key"] = 42
            return values["key"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(request, range(32))) == [42] * 32
    assert len(built) == 1
    assert not locks._locks


def test_persistent_cache_concurrent_writes_use_distinct_temporary_files(tmp_path):
    cache = PersistentJsonCache(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: cache.set("test", "key", {"index": index}, ttl_s=None), range(20)))
    assert cache.get("test", "key").value["index"] in range(20)
    assert not list(tmp_path.rglob("*.tmp"))
