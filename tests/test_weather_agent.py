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
