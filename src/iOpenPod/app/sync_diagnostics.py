"""Give Library diagnostics the Track context available to the Sync workflow."""

from collections.abc import Iterable
from dataclasses import replace

from iOpenPod.app.display_text import source_text
from iPodDB.library import Track, WriteIssue


def describe_track_issues(
    issues: Iterable[WriteIssue], tracks: Iterable[Track]
) -> tuple[WriteIssue, ...]:
    """Retain structured identities and add readable names and source locations."""
    by_id = {track.track_id: track for track in tracks}
    described: list[WriteIssue] = []
    for issue in issues:
        track = (
            by_id.get(issue.record_id)
            if issue.subject == "track" and issue.record_id is not None
            else None
        )
        if track is None:
            described.append(issue)
            continue
        title = track.title or source_text("Untitled Track")
        collection = track.show or track.album
        name = (
            source_text("{title} — {collection}", title=title, collection=collection)
            if collection
            else source_text("{title}", title=title)
        )
        detail = (
            source_text("{name}\n{detail}", name=name, detail=issue.detail)
            if issue.detail
            else name
        )
        described.append(
            replace(
                issue,
                detail=detail,
                artifact=issue.artifact
                or track.metadata.podcast_enclosure_url
                or track.metadata.location,
            )
        )
    return tuple(described)


def unique_issues(issues: Iterable[WriteIssue]) -> tuple[WriteIssue, ...]:
    """A retry is another attempt, not another affected item."""
    return tuple(dict.fromkeys(issues))
