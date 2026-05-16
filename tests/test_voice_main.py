import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import dispatch as main_module
import app_state


def test_handle_voice_transcribes_and_calls_process_text():
    app_state.processed_updates.discard(8801)

    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_ogg"))

    mock_update = MagicMock()
    mock_update.update_id = 8801
    mock_update.message.chat_id = 123
    mock_update.message.voice.get_file = AsyncMock(return_value=mock_file)

    with (
        patch(
            "dispatch.transcribe",
            new_callable=AsyncMock,
            return_value="Was kostet Bitcoin?",
        ) as mock_transcribe,
        patch("dispatch._process_text", new_callable=AsyncMock) as mock_process,
    ):
        asyncio.run(main_module.handle_voice(mock_update, None))

    mock_transcribe.assert_called_once_with(bytes(b"fake_ogg"))
    mock_process.assert_called_once_with("Was kostet Bitcoin?", 123, mock_update)


def test_handle_voice_sends_error_on_transcription_failure():
    app_state.processed_updates.discard(8802)

    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_ogg"))

    mock_update = MagicMock()
    mock_update.update_id = 8802
    mock_update.message.chat_id = 123
    mock_update.message.voice.get_file = AsyncMock(return_value=mock_file)
    mock_update.message.reply_text = AsyncMock()

    with patch(
        "dispatch.transcribe",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Leeres Transkript"),
    ):
        asyncio.run(main_module.handle_voice(mock_update, None))

    mock_update.message.reply_text.assert_called_once_with(
        "❌ Sprachnachricht konnte nicht transkribiert werden."
    )


def test_handle_voice_deduplicates():
    app_state.processed_updates.discard(8803)

    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_ogg"))

    mock_update = MagicMock()
    mock_update.update_id = 8803
    mock_update.message.chat_id = 123
    mock_update.message.voice.get_file = AsyncMock(return_value=mock_file)

    with (
        patch(
            "dispatch.transcribe", new_callable=AsyncMock, return_value="Text"
        ) as mock_transcribe,
        patch("dispatch._process_text", new_callable=AsyncMock) as mock_process,
    ):
        asyncio.run(main_module.handle_voice(mock_update, None))
        asyncio.run(main_module.handle_voice(mock_update, None))

    assert mock_transcribe.call_count == 1
    assert mock_process.call_count == 1
