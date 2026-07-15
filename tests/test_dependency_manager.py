import shutil
import zipfile
from pathlib import Path

from iopenpod.sync import dependency_manager as deps


def _write_zip(path: Path, names: tuple[str, ...]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(f"pkg/bin/{name}", name)


def test_download_ffmpeg_extracts_ffprobe_from_shared_archive(tmp_path, monkeypatch) -> None:
    archive = tmp_path / "ffmpeg.zip"
    _write_zip(archive, ("ffmpeg", "ffprobe"))
    bin_dir = tmp_path / "bin"

    monkeypatch.setattr(deps, "_platform_key", lambda: "linux-x86_64")
    monkeypatch.setitem(deps._FFMPEG_URLS, "linux-x86_64", "https://example.test/ffmpeg.zip")
    monkeypatch.setitem(deps._FFPROBE_URLS, "linux-x86_64", "https://example.test/ffmpeg.zip")
    monkeypatch.setattr(deps, "get_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(deps, "_download", lambda _url, dest, _progress_callback=None: shutil.copyfile(archive, dest) or True)

    result = deps.download_ffmpeg()

    assert result == str(bin_dir / "ffmpeg")
    assert (bin_dir / "ffmpeg").exists()
    assert (bin_dir / "ffprobe").exists()


def test_download_ffmpeg_downloads_separate_ffprobe_archive(tmp_path, monkeypatch) -> None:
    ffmpeg_archive = tmp_path / "ffmpeg.zip"
    ffprobe_archive = tmp_path / "ffprobe.zip"
    _write_zip(ffmpeg_archive, ("ffmpeg",))
    _write_zip(ffprobe_archive, ("ffprobe",))
    bin_dir = tmp_path / "bin"

    monkeypatch.setattr(deps, "_platform_key", lambda: "darwin-arm64")
    monkeypatch.setitem(deps._FFMPEG_URLS, "darwin-arm64", "https://example.test/ffmpeg.zip")
    monkeypatch.setitem(deps._FFPROBE_URLS, "darwin-arm64", "https://example.test/ffprobe.zip")
    monkeypatch.setattr(deps, "get_bin_dir", lambda: bin_dir)

    def fake_download(url: str, dest: Path, _progress_callback=None) -> bool:
        source = ffprobe_archive if url.endswith("ffprobe.zip") else ffmpeg_archive
        shutil.copyfile(source, dest)
        return True

    monkeypatch.setattr(deps, "_download", fake_download)

    result = deps.download_ffmpeg()

    assert result == str(bin_dir / "ffmpeg")
    assert (bin_dir / "ffmpeg").exists()
    assert (bin_dir / "ffprobe").exists()
