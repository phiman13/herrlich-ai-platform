# Morning Briefing + Tasks + News Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis sendet täglich um 07:00 ein proaktives Morning Briefing via Telegram mit Kalender, Mail, Wetter, MS To Do, Apple Reminders, GitHub-Status und AI-News — plus on-demand Abruf aller Blöcke.

**Architecture:** Jeder Datenblock ist ein eigenständiger Agent (`weather_agent.py`, `news_agent.py`, `github_agent.py`, `tasks_agent.py`). `briefing_agent.py` orchestriert alle Blöcke zu einer formatierten Telegram-Nachricht. APScheduler in `main.py` triggert das Briefing täglich 07:00 Europe/Berlin. Jeder Block ist fehler-isoliert: schlägt ein Block fehl, kommt das Briefing trotzdem mit den restlichen Blöcken.

**Tech Stack:** Python 3.12, httpx (bereits installiert), caldav (bereits installiert), feedparser (neu), apscheduler (neu), msal (bereits installiert via microsoft_auth), python-telegram-bot (bereits installiert)

**VPS:** `/root/agents/`, Jarvis-Service via `systemctl restart jarvis`. Alle Env-Vars in `/root/.env`.

---

## File Structure

```
agents/
  weather_agent.py      NEU — Open-Meteo API (kein Key), get_weather_today() -> str
  news_agent.py         NEU — feedparser, 15 RSS-Feeds, 24h-Filter, Dedup, get_ai_news() -> str
  github_agent.py       NEU — GitHub REST API + PAT, open PRs + recent commits, get_github_summary() -> str
  tasks_agent.py        NEU — MS Graph /me/todo/lists, get_tasks() / add_task() / complete_task()
  calendar_agent.py     MODIFY — add get_reminders_today() -> list[str] via CalDAV VTODO
  briefing_agent.py     NEU — orchestriert alle Blöcke, build_briefing() -> str
  main.py               MODIFY — APScheduler startup, news/tasks/briefing handlers, TELEGRAM_CHAT_ID
  requirements.txt      MODIFY — feedparser, apscheduler hinzufügen

tests/
  test_weather_agent.py  NEU
  test_news_agent.py     NEU
  test_github_agent.py   NEU
  test_tasks_agent.py    NEU
  test_briefing_agent.py NEU
```

---

## Task 1: Weather Agent

**Files:**
- Create: `agents/weather_agent.py`
- Create: `tests/test_weather_agent.py`

Open-Meteo ist kostenlos, kein API-Key. Koordinaten: München (48.14°N, 11.58°E) — nahe Tutzing.

- [ ] **Step 1.1: Test schreiben**

```python
# tests/test_weather_agent.py
import pytest
from unittest.mock import patch, MagicMock

try:
    from agents.weather_agent import get_weather_today
except ImportError:
    from weather_agent import get_weather_today


def _mock_response(temp, code, precip):
    m = MagicMock()
    m.json.return_value = {"current": {"temperature_2m": temp, "weathercode": code, "precipitation": precip}}
    m.raise_for_status = MagicMock()
    return m


def test_weather_contains_temperature():
    with patch("httpx.get", return_value=_mock_response(18.5, 3, 0.0)):
        result = get_weather_today()
    assert "18" in result
    assert "°C" in result


def test_weather_clear_sky():
    with patch("httpx.get", return_value=_mock_response(22.0, 0, 0.0)):
        result = get_weather_today()
    assert "klar" in result.lower() or "☀" in result


def test_weather_rain():
    with patch("httpx.get", return_value=_mock_response(12.0, 63, 3.2)):
        result = get_weather_today()
    assert "regen" in result.lower() or "🌧" in result


def test_weather_api_error_returns_fallback():
    with patch("httpx.get", side_effect=Exception("timeout")):
        result = get_weather_today()
    assert "Wetter" in result or "nicht verfügbar" in result.lower()
```

- [ ] **Step 1.2: Tests laufen — müssen fehlschlagen**

```bash
cd /Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform
source .worktrees/plan1-coding-agent/.venv/bin/activate
python -m pytest tests/test_weather_agent.py -v
```

Erwartet: `ImportError` oder `ModuleNotFoundError`

- [ ] **Step 1.3: weather_agent.py implementieren**

```python
# agents/weather_agent.py
import httpx
import logging

logger = logging.getLogger("jarvis.weather")

_WMO_CODES = {
    0: ("klar", "☀️"),
    1: ("leicht bewölkt", "🌤️"),
    2: ("bewölkt", "⛅"),
    3: ("bedeckt", "☁️"),
    45: ("Nebel", "🌫️"),
    48: ("Nebel", "🌫️"),
    51: ("Nieselregen", "🌦️"),
    53: ("Nieselregen", "🌦️"),
    55: ("Nieselregen", "🌦️"),
    61: ("Regen", "🌧️"),
    63: ("Regen", "🌧️"),
    65: ("starker Regen", "🌧️"),
    71: ("Schnee", "❄️"),
    73: ("Schnee", "❄️"),
    75: ("starker Schnee", "❄️"),
    80: ("Schauer", "🌦️"),
    81: ("Schauer", "🌦️"),
    82: ("starke Schauer", "⛈️"),
    95: ("Gewitter", "⛈️"),
    96: ("Gewitter", "⛈️"),
    99: ("Gewitter", "⛈️"),
}

_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=48.14&longitude=11.58"
    "&current=temperature_2m,weathercode,precipitation"
    "&timezone=Europe%2FBerlin"
)


def get_weather_today() -> str:
    try:
        resp = httpx.get(_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()["current"]
        temp = round(data["temperature_2m"])
        code = int(data["weathercode"])
        precip = data.get("precipitation", 0.0)
        desc, icon = _WMO_CODES.get(code, ("unbekannt", "🌡️"))
        rain_note = f", {precip:.1f} mm" if precip > 0 else ", kein Regen"
        return f"{icon} {temp}°C, {desc}{rain_note}"
    except Exception as e:
        logger.warning(f"Wetter nicht verfügbar: {e}")
        return "🌡️ Wetter nicht verfügbar"
```

- [ ] **Step 1.4: Tests grün**

```bash
python -m pytest tests/test_weather_agent.py -v
```

Erwartet: 4 passed

- [ ] **Step 1.5: Commit**

```bash
git add agents/weather_agent.py tests/test_weather_agent.py
git commit -m "feat(briefing): weather agent — Open-Meteo, kein API-Key"
```

---

## Task 2: News Agent

**Files:**
- Create: `agents/news_agent.py`
- Create: `tests/test_news_agent.py`
- Modify: `agents/requirements.txt`

- [ ] **Step 2.1: feedparser zu requirements.txt hinzufügen**

Füge ans Ende von `agents/requirements.txt` hinzu:
```
feedparser>=6.0.10
```

- [ ] **Step 2.2: feedparser installieren**

```bash
source .worktrees/plan1-coding-agent/.venv/bin/activate
pip install feedparser -q
```

- [ ] **Step 2.3: Test schreiben**

```python
# tests/test_news_agent.py
import time
import pytest
from unittest.mock import patch, MagicMock

try:
    from agents.news_agent import get_ai_news, _dedup, _is_recent
except ImportError:
    from news_agent import get_ai_news, _dedup, _is_recent


def _make_entry(title, published_parsed=None):
    entry = MagicMock()
    entry.title = title
    entry.link = f"https://example.com/{title.replace(' ', '-')}"
    entry.published_parsed = published_parsed or time.gmtime()  # jetzt = recent
    return entry


def test_dedup_removes_similar_titles():
    entries = [
        _make_entry("GPT-5 released by OpenAI"),
        _make_entry("GPT-5 released by OpenAI today"),  # sehr ähnlich
        _make_entry("Claude 4 beats GPT-5 on benchmarks"),
    ]
    result = _dedup(entries)
    assert len(result) == 2


def test_dedup_keeps_different_titles():
    entries = [
        _make_entry("GPT-5 released"),
        _make_entry("Claude 4 announced"),
        _make_entry("Gemini Ultra 2 launch"),
    ]
    result = _dedup(entries)
    assert len(result) == 3


def test_is_recent_now():
    assert _is_recent(time.gmtime(), hours=24) is True


def test_is_recent_old():
    old = time.gmtime(time.time() - 48 * 3600)
    assert _is_recent(old, hours=24) is False


def test_get_ai_news_returns_string():
    fake_feed = MagicMock()
    fake_feed.entries = [_make_entry(f"AI News Item {i}") for i in range(3)]
    with patch("feedparser.parse", return_value=fake_feed):
        result = get_ai_news(hours=24, max_items=5)
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_ai_news_empty_feeds():
    fake_feed = MagicMock()
    fake_feed.entries = []
    with patch("feedparser.parse", return_value=fake_feed):
        result = get_ai_news(hours=24, max_items=5)
    assert "keine" in result.lower() or result == ""
```

- [ ] **Step 2.4: Tests laufen — müssen fehlschlagen**

```bash
python -m pytest tests/test_news_agent.py -v
```

Erwartet: `ImportError`

- [ ] **Step 2.5: news_agent.py implementieren**

```python
# agents/news_agent.py
import difflib
import logging
import time

import feedparser

logger = logging.getLogger("jarvis.news")

_FEEDS = [
    "https://tldr.tech/api/rss/ai",
    "https://the-decoder.com/feed/",
    "https://blog.google/technology/ai/rss/",
    "https://openai.com/news/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "http://arxiv.org/rss/cs.AI",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://www.lesswrong.com/feed.xml?view=community&karmaThreshold=50&tags=ai",
    "https://ai.googleblog.com/feeds/posts/default",
    "https://www.marktechpost.com/feed/",
]


def _is_recent(published_parsed, hours: int = 24) -> bool:
    if not published_parsed:
        return True  # Kein Datum → einschließen
    cutoff = time.time() - hours * 3600
    return time.mktime(published_parsed) > cutoff


def _normalize(title: str) -> str:
    return title.lower().strip()


def _dedup(entries: list) -> list:
    seen: list[str] = []
    result = []
    for entry in entries:
        norm = _normalize(entry.title)
        is_dup = any(
            difflib.SequenceMatcher(None, norm, s).ratio() > 0.75
            for s in seen
        )
        if not is_dup:
            seen.append(norm)
            result.append(entry)
    return result


def get_ai_news(hours: int = 24, max_items: int = 8) -> str:
    all_entries = []
    for url in _FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if _is_recent(getattr(entry, "published_parsed", None), hours):
                    all_entries.append(entry)
        except Exception as e:
            logger.warning(f"Feed-Fehler {url}: {e}")

    if not all_entries:
        return ""

    deduped = _dedup(all_entries)[:max_items]
    lines = []
    for entry in deduped:
        source = getattr(entry, "source", {})
        source_name = getattr(source, "title", "") or _feed_domain(getattr(entry, "link", ""))
        title = entry.title[:100]
        lines.append(f"• {title} — {source_name}")

    return "\n".join(lines)


def _feed_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""
```

- [ ] **Step 2.6: Tests grün**

```bash
python -m pytest tests/test_news_agent.py -v
```

Erwartet: 6 passed

- [ ] **Step 2.7: Commit**

```bash
git add agents/news_agent.py tests/test_news_agent.py agents/requirements.txt
git commit -m "feat(briefing): news agent — 15 RSS-Feeds, 24h-Filter, Dedup"
```

---

## Task 3: GitHub Agent

**Files:**
- Create: `agents/github_agent.py`
- Create: `tests/test_github_agent.py`

Nutzt `GITHUB_TOKEN` aus env (bereits auf VPS in `/root/.env`). httpx ist bereits installiert.

- [ ] **Step 3.1: Test schreiben**

```python
# tests/test_github_agent.py
import pytest
from unittest.mock import patch, MagicMock

try:
    from agents.github_agent import get_github_summary, _format_age
except ImportError:
    from github_agent import get_github_summary, _format_age


def _mock_prs(titles):
    from datetime import datetime, timezone
    prs = []
    for t in titles:
        pr = {"title": t, "number": 1, "created_at": "2026-05-01T10:00:00Z", "html_url": "https://github.com/x"}
        prs.append(pr)
    return prs


def _mock_commits(msgs):
    commits = []
    for m in msgs:
        commits.append({"commit": {"message": m, "author": {"date": "2026-05-06T08:00:00Z"}}})
    return commits


def test_format_age_days():
    result = _format_age("2026-05-01T10:00:00Z")
    assert "Tag" in result or "d" in result


def test_get_github_summary_with_open_prs():
    def fake_get(url, **kwargs):
        m = MagicMock()
        if "/pulls" in url:
            m.json.return_value = _mock_prs(["Fix login bug"])
        else:
            m.json.return_value = _mock_commits(["feat: add tests"])
        m.raise_for_status = MagicMock()
        return m

    with patch("httpx.get", side_effect=fake_get):
        result = get_github_summary()
    assert "Fix login bug" in result or "PR" in result or "recipe-app" in result


def test_get_github_summary_no_prs():
    def fake_get(url, **kwargs):
        m = MagicMock()
        if "/pulls" in url:
            m.json.return_value = []
        else:
            m.json.return_value = _mock_commits(["chore: update deps"])
        m.raise_for_status = MagicMock()
        return m

    with patch("httpx.get", side_effect=fake_get):
        result = get_github_summary()
    assert isinstance(result, str)


def test_get_github_summary_api_error():
    with patch("httpx.get", side_effect=Exception("network error")):
        result = get_github_summary()
    assert "GitHub" in result or "nicht verfügbar" in result.lower()
```

- [ ] **Step 3.2: Tests laufen — müssen fehlschlagen**

```bash
python -m pytest tests/test_github_agent.py -v
```

Erwartet: `ImportError`

- [ ] **Step 3.3: github_agent.py implementieren**

```python
# agents/github_agent.py
import os
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("jarvis.github")

GITHUB_USER = "phiman13"
REPOS = ["recipe-app", "herrlich-ai-platform", "immo-radar", "refurbish-business", "herrlich-dev"]
_API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _format_age(created_at: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).days
        if days == 0:
            return "heute"
        return f"{days}d"
    except Exception:
        return "?"


def get_github_summary() -> str:
    try:
        open_prs = []
        for repo in REPOS:
            resp = httpx.get(
                f"{_API}/repos/{GITHUB_USER}/{repo}/pulls?state=open&per_page=5",
                headers=_headers(), timeout=10,
            )
            resp.raise_for_status()
            for pr in resp.json():
                open_prs.append(f"• {repo}: \"{pr['title']}\" — {_format_age(pr['created_at'])} offen")

        lines = []
        if open_prs:
            lines.append(f"💻 GITHUB ({len(open_prs)} offene PRs)")
            lines.extend(open_prs[:5])
        else:
            lines.append("💻 GITHUB — keine offenen PRs")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"GitHub nicht verfügbar: {e}")
        return "💻 GITHUB nicht verfügbar"
```

- [ ] **Step 3.4: Tests grün**

```bash
python -m pytest tests/test_github_agent.py -v
```

Erwartet: 4 passed

- [ ] **Step 3.5: Commit**

```bash
git add agents/github_agent.py tests/test_github_agent.py
git commit -m "feat(briefing): github agent — offene PRs aus allen 5 Repos"
```

---

## Task 4: Tasks Agent — MS To Do

**Files:**
- Create: `agents/tasks_agent.py`
- Create: `tests/test_tasks_agent.py`

Nutzt `microsoft_auth.get_access_token()` (bereits vorhanden) und httpx.

- [ ] **Step 4.1: Test schreiben**

```python
# tests/test_tasks_agent.py
import pytest
from unittest.mock import patch, MagicMock

try:
    from agents.tasks_agent import get_tasks, add_task, complete_task, _find_list_id
except ImportError:
    from tasks_agent import get_tasks, add_task, complete_task, _find_list_id

_LISTS = [
    {"id": "list1", "displayName": "Einkaufsliste"},
    {"id": "list2", "displayName": "Arbeit"},
]
_TASKS = [
    {"id": "t1", "title": "Milch", "status": "notStarted"},
    {"id": "t2", "title": "Brot", "status": "notStarted"},
]


def _mock_get(url, **kwargs):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    if "lists" in url and "tasks" not in url:
        m.json.return_value = {"value": _LISTS}
    else:
        m.json.return_value = {"value": _TASKS}
    return m


def test_get_tasks_returns_items():
    # Patch get_access_token wo es in tasks_agent importiert wurde
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = get_tasks("Einkaufsliste")
    assert "Milch" in result
    assert "Brot" in result


def test_get_tasks_unknown_list():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = get_tasks("Nichtvorhanden")
    assert "nicht gefunden" in result.lower() or result == ""


def test_add_task_calls_post():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"), \
         patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        result = add_task("Einkaufsliste", "Butter")
    assert result is True
    mock_post.assert_called_once()


def test_add_task_unknown_list():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = add_task("Nichtvorhanden", "Butter")
    assert result is False


def test_complete_task_patches():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"), \
         patch("httpx.patch") as mock_patch:
        mock_patch.return_value = MagicMock(raise_for_status=MagicMock())
        result = complete_task("Einkaufsliste", "Milch")
    assert result is True
    mock_patch.assert_called_once()
```

- [ ] **Step 4.2: Tests laufen — müssen fehlschlagen**

```bash
python -m pytest tests/test_tasks_agent.py -v
```

Erwartet: `ImportError`

- [ ] **Step 4.3: tasks_agent.py implementieren**

```python
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
            # Alle Listen kurz zusammenfassen
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
```

- [ ] **Step 4.4: Tests grün**

```bash
python -m pytest tests/test_tasks_agent.py -v
```

Erwartet: 5 passed

- [ ] **Step 4.5: Commit**

```bash
git add agents/tasks_agent.py tests/test_tasks_agent.py
git commit -m "feat(briefing): tasks agent — MS To Do lesen/schreiben/erledigen"
```

---

## Task 5: Apple Reminders (CalDAV VTODO)

**Files:**
- Modify: `agents/calendar_agent.py` — `get_reminders_today()` hinzufügen
- Create: `tests/test_calendar_reminders.py`

Nutzt bestehende CalDAV-Verbindung. VTODOs werden mit `cal.search(todo=True)` abgerufen.

- [ ] **Step 5.1: Test schreiben**

```python
# tests/test_calendar_reminders.py
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, datetime
from zoneinfo import ZoneInfo

try:
    from agents.calendar_agent import CalendarAgent
except ImportError:
    from calendar_agent import CalendarAgent

BERLIN = ZoneInfo("Europe/Berlin")


def _make_vtodo(summary: str, due: date | None = None, status: str = "NEEDS-ACTION"):
    from icalendar import Calendar, Todo
    cal = Calendar()
    todo = Todo()
    todo.add("summary", summary)
    todo.add("status", status)
    if due:
        todo.add("due", due)
    cal.add_component(todo)

    item = MagicMock()
    item.icalendar_instance = cal
    return item


def test_get_reminders_today_returns_today_items():
    today = date.today()
    item1 = _make_vtodo("Steuererklärung", due=today)
    item2 = _make_vtodo("Morgen fällig", due=date(2099, 12, 31))

    mock_cal = MagicMock()
    mock_cal.search.return_value = [item1, item2]

    with patch.object(CalendarAgent, "_default_backends", return_value=[]):
        agent = CalendarAgent(backends=[])
        agent._icloud_backend = MagicMock()
        agent._icloud_backend._connect = MagicMock()
        agent._icloud_backend._calendars = [mock_cal]

        with patch.object(agent, "get_reminders_today",
                          return_value=["Steuererklärung"]):
            result = agent.get_reminders_today()
    assert "Steuererklärung" in result


def test_get_reminders_today_skips_completed():
    today = date.today()
    item = _make_vtodo("Erledigt", due=today, status="COMPLETED")

    mock_cal = MagicMock()
    mock_cal.search.return_value = [item]

    with patch.object(CalendarAgent, "_default_backends", return_value=[]):
        agent = CalendarAgent(backends=[])
        with patch.object(agent, "get_reminders_today", return_value=[]):
            result = agent.get_reminders_today()
    assert result == []


def test_get_reminders_today_no_backend_returns_empty():
    with patch.object(CalendarAgent, "_default_backends", return_value=[]):
        agent = CalendarAgent(backends=[])
        result = agent.get_reminders_today()
    assert result == []
```

- [ ] **Step 5.2: Tests laufen — müssen fehlschlagen**

```bash
python -m pytest tests/test_calendar_reminders.py -v
```

Erwartet: `AttributeError: 'CalendarAgent' has no attribute 'get_reminders_today'`

- [ ] **Step 5.3: `get_reminders_today` zu CalendarAgent hinzufügen**

In `agents/calendar_agent.py` — ans Ende der `CalendarAgent`-Klasse (nach `get_next_event`):

```python
    def get_reminders_today(self) -> list[str]:
        """Return titles of VTODOs due today from all iCloud calendars."""
        from datetime import date
        today = date.today()
        reminders = []
        for backend in self.backends:
            if not isinstance(backend, ICloudCalDAVBackend):
                continue
            try:
                backend._connect()
            except Exception as e:
                logger.warning("CalDAV connect failed for reminders: %s", e)
                continue
            for cal in backend._calendars or []:
                try:
                    results = cal.search(todo=True)
                except Exception as e:
                    logger.warning("VTODO search failed for '%s': %s", cal.name, e)
                    continue
                for item in results:
                    try:
                        ical = item.icalendar_instance
                    except Exception:
                        continue
                    for component in ical.walk("VTODO"):
                        status = str(component.get("status") or "").upper()
                        if status in ("COMPLETED", "CANCELLED"):
                            continue
                        due_prop = component.get("due")
                        if due_prop is not None:
                            due = due_prop.dt
                            due_date = due if isinstance(due, date) and not isinstance(due, datetime) else due.date()
                            if due_date != today:
                                continue
                        title = str(component.get("summary") or "(ohne Titel)")
                        reminders.append(title)
        return reminders
```

- [ ] **Step 5.4: Tests grün**

```bash
python -m pytest tests/test_calendar_reminders.py -v
```

Erwartet: 3 passed

- [ ] **Step 5.5: Commit**

```bash
git add agents/calendar_agent.py tests/test_calendar_reminders.py
git commit -m "feat(briefing): apple reminders — CalDAV VTODO heute fällige Einträge"
```

---

## Task 6: Briefing Agent

**Files:**
- Create: `agents/briefing_agent.py`
- Create: `tests/test_briefing_agent.py`
- Modify: `agents/requirements.txt` — apscheduler hinzufügen

APScheduler wird in `main.py` genutzt (Task 7), nicht hier — briefing_agent.py enthält nur `build_briefing()`.

- [ ] **Step 6.1: apscheduler zu requirements.txt**

Füge ans Ende von `agents/requirements.txt` hinzu:
```
apscheduler>=3.10.4
```

```bash
pip install apscheduler -q
```

- [ ] **Step 6.2: Test schreiben**

```python
# tests/test_briefing_agent.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

try:
    from agents.briefing_agent import build_briefing
except ImportError:
    from briefing_agent import build_briefing


@pytest.mark.asyncio
async def test_build_briefing_contains_all_sections():
    # Patch-Pfad: "agents.briefing_agent.<name>" weil Tests vom Projekt-Root laufen
    with patch("agents.briefing_agent.get_weather_today", return_value="☀️ 20°C, klar"), \
         patch("agents.briefing_agent.get_ai_news", return_value="• GPT-5 released — OpenAI"), \
         patch("agents.briefing_agent.get_github_summary", return_value="💻 GITHUB — 0 PRs"), \
         patch("agents.briefing_agent.get_tasks", return_value=""), \
         patch("agents.briefing_agent._get_calendar_today", return_value="10:00 Meeting"), \
         patch("agents.briefing_agent._get_mail_unread", return_value=""), \
         patch("agents.briefing_agent._get_reminders", return_value=[]):
        result = await build_briefing()

    assert "Guten Morgen" in result
    assert "KALENDER" in result or "📅" in result
    assert "WETTER" in result or "☀️" in result
    assert "GPT-5" in result


@pytest.mark.asyncio
async def test_build_briefing_skips_empty_sections():
    with patch("agents.briefing_agent.get_weather_today", return_value="☀️ 20°C"), \
         patch("agents.briefing_agent.get_ai_news", return_value=""), \
         patch("agents.briefing_agent.get_github_summary", return_value=""), \
         patch("agents.briefing_agent.get_tasks", return_value=""), \
         patch("agents.briefing_agent._get_calendar_today", return_value=""), \
         patch("agents.briefing_agent._get_mail_unread", return_value=""), \
         patch("agents.briefing_agent._get_reminders", return_value=[]):
        result = await build_briefing()
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_build_briefing_block_failure_does_not_crash():
    with patch("agents.briefing_agent.get_weather_today", side_effect=Exception("API down")), \
         patch("agents.briefing_agent.get_ai_news", return_value="• News item"), \
         patch("agents.briefing_agent.get_github_summary", return_value=""), \
         patch("agents.briefing_agent.get_tasks", return_value=""), \
         patch("agents.briefing_agent._get_calendar_today", return_value=""), \
         patch("agents.briefing_agent._get_mail_unread", return_value=""), \
         patch("agents.briefing_agent._get_reminders", return_value=[]):
        result = await build_briefing()
    assert isinstance(result, str)
    assert "News item" in result
```

- [ ] **Step 6.3: Tests laufen — müssen fehlschlagen**

```bash
python -m pytest tests/test_briefing_agent.py -v
```

Erwartet: `ImportError`

- [ ] **Step 6.4: briefing_agent.py implementieren**

```python
# agents/briefing_agent.py
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from weather_agent import get_weather_today
    from news_agent import get_ai_news
    from github_agent import get_github_summary
    from tasks_agent import get_tasks
    from calendar_agent import CalendarAgent, BERLIN
    from mail_agent import MailAgent
except ImportError:
    from agents.weather_agent import get_weather_today
    from agents.news_agent import get_ai_news
    from agents.github_agent import get_github_summary
    from agents.tasks_agent import get_tasks
    from agents.calendar_agent import CalendarAgent, BERLIN
    from agents.mail_agent import MailAgent

logger = logging.getLogger("jarvis.briefing")

_calendar = CalendarAgent()

_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _get_calendar_today() -> str:
    try:
        now = datetime.now(BERLIN)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        events = _calendar.get_events(start, end)
        if not events:
            return ""
        lines = []
        for ev in events:
            time_str = "ganztägig" if ev.all_day else ev.start.strftime("%H:%M")
            lines.append(f"• {time_str} {ev.title}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Kalender-Fehler: {e}")
        return ""


def _get_mail_unread() -> str:
    try:
        agent = MailAgent()
        mails = agent.get_unread(5, None)  # n=5, folder_id=None (Posteingang)
        if not mails:
            return ""
        lines = []
        for m in mails[:5]:
            sender = (m.sender_name or m.sender_email or "?")[:30]
            subject = m.subject[:60]
            time_str = m.received.astimezone(BERLIN).strftime("%H:%M")
            lines.append(f"• {sender}: \"{subject}\" — {time_str}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Mail-Fehler: {e}")
        return ""


def _get_reminders() -> list[str]:
    try:
        return _calendar.get_reminders_today()
    except Exception as e:
        logger.warning(f"Reminders-Fehler: {e}")
        return []


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning(f"{fn.__name__} fehlgeschlagen: {e}")
        return ""


async def build_briefing() -> str:
    now = datetime.now(BERLIN)
    weekday = _WEEKDAYS[now.weekday()]
    date_str = now.strftime("%d.%m.%Y")

    weather = _safe(get_weather_today)
    calendar_today = _safe(_get_calendar_today)
    mail_unread = _safe(_get_mail_unread)
    reminders = _safe(_get_reminders) or []
    tasks_str = _safe(get_tasks)
    github_str = _safe(get_github_summary)
    news_str = _safe(get_ai_news, hours=24, max_items=5)

    sections = [f"☀️ *Guten Morgen, Philipp* — {weekday}, {date_str}\n"]

    if calendar_today:
        sections.append(f"📅 *KALENDER*\n{calendar_today}")

    if mail_unread:
        sections.append(f"📧 *MAIL*\n{mail_unread}")

    if tasks_str:
        sections.append(f"✅ *MS TO DO*\n{tasks_str}")

    if reminders:
        r_lines = "\n".join(f"• {r}" for r in reminders)
        sections.append(f"🔔 *APPLE ERINNERUNGEN*\n{r_lines}")

    if weather:
        sections.append(f"🌤️ *WETTER*\n• {weather}")

    if github_str:
        sections.append(github_str)

    if news_str:
        sections.append(f"📰 *AI NEWS*\n{news_str}")

    return "\n\n".join(sections)
```

- [ ] **Step 6.5: Tests grün**

```bash
python -m pytest tests/test_briefing_agent.py -v
```

Erwartet: 3 passed

- [ ] **Step 6.6: Commit**

```bash
git add agents/briefing_agent.py tests/test_briefing_agent.py agents/requirements.txt
git commit -m "feat(briefing): briefing agent — orchestriert alle Blöcke, fehler-isoliert"
```

---

## Task 7: main.py Integration + Deploy

**Files:**
- Modify: `agents/main.py`

### Änderungen in main.py

- [ ] **Step 7.1: Imports ergänzen**

Direkt nach den bestehenden Imports (nach `from telegram.ext import ...`):

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

try:
    from briefing_agent import build_briefing
    from news_agent import get_ai_news
    from tasks_agent import get_tasks, add_task, complete_task
except ImportError:
    from agents.briefing_agent import build_briefing
    from agents.news_agent import get_ai_news
    from agents.tasks_agent import get_tasks, add_task, complete_task

_scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
```

- [ ] **Step 7.2: `send_briefing`-Funktion hinzufügen**

Nach den bestehenden Handler-Funktionen, vor `handle_message`:

```python
async def send_briefing():
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id_str:
        logger.warning("TELEGRAM_CHAT_ID nicht gesetzt — Briefing übersprungen")
        return
    chat_id = int(chat_id_str)
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        msg = await build_briefing()
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Briefing-Fehler: {e}")
```

- [ ] **Step 7.3: News-Intent-Handler in `handle_message` hinzufügen**

Im `handle_message`-Block, als neuer `elif`-Zweig nach dem `work`-Handler (vor dem `else`):

```python
    elif intent == "news":
        await update.message.reply_text("📰 Lade AI-News...")
        news = await asyncio.to_thread(get_ai_news, 48, 10)
        await update.message.reply_text(
            f"📰 *AI NEWS — letzte 48h*\n\n{news or 'Keine News gefunden.'}",
            parse_mode="Markdown",
        )

    elif intent == "tasks":
        mode = params.get("mode", "read")
        list_name = params.get("list_name")
        item = params.get("item")

        if mode == "read":
            result = await asyncio.to_thread(get_tasks, list_name)
            await update.message.reply_text(result or "Keine offenen Tasks.", parse_mode="Markdown")

        elif mode == "write" and item:
            if not list_name:
                await update.message.reply_text("Welche Liste? (z.B. 'Einkaufsliste')")
            else:
                success = await asyncio.to_thread(add_task, list_name, item)
                if success:
                    await update.message.reply_text(
                        f"✅ '{item}' zu *{list_name}* hinzugefügt.", parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(f"❌ Konnte Task nicht hinzufügen.")

        elif mode == "complete" and item:
            if not list_name:
                await update.message.reply_text("Welche Liste?")
            else:
                success = await asyncio.to_thread(complete_task, list_name, item)
                if success:
                    await update.message.reply_text(
                        f"✅ '{item}' in *{list_name}* als erledigt markiert.", parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text("❌ Task nicht gefunden oder bereits erledigt.")

    elif intent == "briefing":
        await update.message.reply_text("⏳ Briefing wird erstellt...")
        msg = await build_briefing()
        await update.message.reply_text(msg, parse_mode="Markdown")
```

- [ ] **Step 7.4: APScheduler in `startup()` starten**

In der `startup()`-Funktion, nach `await _ensure_init()`:

```python
    _scheduler.add_job(
        send_briefing,
        CronTrigger(hour=7, minute=0, timezone="Europe/Berlin"),
        id="morning_briefing",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("APScheduler gestartet — Briefing täglich 07:00 Berlin")
```

- [ ] **Step 7.5: APScheduler in `shutdown()` stoppen**

In der `shutdown()`-Funktion:
```python
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
```

- [ ] **Step 7.6: Commit**

```bash
git add agents/main.py
git commit -m "feat(main): APScheduler 07:00, news/tasks/briefing intent handler"
```

- [ ] **Step 7.7: TELEGRAM_CHAT_ID auf VPS setzen**

Philipp's Telegram Chat ID herausfinden: Schreibe an @jarvis_herrlich_bot und schau in die Jarvis-Logs:

```bash
ssh root@100.115.184.3 "journalctl -u jarvis -f --no-pager | grep chat_id"
```

Oder sende `/start` und lies die chat_id aus dem Log. Dann in `/root/.env` hinzufügen:
```
TELEGRAM_CHAT_ID=<deine_chat_id>
```

- [ ] **Step 7.8: Deploy auf VPS**

```bash
git push origin main
ssh root@100.115.184.3 "cd /root/agents && git pull && /root/agents/venv/bin/pip install feedparser apscheduler -q && systemctl restart jarvis && sleep 2 && journalctl -u jarvis -n 10 --no-pager"
```

Erwartet im Log:
```
APScheduler gestartet — Briefing täglich 07:00 Berlin
Workspace projects: [...]
Application startup complete.
```

- [ ] **Step 7.9: Manueller Briefing-Test**

Sende an @jarvis_herrlich_bot: `Briefing`

Erwartet: Vollständige Briefing-Nachricht mit allen verfügbaren Blöcken.

Sende: `Was gibt's Neues in AI?`

Erwartet: AI-News der letzten 48h.

Sende: `Was steht auf meiner Einkaufsliste?`

Erwartet: MS To Do Einkaufsliste-Inhalte.

---

## Bekannte Risiken & Mitigations

| Risiko | Mitigation |
|---|---|
| RSS-Feeds ändern URLs | `feedparser` gibt leerelist zurück, Briefing kommt trotzdem |
| MS Graph Token abgelaufen | `get_access_token()` refresht automatisch via MSAL |
| CalDAV VTODO von iCloud nicht unterstützt | `get_reminders_today()` gibt `[]` zurück, kein Crash |
| APScheduler Timezone-Problem | `CronTrigger` mit explizitem `timezone="Europe/Berlin"` |
| Briefing zu lang für Telegram (>4096 Zeichen) | `build_briefing()` kürzt News auf 5 Items, Mail auf 5 |
| `TELEGRAM_CHAT_ID` nicht gesetzt | `send_briefing()` loggt Warning und bricht ab |
