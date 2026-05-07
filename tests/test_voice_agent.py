import asyncio
from unittest.mock import MagicMock, patch
import pytest


def test_transcribe_returns_text():
    mock_result = MagicMock()
    mock_result.text = "Ich möchte eine Recherche über Bitcoin"

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_result

    with patch("agents.voice_agent._get_groq", return_value=mock_client):
        from agents.voice_agent import transcribe
        result = asyncio.run(transcribe(b"fake_ogg_bytes"))

    assert result == "Ich möchte eine Recherche über Bitcoin"
    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["model"] == "whisper-large-v3-turbo"
    assert call_kwargs["language"] == "de"


def test_transcribe_raises_on_empty_transcript():
    mock_result = MagicMock()
    mock_result.text = "   "

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_result

    with patch("agents.voice_agent._get_groq", return_value=mock_client):
        from agents.voice_agent import transcribe
        with pytest.raises(RuntimeError, match="Leeres Transkript"):
            asyncio.run(transcribe(b"fake_ogg_bytes"))


def test_transcribe_propagates_api_error():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = Exception("API unavailable")

    with patch("agents.voice_agent._get_groq", return_value=mock_client):
        from agents.voice_agent import transcribe
        with pytest.raises(Exception, match="API unavailable"):
            asyncio.run(transcribe(b"fake_ogg_bytes"))
