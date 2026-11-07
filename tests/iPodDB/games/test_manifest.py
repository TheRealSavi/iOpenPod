"""Tiny manifests capture display semantics without game or account fixtures."""

import plistlib

import pytest

from iPodDB.games import parse_game_manifest


@pytest.mark.parametrize("fmt", [plistlib.FMT_XML, plistlib.FMT_BINARY])
def test_display_fields_preserve_versions_and_ignore_platform_variants(
    fmt: plistlib.PlistFormat,
) -> None:
    result = parse_game_manifest(
        plistlib.dumps(
            {
                "Name": "Phase",
                "Version": "1.0.0",
                "GUID": "1D000",
                "Platforms": [{"ExecutablePath": "../untrusted"}, {}],
            },
            fmt=fmt,
        )
    )
    assert (result.title, result.version, result.identifier) == (
        "Phase",
        "1.0.0",
        "1D000",
    )


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a plist",
        b"<?xml version='1.0'?><plist><dict>",
        plistlib.dumps([]),
        plistlib.dumps({"Name": 12}),
        b"x" * (1024 * 1024 + 1),
    ],
    ids=["empty", "non-plist", "broken-xml", "list", "invalid-fields", "oversized"],
)
def test_malformed_or_oversized_manifest_rejected(data: bytes) -> None:
    with pytest.raises(ValueError):
        parse_game_manifest(data)
