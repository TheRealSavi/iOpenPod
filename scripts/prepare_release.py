"""Resolve a GitHub release request without creating tags or publishing assets."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReleaseRequest:
    tag: str
    publish: bool
    create_tag: bool


def prepare(
    root: Path, *, event: str, ref: str, publish_requested: bool
) -> ReleaseRequest:
    with (root / "pyproject.toml").open("rb") as stream:
        version = str(tomllib.load(stream)["project"]["version"])
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None or any(
        int(part) > 65535 for part in version.split(".")
    ):
        raise ValueError("Native releases require a numeric major.minor.patch version")
    tag = f"v{version}"
    tagged = ref.startswith("refs/tags/")
    publish = event in {"push", "workflow_dispatch"} and tagged
    if tagged and ref != f"refs/tags/{tag}":
        raise ValueError(f"Release tag must equal {tag}")
    if publish_requested:
        if event != "workflow_dispatch" or (not tagged and ref != "refs/heads/main"):
            raise ValueError(
                "Manual publication requires main or a matching version tag"
            )
        publish = True
    if not publish:
        return ReleaseRequest(tag, False, False)
    existing = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if existing.returncode not in (0, 1):
        raise ValueError(f"Cannot resolve existing tag: {existing.stderr.strip()}")
    if existing.returncode == 0:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        if existing.stdout.strip() != head:
            raise ValueError(
                f"{tag} already points at a different commit; bump the version"
            )
    elif tagged:
        raise ValueError(f"The requested tag {tag} is missing from the checkout")
    return ReleaseRequest(tag, True, existing.returncode == 1)


def main() -> None:
    request = prepare(
        Path(__file__).resolve().parents[1],
        event=os.environ["GITHUB_EVENT_NAME"],
        ref=os.environ["GITHUB_REF"],
        publish_requested=os.environ.get("PUBLISH_RELEASE") == "true",
    )
    outputs = (
        f"tag={request.tag}\n"
        f"publish={str(request.publish).lower()}\n"
        f"create_tag={str(request.create_tag).lower()}\n"
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        stream.write(outputs)
    print(outputs, end="")


if __name__ == "__main__":
    main()
