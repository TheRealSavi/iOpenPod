"""Application display templates remain ordinary strings until presentation."""

from copy import deepcopy

import pytest

from iOpenPod.app.display_text import SourceText, exception_text, source_text


def test_source_text_retains_template_values_and_existing_string_behavior() -> None:
    message = source_text(
        "Preparing {title}: {done} of {total}", title="A {B}", done="2", total="5"
    )

    assert isinstance(message, str)
    assert message == "Preparing A {B}: 2 of 5"
    assert hash(message) == hash("Preparing A {B}: 2 of 5")
    assert message.source == "Preparing {title}: {done} of {total}"
    assert dict(message.parameters) == {"title": "A {B}", "done": "2", "total": "5"}
    # Exercise the immutability guard on its backing field.
    with pytest.raises(AttributeError, match="immutable"):
        message._source = "Changed"  # pyright: ignore[reportPrivateUsage]
    copied = deepcopy(message)
    assert isinstance(copied, SourceText)
    assert copied.source == message.source and copied.parameters == message.parameters


def test_exception_capture_preserves_explicit_source_without_changing_causes() -> None:
    cause = OSError(5, "Native detail")
    source = source_text("The file {name} changed.", name="My {file}.mp3")
    error = ValueError(source)
    error.__cause__ = cause

    captured = exception_text(error)

    assert captured is source
    assert str(error) == captured == "The file My {file}.mp3 changed."
    assert error.__cause__ is cause and error.args == (source,)


def test_exception_capture_keeps_native_and_custom_string_semantics() -> None:
    class CustomError(Exception):
        def __str__(self) -> str:
            return "Custom prefix: " + super().__str__()

    source = source_text("The file {name} changed.", name="music.mp3")
    errors = (
        OSError(5, "Native detail"),
        CustomError(source),
        ValueError(" Plain text "),
    )
    for error in errors:
        captured = exception_text(error)
        assert captured == str(error)
        assert type(captured) is str
