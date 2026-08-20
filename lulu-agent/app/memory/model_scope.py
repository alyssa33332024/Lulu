from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator


@asynccontextmanager
async def model_execution_scope(provider: Any) -> AsyncIterator[None]:
    del provider
    yield
