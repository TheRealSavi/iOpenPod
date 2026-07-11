from iopenpod.infrastructure.settings_secrets import (
    decrypt_secret_for_device,
    encrypt_secret,
    normalized_device_mount_key,
)


def test_device_secret_round_trip_with_current_key() -> None:
    encoded = encrypt_secret("listen-token", "SERIAL123")

    assert encoded.startswith("xor1:")
    assert (
        decrypt_secret_for_device(encoded, device_key="SERIAL123")
        == "listen-token"
    )


def test_device_secret_round_trip_with_legacy_mount_mixed_key() -> None:
    ipod_root = "C:\\IPOD"
    encoded = encrypt_secret(
        "listen-token",
        f"SERIAL123|{normalized_device_mount_key(ipod_root)}",
    )

    assert (
        decrypt_secret_for_device(
            encoded,
            device_key="SERIAL123",
            ipod_root=ipod_root,
        )
        == "listen-token"
    )
