import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def run_in_thread(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a blocking callable in a worker thread (forwards args to asyncio.to_thread)."""
    return await asyncio.to_thread(func, *args, **kwargs)
