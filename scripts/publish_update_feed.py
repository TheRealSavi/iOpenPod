"""Publish a signed feed commit with a compare-and-swap branch update."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

from scripts.update_feed import ROOT, create_feed

from iOpenPod.app.updates.releases import (
    REPOSITORY,
    TARGET_SUFFIXES,
    read_json,
    version_tuple,
)


def _api(
    path: str, data: dict[str, object] | None = None, *, method: str | None = None
) -> dict[str, object]:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/{path}",
        body,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "iOpenPod-release-feed",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return cast("dict[str, object]", json.load(response))


def publish(version: str, archives: Path, output: Path) -> str:
    version_tuple(version)
    release = _api(f"releases/tags/v{version}")
    if (
        release.get("draft") is not False
        or release.get("prerelease") is not False
        or release.get("tag_name") != f"v{version}"
    ):
        raise ValueError(
            "Only a published, exactly versioned stable release can update the feed"
        )
    latest = _api("releases/latest")
    if latest.get("id") != release.get("id"):
        raise ValueError("Only the current latest release can update the stable feed")
    published = cast("list[dict[str, object]]", release["assets"])
    for suffix in TARGET_SUFFIXES.values():
        path = archives / f"iOpenPod-{version}-{suffix}"
        asset = next(
            (item for item in published if item.get("name") == path.name), None
        )
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if (
            asset is None
            or asset.get("size") != path.stat().st_size
            or asset.get("digest") != "sha256:" + digest
        ):
            raise ValueError(
                "Local archive differs from the published GitHub release asset"
            )
    parent = None
    base_tree = None
    previous = None
    try:
        reference = _api("git/ref/heads/update-feed")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        parent = str(cast("dict[str, object]", reference["object"])["sha"])
        commit = _api("git/commits/" + parent)
        base_tree = str(cast("dict[str, object]", commit["tree"])["sha"])
        tree = _api("git/trees/" + base_tree)
        entry = next(
            (
                item
                for item in cast("list[dict[str, object]]", tree["tree"])
                if item["path"] == "stable.json"
            ),
            None,
        )
        if entry is None:
            raise ValueError("Existing feed branch has no trusted release history")
        blob = _api("git/blobs/" + str(entry["sha"]))
        previous = base64.b64decode(str(blob["content"]))
        read_json(previous)
    seed = base64.b64decode(
        os.environ.pop("IOPENPOD_UPDATE_PRIVATE_KEY"), validate=True
    )
    if len(seed) != 32:
        raise ValueError("Invalid Ed25519 signing seed")
    create_feed(archives, output, version, seed, root=ROOT, previous=previous)
    entries: list[dict[str, object]] = []
    for name in ("stable.json", "macos-arm64.xml", "macos-x86_64.xml"):
        blob = _api(
            "git/blobs",
            {
                "content": base64.b64encode((output / name).read_bytes()).decode(),
                "encoding": "base64",
            },
        )
        entries.append(
            {"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]}
        )
    tree_data: dict[str, object] = {"tree": entries}
    if base_tree:
        tree_data["base_tree"] = base_tree
    new_tree = _api("git/trees", tree_data)
    commit = _api(
        "git/commits",
        {
            "message": f"Publish signed iOpenPod {version} update feed",
            "tree": new_tree["sha"],
            "parents": [parent] if parent else [],
        },
    )
    sha = str(commit["sha"])
    if parent:
        # Concurrent publication creates a sibling commit and cannot fast-forward.
        _api("git/refs/heads/update-feed", {"sha": sha, "force": False}, method="PATCH")
    else:
        _api("git/refs", {"ref": "refs/heads/update-feed", "sha": sha})
    return sha


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("archives", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(
        "Published signed feed commit "
        + publish(args.version, args.archives, args.output)
    )


if __name__ == "__main__":
    main()
