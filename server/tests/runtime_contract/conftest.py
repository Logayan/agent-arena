from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """The application runtime is asyncio; do not synthesize an unavailable Trio lane."""

    return "asyncio"
