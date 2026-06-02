import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from scripts.check_architecture import (
    count_except_exception_passes,
    count_runtime_singleton_access,
    detect_app_core_sync_executor_private_usage,
    detect_forbidden_runtime_private_access,
    detect_forbidden_settings_runtime_imports,
    detect_forbidden_sync_review_workers,
    detect_gui_forbidden_imports,
    detect_import_cycles,
    detect_legacy_settings_runtime_globals,
    detect_main_window_runtime_singleton_access,
    detect_sync_executor_private_usage,
)


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@contextmanager
def repo_temp_dir():
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / ".tmp" / f"architecture-test-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_count_except_exception_passes_ignores_other_handlers() -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "app_core" / "example.py",
            """
def ok():
    try:
        return 1
    except ValueError:
        return 2

def bad():
    try:
        return 1
    except Exception:
        pass
""",
        )

        counts = count_except_exception_passes(tmp_path)

        assert counts == {"app_core/example.py": 1}


def test_detect_gui_forbidden_imports_reports_cross_layer_edges() -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "GUI" / "view.py",
            """
from SyncEngine.sync_executor import SyncExecutor
from app_core.runtime import DeviceManager
import infrastructure.settings_runtime as settings
""",
        )

        violations = detect_gui_forbidden_imports(tmp_path)

        assert violations == {
            "GUI/view.py": [
                "SyncEngine.sync_executor",
                "infrastructure.settings_runtime",
            ]
        }


def test_detect_import_cycles_finds_first_party_cycle() -> None:
    with repo_temp_dir() as tmp_path:
        write_file(tmp_path / "app_core" / "a.py", "from app_core import b\n")
        write_file(tmp_path / "app_core" / "b.py", "from app_core import a\n")

        cycles = detect_import_cycles(tmp_path)

        assert cycles == [["app_core.a", "app_core.b"]]


def test_detect_forbidden_runtime_private_access_reports_runtime_state_reach_in(
) -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "GUI" / "view.py",
            """
def bad(cache):
    cache._user_playlists.clear()
""",
        )

        violations = detect_forbidden_runtime_private_access(tmp_path)

        assert violations == {"GUI/view.py": ["_user_playlists"]}


def test_detect_main_window_runtime_singleton_access_reports_get_instance(
) -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "GUI" / "app.py",
            """
from app_core.runtime import DeviceManager

def bad():
    return DeviceManager.get_instance()
""",
        )

        violations = detect_main_window_runtime_singleton_access(tmp_path)

        assert violations == ["DeviceManager.get_instance"]


def test_count_runtime_singleton_access_skips_app_core_and_counts_gui(
) -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "app_core" / "context.py",
            """
from app_core.runtime import DeviceManager

def allowed():
    return DeviceManager.get_instance()
""",
        )
        write_file(
            tmp_path / "GUI" / "view.py",
            """
from app_core.runtime import DeviceManager, iTunesDBCache

def bad():
    DeviceManager.get_instance()
    iTunesDBCache.get_instance()
    iTunesDBCache.get_instance()
""",
        )

        counts = count_runtime_singleton_access(tmp_path)

        assert counts == {
            "GUI/view.py": {
                "DeviceManager.get_instance": 1,
                "iTunesDBCache.get_instance": 2,
            }
        }


def test_detect_forbidden_settings_runtime_imports_allows_app_core_only(
) -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "app_core" / "context.py",
            "import infrastructure.settings_runtime as settings\n",
        )
        write_file(
            tmp_path / "infrastructure" / "settings_runtime.py",
            "def get_settings():\n    return object()\n",
        )
        write_file(
            tmp_path / "SyncEngine" / "executor.py",
            "from infrastructure.settings_runtime import get_settings\n",
        )

        violations = detect_forbidden_settings_runtime_imports(tmp_path)

        assert violations == {
            "SyncEngine/executor.py": ["infrastructure.settings_runtime"]
        }


def test_detect_legacy_settings_runtime_globals_reports_module_state(
) -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "infrastructure" / "settings_runtime.py",
            """
_global_instance = None
_effective_instance = None

class SettingsRuntime:
    def __init__(self):
        self._active_device_state = None
""",
        )

        violations = detect_legacy_settings_runtime_globals(tmp_path)

        assert violations == ["_effective_instance", "_global_instance"]


def test_detect_forbidden_sync_review_workers_reports_operational_workers(
) -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "GUI" / "widgets" / "syncReview.py",
            """
class SyncReviewWidget:
    pass

class SyncExecuteWorker:
    pass

class SyncWorker:
    pass

class BackSyncWorker:
    pass
""",
        )

        violations = detect_forbidden_sync_review_workers(tmp_path)

        assert violations == ["BackSyncWorker", "SyncExecuteWorker", "SyncWorker"]


def test_detect_app_core_sync_executor_private_usage_reports_reach_in(
) -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "app_core" / "jobs.py",
            """
from SyncEngine.sync_executor import SyncExecutor, _SyncContext

def bad(executor: SyncExecutor):
    executor._read_existing_database()
    executor._write_database([])
""",
        )

        violations = detect_app_core_sync_executor_private_usage(tmp_path)

        assert violations == {
            "app_core/jobs.py": [
                "_SyncContext",
                "_read_existing_database",
                "_write_database",
            ]
        }


def test_detect_sync_executor_private_usage_reports_all_layers(
) -> None:
    with repo_temp_dir() as tmp_path:
        write_file(
            tmp_path / "SyncEngine" / "sync_executor.py",
            """
class _SyncContext:
    pass

class SyncExecutor:
    def _write_database(self):
        pass
""",
        )
        write_file(
            tmp_path / "GUI" / "view.py",
            """
from SyncEngine.sync_executor import SyncExecutor, _SyncContext

def bad(executor: SyncExecutor):
    executor._write_database()
""",
        )

        violations = detect_sync_executor_private_usage(tmp_path)

        assert violations == {
            "GUI/view.py": ["_SyncContext", "_write_database"]
        }


def test_sync_contracts_do_not_import_diff_engine() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    contracts = repo_root / "SyncEngine" / "contracts.py"

    assert "fingerprint_diff_engine" not in contracts.read_text(encoding="utf-8")
