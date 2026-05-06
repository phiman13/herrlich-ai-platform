# agents/briefing_agent.py
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
        mails = agent.get_unread(5, None)
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
        logger.warning(f"{getattr(fn, '__name__', repr(fn))} fehlgeschlagen: {e}")
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
