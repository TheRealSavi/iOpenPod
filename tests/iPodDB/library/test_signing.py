"""Public HASH72 signing-material contract tests."""

from iPodDB.library import Hash72Material, parse_hash72_info


def test_parse_hash72_info_preserves_typed_device_binding() -> None:
    guid = bytes.fromhex("000A270012345678")
    random_part = bytes(range(12))
    iv = bytes(range(16))

    material = parse_hash72_info(b"HASHv0" + guid + bytes(12) + random_part + iv)

    assert material == Hash72Material(guid + bytes(12), random_part, iv)
    assert material.belongs_to_guid(guid)


def test_hash72_material_rejects_nonzero_uuid_padding() -> None:
    guid = bytes.fromhex("000A270012345678")
    material = parse_hash72_info(
        b"HASHv0" + guid + bytes(11) + b"\x01" + bytes(range(12)) + bytes(range(16))
    )

    assert not material.belongs_to_guid(guid)


def test_hash72_material_rejects_each_replaced_secret_component() -> None:
    original = Hash72Material(bytes(20), bytes(range(12)), bytes(range(16)))

    assert not original.matches(
        Hash72Material(bytes(20), bytes(reversed(range(12))), bytes(range(16)))
    )
    assert not original.matches(
        Hash72Material(bytes(20), bytes(range(12)), bytes(reversed(range(16))))
    )
