import asyncio
from unittest.mock import MagicMock, patch


def test_load_creates_default_profile(tmp_path):
    from agents.profile_agent import ProfileAgent
    agent = ProfileAgent(str(tmp_path / "profile.md"))
    content = agent.load()
    assert "# Philipp" in content
    assert "Beruf & Rolle" in content
    assert (tmp_path / "profile.md").exists()


def test_load_returns_existing_profile(tmp_path):
    profile_path = tmp_path / "profile.md"
    profile_path.write_text("# Mein Profil\n## Beruf\nEntwickler\n")
    from agents.profile_agent import ProfileAgent
    agent = ProfileAgent(str(profile_path))
    content = agent.load()
    assert content == "# Mein Profil\n## Beruf\nEntwickler\n"


def test_update_writes_when_haiku_returns_content(tmp_path):
    from agents.profile_agent import ProfileAgent
    agent = ProfileAgent(str(tmp_path / "profile.md"))
    agent.load()  # create default

    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="# Philipp — Benutzerprofil\n## Beruf & Rolle\nEntwickler\n")]

    with patch("agents.profile_agent._claude") as mock_claude:
        mock_claude.messages.create.return_value = mock_resp
        asyncio.run(agent.update("Philipp: Ich bin Entwickler.\nJarvis: Super!"))

    updated = (tmp_path / "profile.md").read_text()
    assert "Entwickler" in updated


def test_update_skips_when_haiku_returns_empty(tmp_path):
    from agents.profile_agent import ProfileAgent
    agent = ProfileAgent(str(tmp_path / "profile.md"))
    original = agent.load()

    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="")]

    with patch("agents.profile_agent._claude") as mock_claude:
        mock_claude.messages.create.return_value = mock_resp
        asyncio.run(agent.update("Philipp: Wie ist das Wetter?\nJarvis: Gut."))

    unchanged = (tmp_path / "profile.md").read_text()
    assert unchanged == original
