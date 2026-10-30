"""Small synthetic account-session tests, without firmware or captured licenses."""

import pytest

from iPodDB.ic_info.sessions import decode_session, encode_session


@pytest.mark.parametrize("family", [13, 20, 25, 24, 33, 35, 38, 26, 31, 34])
def test_account_session_round_trip(family: int) -> None:
    session = bytes(range(16))
    wrapped = encode_session(session, family)
    assert len(wrapped) == 128
    assert decode_session(wrapped, family) == session


@pytest.mark.parametrize("families", [(13, 20, 25), (24, 33, 35, 38), (26, 31)])
def test_shared_firmware_key_groups(families: tuple[int, ...]) -> None:
    session = bytes(range(16))
    wrapped = encode_session(session, families[0])
    for family in families[1:]:
        assert decode_session(wrapped, family) == session


def test_different_groups_reject_same_ciphertext() -> None:
    wrapped = encode_session(bytes(range(16)), 33)
    for family in (13, 26, 34):
        with pytest.raises(ValueError):
            decode_session(wrapped, family)


def test_oaep_randomness_does_not_change_session() -> None:
    session = bytes(range(16))
    first = encode_session(session, 34)
    second = encode_session(session, 34)
    assert first != second
    assert decode_session(first, 34) == decode_session(second, 34) == session


def test_tampered_session_is_rejected() -> None:
    wrapped = bytearray(encode_session(bytes(range(16)), 33))
    wrapped[53] ^= 1
    with pytest.raises(ValueError):
        decode_session(bytes(wrapped), 33)


@pytest.mark.parametrize("length", [0, 15, 17, 128])
def test_session_plaintext_length_is_exact(length: int) -> None:
    with pytest.raises(ValueError, match="16 bytes"):
        encode_session(bytes(length), 33)


@pytest.mark.parametrize("length", [0, 16, 127, 129])
def test_session_ciphertext_length_is_exact(length: int) -> None:
    with pytest.raises(ValueError, match="128 encrypted bytes"):
        decode_session(bytes(length), 33)


def test_unknown_family_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported IC-Info updater family"):
        encode_session(bytes(16), 99)
