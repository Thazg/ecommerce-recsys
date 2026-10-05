"""Pin numerical worker pools during reproducible offline benchmarks."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from threadpoolctl import threadpool_limits

P = ParamSpec("P")
R = TypeVar("R")


def single_thread_benchmark(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with threadpool_limits(limits=1):
            return function(*args, **kwargs)

    return wrapped
