"""Update fixtures must retain stable upgrade and downgrade test scenarios."""

from itertools import pairwise

from packaging.version import Version
from tests.iOpenPod.app.version_fixtures import (
    CURRENT_VERSION,
    NEXT_MINOR_VERSION,
    NEXT_VERSION,
    OLDER_VERSION,
    PREVIOUS_VERSION,
    patch_version,
)


def test_update_fixture_versions_are_stable_and_strictly_ordered() -> None:
    versions = tuple(
        Version(value)
        for value in (
            OLDER_VERSION,
            PREVIOUS_VERSION,
            CURRENT_VERSION,
            NEXT_VERSION,
            patch_version(2),
            patch_version(3),
            NEXT_MINOR_VERSION,
        )
    )

    assert all(
        not version.is_prerelease and not version.is_devrelease for version in versions
    )
    assert all(older < newer for older, newer in pairwise(versions))
