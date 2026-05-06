# tests/conftest.py
import pytest
import os
from unittest.mock import patch, MagicMock, AsyncMock


def pytest_configure(config):
    """Mock telegram before any test modules import agents.main."""
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_12345:test_string")

    # Patch telegram.ext.Application.builder at import time
    mock_bot_app = MagicMock()
    mock_bot_app.initialize = AsyncMock()
    mock_bot_app.start = AsyncMock()
    mock_bot_app.stop = AsyncMock()
    mock_bot_app.add_handler = MagicMock()

    # Create a builder mock chain
    mock_builder = MagicMock()
    mock_builder.token.return_value.build.return_value = mock_bot_app

    # Patch the Application.builder directly in the module
    patch("telegram.ext.Application.builder", return_value=mock_builder).start()


@pytest.fixture(autouse=True)
def mock_ensure_init():
    """Prevent _ensure_init from hitting the filesystem in tests."""
    async def noop():
        pass

    with patch("agents.coding_agent._ensure_init", side_effect=noop):
        yield
