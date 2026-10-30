"""Synthetic native known answers; no captured license or firmware dependency."""

import pytest

from iPodDB.ic_info.aes import ecb_cipher
from iPodDB.ic_info.binding import (
    derive_device_key,
    rebind_value,
    unwrap_value,
    wrap_value,
)

_SESSION = bytes(range(16))
_VALUE = bytes(range(16, 32))
_ACCOUNT = 0x12345678
_VERSION = 0x10101


@pytest.mark.parametrize(
    ("guid", "kind", "expected"),
    [
        ("0001020304050607", 0, "6535f2ce6bfd5eec179670ee2c4ab55c"),
        ("0001020304050607", 1, "225194afdd8a8f10137e1757e1760f80"),
        ("08090a0b0c0d0e0f", 0, "09f7dbfa5d580907ccb8742050f3aaa8"),
        ("08090a0b0c0d0e0f", 1, "e87faeca37320fb68e4e8590cc4fa391"),
    ],
)
def test_synthetic_native_known_answers(guid: str, kind: int, expected: str) -> None:
    # Captured from unmodified Classic 120GB 2.0.1 native getter 0x08313514.
    # Lab scripts/standalone_binding_kat.py uses synthetic GUID/session/value
    # and account/key selectors; these expected bytes are not product outputs.
    identity = bytes.fromhex(guid)
    key = 0x10203040 + kind
    final = bytes.fromhex(expected)
    assert (
        unwrap_value(_VALUE, _SESSION, identity, _ACCOUNT, key, _VERSION, kind) == final
    )
    assert (
        wrap_value(final, _SESSION, identity, _ACCOUNT, key, _VERSION, kind) == _VALUE
    )


@pytest.mark.parametrize("kind", [0, 1])
def test_rebinding_preserves_final_key_and_same_guid_is_exact(kind: int) -> None:
    source = bytes(range(8))
    destination = bytes(range(8, 16))
    key = 0x10203040 + kind
    transferred = rebind_value(
        _VALUE, _SESSION, source, destination, _ACCOUNT, key, _VERSION, kind
    )
    assert transferred != _VALUE
    assert unwrap_value(
        transferred, _SESSION, destination, _ACCOUNT, key, _VERSION, kind
    ) == unwrap_value(_VALUE, _SESSION, source, _ACCOUNT, key, _VERSION, kind)
    assert (
        rebind_value(_VALUE, _SESSION, source, source, _ACCOUNT, key, _VERSION, kind)
        == _VALUE
    )


@pytest.mark.parametrize("kind", [0, 1])
def test_session_protection_bit_controls_only_session_layer(kind: int) -> None:
    guid = bytes(range(8))
    key = 0x10203040 + kind
    protected = wrap_value(_VALUE, _SESSION, guid, _ACCOUNT, key, 0x10101, kind)
    unprotected = wrap_value(_VALUE, _SESSION, guid, _ACCOUNT, key, 0x10001, kind)
    assert ecb_cipher(_SESSION).decrypt(protected) == unprotected
    assert (
        unwrap_value(unprotected, bytes(16), guid, _ACCOUNT, key, 0x10001, kind)
        == _VALUE
    )


@pytest.mark.parametrize("kind", [-1, 2, 3, 50, 0xFFFFFFFF])
def test_unsupported_kinds_have_no_claimed_final_transform(kind: int) -> None:
    with pytest.raises(ValueError, match="no evidenced final device-key"):
        derive_device_key(bytes(8), 1, 1, _VERSION, kind)


@pytest.mark.parametrize("version", [-1, 0, 0x10002, 0x10102, 0x100000000])
def test_unsupported_account_versions_are_rejected(version: int) -> None:
    with pytest.raises(ValueError, match="account-version"):
        derive_device_key(bytes(8), 1, 1, version, 0)


@pytest.mark.parametrize(
    ("guid", "account", "key"),
    [(bytes(7), 1, 1), (bytes(9), 1, 1), (bytes(8), -1, 1), (bytes(8), 1, 2**32)],
)
def test_invalid_identity_or_selectors_are_rejected(
    guid: bytes, account: int, key: int
) -> None:
    with pytest.raises(ValueError, match="GUID or account/key"):
        derive_device_key(guid, account, key, _VERSION, 0)


@pytest.mark.parametrize(
    ("value", "session"), [(bytes(15), bytes(16)), (bytes(16), bytes(17))]
)
def test_invalid_value_or_session_lengths_are_rejected(
    value: bytes, session: bytes
) -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        unwrap_value(value, session, bytes(8), 1, 1, _VERSION, 0)
    with pytest.raises(ValueError, match="16 bytes"):
        wrap_value(value, session, bytes(8), 1, 1, _VERSION, 0)
