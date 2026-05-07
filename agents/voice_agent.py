import asyncio
import io
import logging
import os

logger = logging.getLogger("jarvis.voice")

_groq = None


def _get_groq():
    global _groq
    if _groq is None:
        from groq import Groq
        _groq = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq


async def transcribe(ogg_bytes: bytes) -> str:
    client = _get_groq()
    audio_io = io.BytesIO(ogg_bytes)
    audio_io.name = "voice.ogg"
    result = await asyncio.to_thread(
        client.audio.transcriptions.create,
        model="whisper-large-v3-turbo",
        file=audio_io,
        language="de",
    )
    text = result.text.strip()
    if not text:
        raise RuntimeError("Leeres Transkript")
    return text
