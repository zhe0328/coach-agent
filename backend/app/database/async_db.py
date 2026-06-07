import asyncio
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


async def run_in_thread(func: Callable[[], T]) -> T:
    """Run a blocking DB / I/O callable in a worker thread."""
    return await asyncio.to_thread(func)
