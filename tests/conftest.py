# tests/conftest.py
import pytest
from unittest.mock import patch, AsyncMock


@pytest.fixture(autouse=True)
def mock_ensure_init():
    """Prevent _ensure_init from hitting the filesystem in tests."""
    async def noop():
        pass

    with patch("agents.coding_agent._ensure_init", side_effect=noop):
        yield
