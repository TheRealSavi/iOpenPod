# threadpoolctl 3.6 ships no type information. Declare only the API iOpenPod uses.
from types import TracebackType
from typing import Literal, Self

def threadpool_info() -> list[dict[str, object]]: ...

class threadpool_limits:  # noqa: N801 - the library's own spelling
    def __init__(
        self,
        limits: int | None = None,
        user_api: Literal["blas", "openmp"] | None = None,
    ) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
