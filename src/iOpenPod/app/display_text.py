"""Retain display templates without coupling application results to a GUI locale."""

from typing import Self


class SourceText(str):
    """An English string whose immutable template can be translated at display time."""

    __slots__ = ("_parameters", "_source")

    _source: str
    _parameters: tuple[tuple[str, str], ...]

    def __new__(cls, source: str, parameters: tuple[tuple[str, str], ...]) -> Self:
        value = super().__new__(cls, source.format(**dict(parameters)))
        object.__setattr__(value, "_source", source)
        object.__setattr__(value, "_parameters", parameters)
        return value

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SourceText is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SourceText is immutable")

    @property
    def source(self) -> str:
        return self._source

    @property
    def parameters(self) -> tuple[tuple[str, str], ...]:
        return self._parameters

    def __reduce__(
        self,
    ) -> tuple[type[Self], tuple[str, tuple[tuple[str, str], ...]]]:
        return type(self), (self.source, self.parameters)


def source_text(source: str, **parameters: str) -> SourceText:
    """Format readable source copy while retaining its named display values."""

    return SourceText(source, tuple(parameters.items()))


def exception_text(error: BaseException) -> str:
    """Keep an explicit display template when it is the exception's complete text.

    Native errors and custom exception formatting retain their ordinary ``str``
    representation. Exception type, arguments, and cause are never modified.
    """

    rendered = str(error)
    if len(error.args) == 1:
        source = error.args[0]
        if isinstance(source, SourceText) and source == rendered:
            return source
    return rendered
