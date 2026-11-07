"""Choose full-suite parallelism before pytest-xdist starts its workers."""

from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "full_suite_workers",
        "Worker count for complete test runs using -n auto.",
        type="int",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """Keep focused runs serial; explicit numeric -n overrides bypass this hook."""

    if any(
        config.getoption(option, default=None)
        for option in (
            "collectonly",
            "keyword",
            "markexpr",
            "lf",
            "stepwise",
            "stepwise_skip",
            "stepwise_reset",
            "deselect",
            "ignore",
            "ignore_glob",
            "pyargs",
        )
    ):
        return 0

    selected = {
        (config.invocation_params.dir / Path(argument)).resolve()
        for argument in config.args
        if "::" not in argument
    }
    test_roots = {
        (config.rootpath / path).resolve() for path in config.getini("testpaths")
    }
    full_suite = config.rootpath in selected or (
        bool(test_roots) and test_roots.issubset(selected)
    )
    if not full_suite:
        return 0

    workers = config.getini("full_suite_workers")
    if not isinstance(workers, int) or workers < 1:
        raise pytest.UsageError("full_suite_workers must be a positive integer")
    return workers
