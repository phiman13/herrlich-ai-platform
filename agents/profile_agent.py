import asyncio
import logging
import os

import anthropic

logger = logging.getLogger("jarvis.profile")

PROFILE_PATH = "/root/.jarvis/user_profile.md"

_DEFAULT_PROFILE = """\
# Philipp — Benutzerprofil

## Beruf & Rolle
*Noch keine Informationen*

## Fähigkeiten & Werkzeuge
*Noch keine Informationen*

## Projekte
*Noch keine Informationen*

## Interessen & Hobbys
*Noch keine Informationen*

## Kommunikationsstil
*Noch keine Informationen*

## Laufende Ziele
*Noch keine Informationen*
"""

_UPDATE_SYSTEM = (
    "Du pflegst das Benutzerprofil von Philipp für seinen persönlichen KI-Assistenten Jarvis.\n"
    "Dir wird ein Gespräch und das aktuelle Profil gezeigt.\n"
    "Entscheide: Enthält das Gespräch neue, relevante Informationen über Philipp "
    "(Beruf, Skills, Projekte, Interessen, Ziele, Kommunikationsstil)?\n"
    "Wenn JA: Gib das vollständig aktualisierte Profil zurück (exakt gleiche Markdown-Struktur).\n"
    "Wenn NEIN: Gib einen leeren String zurück.\n"
    "WICHTIG: Nur faktische Informationen über Philipp aufnehmen. "
    "Kein erklärender Text außerhalb des Profils."
)

_claude = anthropic.Anthropic()
_profile_lock = asyncio.Lock()


class ProfileAgent:
    def __init__(self, path: str = PROFILE_PATH):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def load(self) -> str:
        try:
            with open(self.path, "x", encoding="utf-8") as f:
                f.write(_DEFAULT_PROFILE)
        except FileExistsError:
            pass
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    async def update(self, conversation: str) -> None:
        async with _profile_lock:
            current = self.load()
            prompt = f"Aktuelles Profil:\n{current}\n\nGespräch:\n{conversation}"
            try:
                resp = await asyncio.to_thread(
                    _claude.messages.create,
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1000,
                    temperature=0,
                    system=_UPDATE_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                )
                updated = ""
                for block in resp.content:
                    if hasattr(block, "text"):
                        updated += block.text
                updated = updated.strip()
                if updated and updated != current.strip():
                    with open(self.path, "w", encoding="utf-8") as f:
                        f.write(updated + "\n")
                    logger.info("User profile updated")
            except Exception as e:
                logger.warning("Profile update failed: %s", e)
