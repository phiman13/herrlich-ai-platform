# agents/tasks_agent.py
import logging

import httpx

try:
    from microsoft_auth import get_access_token
except ImportError:
    from agents.microsoft_auth import get_access_token  # type: ignore

logger = logging.getLogger("jarvis.tasks")

_BASE = "https://graph.microsoft.com/v1.0/me/todo"


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}", "Content-Type": "application/json"}


def _get_lists() -> list[dict]:
    resp = httpx.get(f"{_BASE}/lists", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json().get("value", [])


def _find_list_id(list_name: str) -> str | None:
    for lst in _get_lists():
        if lst["displayName"].lower() == list_name.lower():
            return lst["id"]
    return None


def get_tasks(list_name: str | None = None) -> str:
    try:
        if list_name:
            list_id = _find_list_id(list_name)
            if not list_id:
                return f"Liste '{list_name}' nicht gefunden."
            resp = httpx.get(
                f"{_BASE}/lists/{list_id}/tasks?$filter=status ne 'completed'&$top=20",
                headers=_headers(), timeout=10,
            )
            resp.raise_for_status()
            tasks = resp.json().get("value", [])
            if not tasks:
                return f"✅ {list_name} — alles erledigt"
            lines = [f"✅ MS TO DO — {list_name} ({len(tasks)} offen)"]
            for t in tasks:
                lines.append(f"• {t['title']}")
            return "\n".join(lines)
        else:
            lists = _get_lists()
            lines = []
            for lst in lists[:5]:
                resp = httpx.get(
                    f"{_BASE}/lists/{lst['id']}/tasks?$filter=status ne 'completed'&$top=5",
                    headers=_headers(), timeout=10,
                )
                resp.raise_for_status()
                tasks = resp.json().get("value", [])
                if tasks:
                    lines.append(f"• {lst['displayName']}: {len(tasks)} offen")
            return "\n".join(lines) if lines else "Keine offenen Tasks."
    except Exception as e:
        logger.warning(f"Tasks nicht verfügbar: {e}")
        return "Tasks nicht verfügbar."


def add_task(list_name: str, title: str) -> bool:
    try:
        list_id = _find_list_id(list_name)
        if not list_id:
            return False
        resp = httpx.post(
            f"{_BASE}/lists/{list_id}/tasks",
            headers=_headers(),
            json={"title": title},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"add_task fehlgeschlagen: {e}")
        return False


def complete_task(list_name: str, task_title: str) -> bool:
    try:
        list_id = _find_list_id(list_name)
        if not list_id:
            return False
        resp = httpx.get(
            f"{_BASE}/lists/{list_id}/tasks?$filter=status ne 'completed'",
            headers=_headers(), timeout=10,
        )
        resp.raise_for_status()
        tasks = resp.json().get("value", [])
        task_id = None
        for t in tasks:
            if t["title"].lower() == task_title.lower():
                task_id = t["id"]
                break
        if not task_id:
            return False
        resp = httpx.patch(
            f"{_BASE}/lists/{list_id}/tasks/{task_id}",
            headers=_headers(),
            json={"status": "completed"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"complete_task fehlgeschlagen: {e}")
        return False
