"""Optional failures must retain measured acoustic analysis and honest provenance."""

import struct
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal, Protocol, cast

import pytest
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA
from tests.iOpenPod.app.test_phase_evidence import music_with_energy_change

from iOpenPod.app import phase_analysis
from iOpenPod.app.phase_analysis import PhaseAnalysisService
from iOpenPod.app.phase_audio import analyze_phase_pcm
from iOpenPod.app.phase_parts import PhasePart
from iPodDB.games import PhaseBeat, PhaseChart, PhaseTransient, phase
from storage import FilesystemSession, HostPath, Storage, VolumeDisconnectedError
from storage.testing import VirtualStoragePlatform


@pytest.fixture
def session(tmp_path: Path) -> Iterator[FilesystemSession]:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(storage.discover().volumes[0]) as result:
        yield result


class Decoder:
    def decode(self, *_args: object, **_kwargs: object) -> bytes:
        return bytes(30 * 22_050 * 4)


class FailingSources:
    @property
    def identity(self) -> str:
        return "optional-model"

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def analyze(
        self, *_args: object, checkpoint: Callable[[], None], **_kwargs: object
    ) -> tuple[PhasePart, ...]:
        self.calls += 1
        checkpoint()
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        ImportError("missing"),
        OSError("offline"),
        RuntimeError("model failed"),
        MemoryError("full"),
    ],
)
def test_provider_failure_uses_acoustic_analysis_for_the_rest_of_the_run(
    session: FilesystemSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    provider = FailingSources(error)
    measured: list[tuple[PhasePart, ...]] = []

    def acoustic(
        _pcm: bytes, *, parts: tuple[PhasePart, ...], **_kwargs: object
    ) -> PhaseChart:
        measured.append(parts)
        return PhaseChart()

    monkeypatch.setattr(phase_analysis, "analyze_phase_pcm", acoustic)
    original = PhaseAnalysisService(decoder=Decoder(), source_analyzer=provider)
    service = original.for_analysis()
    for _ in range(2):
        assert service.analyze(
            HostPath(tmp_path / "music.wav"),
            input_suffix=".wav",
            length_ms=30_000,
            session=session,
            checkpoint=lambda: None,
        ).startswith(b"pha\x02")
    assert provider.calls == 1
    assert measured == [(), ()]
    assert service.identity.endswith(":acoustic:mono")
    assert "optional-model" in original.identity


@pytest.mark.parametrize(
    "error", [RuntimeError("cancelled"), VolumeDisconnectedError("disconnected")]
)
def test_checkpoint_failures_are_never_optional_fallbacks(
    session: FilesystemSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def fail_analysis(*_args: object, **_kwargs: object) -> PhaseChart:
        pytest.fail("Cancellation or disconnection entered acoustic fallback")

    def checkpoint() -> None:
        raise error

    monkeypatch.setattr(phase_analysis, "analyze_phase_pcm", fail_analysis)
    service = PhaseAnalysisService(
        decoder=Decoder(), source_analyzer=FailingSources(OSError("model"))
    )
    with pytest.raises(type(error), match=str(error)):
        service.analyze(
            HostPath(tmp_path / "music.wav"),
            input_suffix=".wav",
            length_ms=30_000,
            session=session,
            checkpoint=checkpoint,
        )


def test_unimportable_optional_identity_uses_acoustic_identity() -> None:
    class BrokenIdentity(FailingSources):
        @property
        def identity(self) -> str:
            raise ImportError("Incompatible Torch library")

    service = PhaseAnalysisService(
        decoder=Decoder(), source_analyzer=BrokenIdentity(OSError())
    )
    assert service.identity.endswith(":acoustic:mono")


class _EcbCipher(Protocol):
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class _EcbFactory(Protocol):
    def __call__(self, key: bytes, mode: Literal[1]) -> _EcbCipher: ...


def test_real_acoustic_fallback_encodes_complete_native_parameter_evidence(
    session: FilesystemSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcm = music_with_energy_change()

    class AudioDecoder(Decoder):
        def decode(self, *_args: object, **_kwargs: object) -> bytes:
            return pcm

    key = RSA.generate(1024)
    monkeypatch.setattr(phase, "_PUBLIC_KEY", key.public_key().export_key(format="DER"))
    service = PhaseAnalysisService(
        decoder=AudioDecoder(),
        source_analyzer=FailingSources(OSError("model unavailable")),
    ).for_analysis()
    data = service.analyze(
        HostPath(tmp_path / "music.wav"),
        input_suffix=".wav",
        length_ms=30_000,
        session=session,
        checkpoint=lambda: None,
    )
    # Independently decrypt and read the native wire fields, rather than replacing
    # the acoustic DSP or codec with a double. This detects a placeholder fallback,
    # lost spectral evidence, swapped beat nibbles, and altered Q16.16 timing.
    wrapped_size = struct.unpack_from("<H", data, 8)[0]
    secret = PKCS1_OAEP.new(key, hashAlgo=SHA1).decrypt(data[10 : 10 + wrapped_size])
    new_ecb = cast("_EcbFactory", AES.new)  # pyright: ignore[reportUnknownMemberType]
    plain = new_ecb(secret, AES.MODE_ECB).decrypt(data[10 + wrapped_size :])
    assert plain[:8] == b"head\x10\0\0\0"
    cursor = 24
    assert plain[cursor : cursor + 4] == b"tran"
    size, count = struct.unpack_from("<II", plain, cursor + 4)
    transients: list[PhaseTransient] = []
    for index in range(count):
        marker, time, magnitudes = struct.unpack_from(
            "<BIH", plain, cursor + 12 + 7 * index
        )
        assert marker == 255
        transients.append(
            PhaseTransient(
                time, magnitudes & 31, (magnitudes >> 5) & 31, (magnitudes >> 10) & 31
            )
        )
    cursor += 8 + size
    assert plain[cursor : cursor + 4] == b"beat"
    _, count = struct.unpack_from("<II", plain, cursor + 4)
    beats: list[PhaseBeat] = []
    for index in range(count):
        marker, time, fields = struct.unpack_from(
            "<BIB", plain, cursor + 12 + 6 * index
        )
        assert marker == 255
        beats.append(PhaseBeat(time, fields >> 4, fields & 15))
    reference = analyze_phase_pcm(pcm, length_ms=30_000)
    assert reference.transients and reference.beats
    assert PhaseChart(tuple(transients), tuple(beats)) == reference
    assert service.identity.endswith(":acoustic:mono")
