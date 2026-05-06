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
        data = resp.json().get("current", {})
        temp = round(data.get("temperature_2m", 0))
        code = int(data.get("weathercode", -1))
        precip = data.get("precipitation", 0.0)
        desc, icon = _WMO_CODES.get(code, ("unbekannt", "🌡️"))
        rain_note = f", {precip:.1f} mm" if precip > 0 else ""
        return f"{icon} {temp}°C, {desc}{rain_note}"
    except Exception as e:
        logger.warning(f"Wetter nicht verfügbar: {e}")
        return "🌡️ Wetter nicht verfügbar"
