from pathlib import Path

import iopenpod.sync.sync_executor as sync_executor_module
from iopenpod.device.write_guard import DeviceBusyError


def test_write_guard_retries_a_short_lived_iopenpod_writer(monkeypatch) -> None:
    attempts: list[object] = []

    class FakeWriteGuard:
        def __init__(self, *_args, **_kwargs) -> None:
            attempts.append("created")

        def __enter__(self):
            if len(attempts) == 1:
                raise DeviceBusyError("busy")
            return self

        def __exit__(self, *_args) -> None:
            attempts.append("released")

    monkeypatch.setattr(sync_executor_module, "DeviceWriteGuard", FakeWriteGuard)
    monkeypatch.setattr(sync_executor_module.time, "sleep", lambda _seconds: None)

    with sync_executor_module._retrying_device_write_guard(
        Path("/ipod"),
        volume_key="test-device",
        expected_database_generation=None,
    ) as guard:
        assert isinstance(guard, FakeWriteGuard)

    assert attempts == ["created", "created", "released"]
