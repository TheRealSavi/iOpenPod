def install_certifi_ssl() -> None:
    import os

    import certifi

    os.environ.setdefault(
        "SSL_CERT_FILE",
        certifi.where(),
    )
