"""Release requests bind publication to the checked-out version and commit."""

import subprocess
from pathlib import Path

import pytest
from scripts.prepare_release import ReleaseRequest, prepare


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "2.0.1"\n')
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "Initial",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_candidates_do_not_request_a_tag(checkout: Path, event: str) -> None:
    assert prepare(
        checkout, event=event, ref="refs/heads/main", publish_requested=False
    ) == ReleaseRequest("v2.0.1", False, False)


def test_manual_release_requests_tag_only_when_missing(checkout: Path) -> None:
    assert prepare(
        checkout,
        event="workflow_dispatch",
        ref="refs/heads/main",
        publish_requested=True,
    ) == ReleaseRequest("v2.0.1", True, True)
    assert (
        subprocess.run(
            ["git", "tag", "--list"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        == ""
    )


@pytest.mark.parametrize("annotated", [False, True])
@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_existing_tag_resolves_to_the_built_commit(
    checkout: Path, annotated: bool, event: str
) -> None:
    command = [
        "git",
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "tag.gpgsign=false",
        "tag",
        "v2.0.1",
    ]
    if annotated:
        command.extend(["-a", "-m", "Release"])
    subprocess.run(command, cwd=checkout, check=True)
    assert prepare(
        checkout, event=event, ref="refs/tags/v2.0.1", publish_requested=False
    ) == ReleaseRequest("v2.0.1", True, False)


def test_existing_tag_cannot_be_reused_for_new_code(checkout: Path) -> None:
    subprocess.run(
        ["git", "-c", "tag.gpgsign=false", "tag", "v2.0.1"], cwd=checkout, check=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            "Changed",
        ],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="different commit"):
        prepare(
            checkout,
            event="workflow_dispatch",
            ref="refs/heads/main",
            publish_requested=True,
        )


@pytest.mark.parametrize(
    "event,ref,requested,reason",
    [
        ("push", "refs/tags/v1.0.0", False, "must equal"),
        ("push", "refs/tags/v2.0.1", False, "missing"),
        ("workflow_dispatch", "refs/heads/feature", True, "requires main"),
        ("pull_request", "refs/pull/1/merge", True, "requires main"),
    ],
)
def test_invalid_requests_are_rejected(
    checkout: Path, event: str, ref: str, requested: bool, reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        prepare(checkout, event=event, ref=ref, publish_requested=requested)
