"""Exercise native memory and default storage paths against an installed Jayrun."""
from __future__ import annotations

import mmap
import os
from pathlib import Path
import platform
import sys
import tempfile
from unittest.mock import patch

import jayrun
from jayrun import ArtifactContext, ConfigContext, Engine
from jayrun.context import ContextState
from jayrun.engine.scheduler.memory import MemoryPressureMonitor
from jayrun.persistence import Database
from jayrun.placement import Device
from jayrun.settings import EngineSettings, RuntimeDevice


def check_admission(graph, source, scale, result, rss: int) -> None:
    # Windows can recover on the current working set. Darwin reports peak RSS.
    span = 64 * 1024 * 1024
    limit_gb = (rss + span // 3) / (0.75 * 1e9) if sys.platform == "win32" else 0.000001
    engine = Engine(EngineSettings(runtime_devices=RuntimeDevice(device=Device.CPU, memory_limit_gb=limit_gb)))
    engine.start()
    try:
        if sys.platform == "win32":
            with mmap.mmap(-1, span) as pages:
                for offset in range(0, span, mmap.PAGESIZE):
                    pages[offset] = 1
                assert engine.pressure.memory_pressured
                run = engine.submit(graph, ArtifactContext({source: 7}), ConfigContext({scale.factor: 3}))
                run.wait(ContextState.QUEUED, timeout=10)
                assert engine.pressure.queued_contexts == 1
            run.wait(timeout=15)
            assert run.state is ContextState.FINISHED and run.artifact(result).value == 21
            assert not engine.pressure.memory_pressured
        else:
            assert engine.pressure.memory_pressured
            run = engine.submit(graph, ArtifactContext({source: 7}), ConfigContext({scale.factor: 3}))
            run.wait(ContextState.QUEUED, timeout=10)
            assert engine.pressure.queued_contexts == 1
            run.abort()
            run.wait(timeout=10)
            assert run.state is ContextState.ABORTED
    finally:
        engine.shutdown(forced=True, timeout=10)
    assert not engine.cleanup_failures


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    assert sys.flags.isolated and not Path(jayrun.__file__).resolve().is_relative_to(root)
    assert sys.platform == {"Windows": "win32", "macOS": "darwin"}[os.environ["RUNNER_OS"]]
    sys.path.insert(0, str(root / "docs" / "_examples"))
    from first_graph import build_graph

    graph, source, result, scale = build_graph()
    monitor = MemoryPressureMonitor(None)
    rss = monitor._process_usage()
    total, available = monitor._system_memory()
    print(f"{platform.platform()} {platform.machine()}, Python {platform.python_version()}, "
          f"RSS={rss}, total={total}, available={available}", flush=True)
    assert rss is not None and rss > 1000
    if sys.platform == "win32":
        assert total is not None and total > 0 and available is not None and 0 <= available <= total
    check_admission(graph, source, scale, result, rss)

    with tempfile.TemporaryDirectory(prefix="jayrun native ") as folder:
        home = Path(folder)
        with patch.dict(os.environ, {"LOCALAPPDATA": folder, "HOME": folder}):
            if sys.platform == "win32":
                for key in ("USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
                    os.environ.pop(key, None)
                expected = home / "Jayrun" / "history.sqlite3"
            else:
                expected = home / "Library" / "Application Support" / "Jayrun" / "history.sqlite3"
            database = Database()
        assert database.path == expected and not expected.exists()
        with Engine(database=database) as engine:
            run = engine.submit(graph, ArtifactContext({source: 7}), ConfigContext({scale.factor: 3}))
            run.wait(timeout=15)
            assert run.state is ContextState.FINISHED and run.artifact(result).value == 21
            database.flush(timeout=10)
        assert not engine.cleanup_failures
        with Database(expected) as reader:
            history = reader.query_contexts().items
            assert len(history) == 1 and history[0].outcome == "finished"
    print("PASS native pressure, queued admission, execution, shutdown and SQLite reopen")


if __name__ == "__main__":
    main()
