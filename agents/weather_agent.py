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

_WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=48.14&longitude=11.58"
    "&current=temperature_2m,weathercode,precipitation"
    "&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum"
    "&forecast_days=7"
    "&timezone=Europe%2FBerlin"
)


def get_weather(period: str = "today") -> str:
    for attempt in range(2):
        try:
            resp = httpx.get(_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if period == "today":
                cur = data.get("current", {})
                temp = round(cur.get("temperature_2m", 0))
                code = int(cur.get("weathercode", -1))
                precip = cur.get("precipitation", 0.0)
                desc, icon = _WMO_CODES.get(code, ("unbekannt", "🌡️"))
                rain_note = f", {precip:.1f} mm" if precip > 0 else ""
                return f"{icon} {temp}°C, {desc}{rain_note}"

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
                return f"{icon} {max_temps[idx]:.0f}°C / {min_temps[idx]:.0f}°C, {desc}{rain_note}"

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
