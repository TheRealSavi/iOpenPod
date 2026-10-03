"""Release authentication, freshness, target selection, and publisher identity."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from iOpenPod.app.updates.releases import (
    REPOSITORY,
    SIGNING_CONTEXT,
    ReleaseFloor,
    verify_release,
    version_tuple,
)

NOW = datetime.now(UTC)


def signed_release(**overrides: object) -> tuple[bytes, tuple[str, ...]]:
    key = ECC.generate(curve="Ed25519")
    public = key.public_key().export_key(format="raw")
    value: dict[str, object] = {
        "schema": 1,
        "product": "iOpenPod",
        "repository": REPOSITORY,
        "track": "stable",
        "version": "2.0.2",
        "tag": "v2.0.2",
        "sequence": 42,
        "issued": NOW.isoformat(),
        "expires": (NOW + timedelta(days=30)).isoformat(),
        "assets": [
            {
                "target": "windows-x86_64",
                "layout": "windows-onefile-v1",
                "updater_protocol": 1,
                "size": 12,
                "sha256": "a" * 64,
                "executable_sha256": "b" * 64,
                "minimum_os": "10.0",
            }
        ],
    }
    value.update(overrides)
    payload = json.dumps(value).encode()
    signature = eddsa.new(key, "rfc8032").sign(SIGNING_CONTEXT + payload)
    envelope = json.dumps(
        {
            "payload": base64.b64encode(payload).decode(),
            "signatures": [
                {
                    "key_id": hashlib.sha256(public).hexdigest(),
                    "signature": base64.b64encode(signature).decode(),
                }
            ],
        }
    ).encode()
    return envelope, (base64.b64encode(public).decode(),)


def test_authenticates_exact_release_and_derives_download_destination() -> None:
    data, keys = signed_release()
    release = verify_release(data, keys, now=NOW)
    asset = release.asset("windows-x86_64")
    assert (
        asset.url
        == "https://github.com/TheRealSavi/iOpenPod/releases/download/v2.0.2/iOpenPod-2.0.2-Windows-AMD64.zip"
    )
    assert asset.executable_sha256 == "b" * 64
    with pytest.raises(ValueError, match="no supported download"):
        release.asset("linux-x86_64")


def test_rejects_tampering_and_unknown_signer() -> None:
    data, keys = signed_release()
    envelope = json.loads(data)
    payload = base64.b64decode(envelope["payload"]).replace(b"2.0.2", b"2.0.9")
    envelope["payload"] = base64.b64encode(payload).decode()
    with pytest.raises(ValueError, match="not signed"):
        verify_release(json.dumps(envelope).encode(), keys, now=NOW)
    with pytest.raises(ValueError, match="not signed"):
        verify_release(data, (), now=NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"tag": "BETA"},
        {"version": "BETA"},
        {"repository": "someone/else"},
        {"expires": NOW.isoformat()},
        {"issued": (NOW + timedelta(days=1)).isoformat()},
        {"expires": (NOW + timedelta(days=91)).isoformat()},
        {"sequence": True},
        {"issued": "2026-10-03T00:00:00"},
        {"track": "nightly"},
        {"assets": []},
    ],
)
def test_rejects_signed_but_unsupported_or_stale_metadata(
    overrides: dict[str, object],
) -> None:
    data, keys = signed_release(**overrides)
    with pytest.raises(ValueError):
        verify_release(data, keys, now=NOW)


def test_retained_evidence_rejects_rollback_and_same_sequence_substitution() -> None:
    data, keys = signed_release()
    current = verify_release(data, keys, now=NOW)
    floor = ReleaseFloor(current.sequence, current.version, current.digest)
    assert verify_release(data, keys, now=NOW, floor=floor) == current
    for other in (
        ReleaseFloor(43, "2.0.2", ""),
        ReleaseFloor(41, "2.0.3", ""),
        ReleaseFloor(42, "2.0.2", "changed"),
    ):
        with pytest.raises(ValueError):
            verify_release(data, keys, now=NOW, floor=other)


@pytest.mark.parametrize(
    "version", ["BETA", "2.0", "2.00.1", "2.0.1rc1", "65536.0.0", "../../2.0.1"]
)
def test_versions_cannot_be_used_as_arbitrary_paths(version: str) -> None:
    with pytest.raises(ValueError):
        version_tuple(version)
