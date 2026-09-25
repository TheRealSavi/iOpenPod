from pathlib import Path


def test_pyinstaller_spec_bundles_packaged_libusb_library() -> None:
    spec = (Path(__file__).parents[1] / "iOpenPod.spec").read_text(encoding="utf-8")

    assert "libusb_package.get_library_path()" in spec
    assert "(str(_libusb_path), 'libusb_package')" in spec
    assert "*_libusb_binaries" in spec
    assert "'libusb_package'" in spec
