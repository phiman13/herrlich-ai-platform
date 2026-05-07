import logging
import os

import httpx

logger = logging.getLogger("jarvis.ntfy")

_NTFY_BASE = "https://ntfy.sh"


def send_reminder(
    title: str, due_date: str | None = None, list_name: str | None = None
) -> None:
    topic = os.environ.get("NTFY_REMINDER_TOPIC")
    if not topic:
        raise RuntimeError("NTFY_REMINDER_TOPIC nicht gesetzt")

    message_parts = [title]
    if due_date:
        message_parts.append(f"Fällig: {due_date}")
    if list_name:
        message_parts.append(f"Liste: {list_name}")

    headers = {
        "Title": title,
        "Tags": "bell",
        "Priority": "default",
        # Shortcut on iPhone reads X-Due and X-List to create the reminder
        "X-Due": due_date or "",
        "X-List": list_name or "",
    }

    resp = httpx.post(
        f"{_NTFY_BASE}/{topic}",
        content="\n".join(message_parts),
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    logger.info(
        "ntfy reminder gesendet: topic=%s title=%r due=%s", topic, title, due_date
    )
