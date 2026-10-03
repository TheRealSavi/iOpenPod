"""Identify packaging evidence without contacting a store or assuming an origin."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from iOpenPod.app.updates import platform, windows
from iOpenPod.app.updates.backend import InstallChannel, UpdateProvider


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("host", ["win32", "linux", "darwin"])
def test_unmanaged_install_distinguishes_python_and_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frozen: bool, host: str
) -> None:
    def create_store_provider(_window: int) -> UpdateProvider:
        return UpdateProvider(InstallChannel.UNPACKAGED)

    bundle = SimpleNamespace(appStoreReceiptURL=lambda: None)

    def import_foundation(_name: str) -> SimpleNamespace:
        return SimpleNamespace(NSBundle=SimpleNamespace(mainBundle=lambda: bundle))

    monkeypatch.setattr(sys, "platform", host)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(platform, "_runtime_error", "")
    monkeypatch.setattr(platform, "_FLATPAK_INFO", tmp_path / "missing")
    monkeypatch.delenv("SNAP_NAME", raising=False)
    monkeypatch.setattr(
        windows,
        "create_store_provider",
        create_store_provider,
    )
    monkeypatch.setattr(platform, "import_module", import_foundation)
    provider = platform.create_update_provider(1)
    assert provider.channel is (
        InstallChannel.FROZEN if frozen else InstallChannel.SOURCE
    )
    assert provider.backend is None


@pytest.mark.parametrize(
    ("app_id", "snap", "expected"),
    [
        ("io.github.therealsavi.iOpenPod", "", InstallChannel.FLATPAK),
        ("org.other.App", "", InstallChannel.FROZEN),
        ("", "iopenpod", InstallChannel.SNAP),
        ("", "other-app", InstallChannel.FROZEN),
    ],
)
def test_linux_uses_own_package_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    app_id: str,
    snap: str,
    expected: InstallChannel,
) -> None:
    metadata = tmp_path / "flatpak-info"
    metadata.write_text(f"[Application]\nname={app_id}\n", encoding="utf-8")
    monkeypatch.setattr(platform, "_FLATPAK_INFO", metadata)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("SNAP_NAME", snap)
    monkeypatch.setenv("SNAP", "/snap/iopenpod/current")
    provider = platform.create_update_provider(1)
    assert provider.channel is expected
    assert provider.backend is None


@pytest.mark.parametrize(
    ("filename", "exists", "expected"),
    [
        ("receipt", True, InstallChannel.MAC_APP_STORE),
        ("sandboxReceipt", True, InstallChannel.APP_STORE_TEST),
        ("receipt", False, InstallChannel.FROZEN),
    ],
)
def test_mac_receipt_is_display_evidence_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    filename: str,
    exists: bool,
    expected: InstallChannel,
) -> None:
    receipt = tmp_path / filename
    if exists:
        receipt.write_bytes(b"receipt fixture, not license validation")
    bundle = SimpleNamespace(
        appStoreReceiptURL=lambda: SimpleNamespace(path=lambda: str(receipt))
    )

    def import_foundation(_name: str) -> SimpleNamespace:
        return SimpleNamespace(NSBundle=SimpleNamespace(mainBundle=lambda: bundle))

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(platform, "import_module", import_foundation)
    provider = platform.create_update_provider(1)
    assert provider.channel is expected
    assert provider.backend is None
