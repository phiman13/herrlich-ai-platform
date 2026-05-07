# tests/conftest.py
import sys
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# ---------------------------------------------------------------------------
# Path fixup — must run at module load time, before any test collection.
#
# pytest rootdir is herrlich-ai-platform/ (the parent repo), so without this
# fixup "import agents.router" resolves to the main repo's agents/router.py
# instead of the plan4 worktree's updated version.
#
# We prepend:
#   1. <worktree>/                 → "agents" package resolves to worktree's agents/
#   2. <worktree>/agents/          → bare imports (router, calendar_agent, …) resolve
#                                    to worktree's files, not main repo's
# ---------------------------------------------------------------------------
_WORKTREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENTS_DIR = os.path.join(_WORKTREE, "agents")

for _p in (_AGENTS_DIR, _WORKTREE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Evict any already-imported agents.* entries so they re-import from worktree
for _key in list(sys.modules):
    if _key == "agents" or _key.startswith("agents."):
        del sys.modules[_key]


def pytest_configure(config):
    """Set env vars and mock external deps before any test module imports agents.*"""
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_12345:test_string")

    # Mock missing optional packages so agents.main can be imported without them installed
    for _mod in ("msal", "requests"):
        if _mod not in sys.modules:
            sys.modules[_mod] = MagicMock()

    # Patch telegram.ext.Application.builder at import time
    mock_bot_app = MagicMock()
    mock_bot_app.initialize = AsyncMock()
    mock_bot_app.start = AsyncMock()
    mock_bot_app.stop = AsyncMock()
    mock_bot_app.add_handler = MagicMock()

    mock_builder = MagicMock()
    mock_builder.token.return_value.build.return_value = mock_bot_app

    patch("telegram.ext.Application.builder", return_value=mock_builder).start()


@pytest.fixture(autouse=True)
def mock_ensure_init():
    """Prevent _ensure_init from hitting the filesystem in tests."""
    async def noop():
        pass

    try:
        with patch("agents.coding_agent._ensure_init", side_effect=noop):
            yield
    except (ImportError, AttributeError):
        # If coding_agent doesn't exist or doesn't have _ensure_init, skip the patch
        yield
