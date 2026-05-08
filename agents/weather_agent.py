import httpx
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("jarvis.weather")

_BERLIN = ZoneInfo("Europe/Berlin")

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

_WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# time_of_day → hour ranges to show
_TIME_SLOTS = {
    "morning": [7, 9],
    "noon": [12],
    "afternoon": [14, 16, 18],
    "evening": [18, 20],
    "night": [21, 23],
}
_DEFAULT_SLOTS = [9, 12, 15, 18, 21]

_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=48.14&longitude=11.58"
    "&current=temperature_2m,weathercode,precipitation"
    "&hourly=temperature_2m,weathercode,precipitation_probability"
    "&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum"
    "&forecast_days=7"
    "&timezone=Europe%2FBerlin"
)


def _fmt_hourly(hourly: dict, date_prefix: str, hours: list[int]) -> list[str]:
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    codes = hourly.get("weathercode", [])
    precip_probs = hourly.get("precipitation_probability", [])

    lines = []
    for i, t in enumerate(times):
        if not t.startswith(date_prefix):
            continue
        hour = int(t[11:13])
        if hour not in hours:
            continue
        temp = round(temps[i]) if i < len(temps) else "?"
        code = int(codes[i]) if i < len(codes) else -1
        prob = precip_probs[i] if i < len(precip_probs) else 0
        desc, icon = _WMO_CODES.get(code, ("unbekannt", "🌡️"))
        rain = f", {prob}% Regen" if prob >= 20 else ""
        lines.append(f"{hour:02d}:00 {icon} {temp}°C, {desc}{rain}")
    return lines


def get_weather(period: str = "today", time_of_day: str | None = None) -> str:
    for attempt in range(2):
        try:
            resp = httpx.get(_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            now = datetime.now(_BERLIN)
            today_str = now.strftime("%Y-%m-%d")

            if period == "today":
                cur = data.get("current", {})
                cur_temp = round(cur.get("temperature_2m", 0))
                cur_code = int(cur.get("weathercode", -1))
                cur_precip = cur.get("precipitation", 0.0)
                cur_desc, cur_icon = _WMO_CODES.get(cur_code, ("unbekannt", "🌡️"))
                rain_note = f", {cur_precip:.1f} mm" if cur_precip > 0 else ""
                header = f"Jetzt: {cur_icon} {cur_temp}°C, {cur_desc}{rain_note}"

                hours = _TIME_SLOTS.get(time_of_day or "", _DEFAULT_SLOTS)
                # only future hours
                hours = [h for h in hours if h > now.hour]
                if not hours:
                    return header

                hourly_lines = _fmt_hourly(data.get("hourly", {}), today_str, hours)
                if hourly_lines:
                    return header + "\n" + "\n".join(hourly_lines)
                return header

            daily = data.get("daily", {})
            dates = daily.get("time", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])
            codes = daily.get("weathercode", [])
            precips = daily.get("precipitation_sum", [])

            if period == "tomorrow":
                if len(dates) < 2:
                    return "Morgen-Wetter nicht verfügbar"
                idx = 1
                desc, icon = _WMO_CODES.get(int(codes[idx]), ("unbekannt", "🌡️"))
                rain_note = f", {precips[idx]:.1f} mm Regen" if precips[idx] > 0 else ""
                header = f"{icon} {max_temps[idx]:.0f}°C / {min_temps[idx]:.0f}°C, {desc}{rain_note}"

                hours = _TIME_SLOTS.get(time_of_day or "", _DEFAULT_SLOTS)
                tomorrow_str = dates[1] if len(dates) > 1 else ""
                hourly_lines = _fmt_hourly(data.get("hourly", {}), tomorrow_str, hours)
                if hourly_lines:
                    return header + "\n" + "\n".join(hourly_lines)
                return header

            # week
            from datetime import date as _date

            lines = []
            for i in range(min(7, len(dates))):
                d = _date.fromisoformat(dates[i])
                day = _WEEKDAYS_DE[d.weekday()]
                desc, icon = _WMO_CODES.get(int(codes[i]), ("unbekannt", "🌡️"))
                lines.append(
                    f"{day} {dates[i][5:]}: {icon} {max_temps[i]:.0f}/{min_temps[i]:.0f}°C, {desc}"
                )
            return "\n".join(lines)

        except Exception as e:
            logger.warning("Wetter nicht verfügbar (Versuch %d): %s", attempt + 1, e)
    return "🌡️ Wetter nicht verfügbar"


def get_weather_today() -> str:
    return get_weather("today")
