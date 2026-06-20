"""
weather.py — Real-time and forecast weather for EventIQ.

Uses Open-Meteo (https://open-meteo.com/) — completely free, no API key required.

Public API:
    get_current_weather(lat, lon)  -> dict
    get_weather_impact(lat, lon)   -> dict  (impact score + multiplier for resource planner)
    get_weather_summary(lat, lon)  -> str   (human-readable one-liner for LLM brief)
    get_forecast(lat, lon, hours)  -> list  (hourly forecast dicts)
"""

import time
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# WMO weather interpretation codes → human label + severity (0=none, 3=severe)
# ---------------------------------------------------------------------------
_WMO_CODES: dict[int, tuple[str, int]] = {
    0:  ("Clear sky",              0),
    1:  ("Mainly clear",           0),
    2:  ("Partly cloudy",          0),
    3:  ("Overcast",               0),
    45: ("Foggy",                  2),
    48: ("Depositing rime fog",    2),
    51: ("Light drizzle",          1),
    53: ("Moderate drizzle",       1),
    55: ("Dense drizzle",          1),
    56: ("Freezing drizzle",       2),
    57: ("Heavy freezing drizzle", 2),
    61: ("Slight rain",            1),
    63: ("Moderate rain",          2),
    65: ("Heavy rain",             2),
    66: ("Light freezing rain",    2),
    67: ("Heavy freezing rain",    3),
    71: ("Slight snow",            1),
    73: ("Moderate snow",          2),
    75: ("Heavy snow",             3),
    77: ("Snow grains",            1),
    80: ("Slight rain showers",    1),
    81: ("Moderate rain showers",  2),
    82: ("Violent rain showers",   3),
    85: ("Slight snow showers",    1),
    86: ("Heavy snow showers",     2),
    95: ("Thunderstorm",           3),
    96: ("Thunderstorm w/ hail",   3),
    99: ("Thunderstorm w/ heavy hail", 3),
}

# Severity → resource multiplier and congestion adder
_SEVERITY_MULTIPLIER = {0: 1.0, 1: 1.15, 2: 1.30, 3: 1.50}
_SEVERITY_CONGESTION_ADDER = {0: 0, 1: 5, 2: 12, 3: 20}  # points added to congestion score
_SEVERITY_LABEL = {0: "None", 1: "Low", 2: "Moderate", 3: "Severe"}

_CACHE: dict = {}  # simple in-process cache {key: (timestamp, data)}
_CACHE_TTL = 600   # 10 minutes


def _cache_get(key: str):
    entry = _CACHE.get(key)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, data):
    _CACHE[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------

def _fetch_open_meteo(lat: float, lon: float, forecast_hours: int = 1) -> Optional[dict]:
    """Call Open-Meteo current + hourly forecast endpoint."""
    key = f"{round(lat,3)}:{round(lon,3)}:{forecast_hours}"
    cached = _cache_get(key)
    if cached:
        return cached

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "weather_code",
            "wind_speed_10m",
            "visibility",
        ],
        "hourly": [
            "temperature_2m",
            "precipitation_probability",
            "precipitation",
            "weather_code",
            "wind_speed_10m",
            "visibility",
        ],
        "forecast_hours": max(forecast_hours, 6),
        "timezone": "Asia/Kolkata",
        "wind_speed_unit": "kmh",
    }
    try:
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        _cache_set(key, data)
        return data
    except Exception:
        return None


def _parse_current(data: dict) -> dict:
    """Extract current weather fields from Open-Meteo response."""
    c = data.get("current", {})
    code = int(c.get("weather_code", 0) or 0)
    label, severity = _WMO_CODES.get(code, ("Unknown", 0))
    temp = c.get("temperature_2m")
    feels = c.get("apparent_temperature")
    humidity = c.get("relative_humidity_2m")
    precip = c.get("precipitation", 0) or 0
    wind = c.get("wind_speed_10m", 0) or 0
    visibility = c.get("visibility")        # metres

    # Adjust severity up for low visibility or high wind
    if visibility is not None and float(visibility) < 500:
        severity = max(severity, 2)
    if float(wind) > 60:
        severity = max(severity, 2)
    if float(wind) > 90:
        severity = max(severity, 3)

    return {
        "temperature_c": round(float(temp), 1) if temp is not None else None,
        "feels_like_c": round(float(feels), 1) if feels is not None else None,
        "humidity_pct": int(humidity) if humidity is not None else None,
        "precipitation_mm": round(float(precip), 1),
        "wind_kmh": round(float(wind), 1),
        "visibility_m": int(visibility) if visibility is not None else None,
        "weather_code": code,
        "condition": label,
        "severity": severity,
        "severity_label": _SEVERITY_LABEL[severity],
        "resource_multiplier": _SEVERITY_MULTIPLIER[severity],
        "congestion_adder": _SEVERITY_CONGESTION_ADDER[severity],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_current_weather(lat: float, lon: float) -> dict:
    """
    Fetch current weather at (lat, lon).

    Returns a dict with condition, temperature, wind, precipitation, severity,
    resource_multiplier, and congestion_adder. Returns a safe default on failure.
    """
    data = _fetch_open_meteo(lat, lon, forecast_hours=1)
    if data:
        return _parse_current(data)

    # Graceful degradation — return clear-sky defaults so rest of pipeline works
    return {
        "temperature_c": None,
        "feels_like_c": None,
        "humidity_pct": None,
        "precipitation_mm": 0.0,
        "wind_kmh": 0.0,
        "visibility_m": None,
        "weather_code": 0,
        "condition": "Unknown (offline)",
        "severity": 0,
        "severity_label": "None",
        "resource_multiplier": 1.0,
        "congestion_adder": 0,
        "offline": True,
    }


def get_weather_impact(lat: float, lon: float) -> dict:
    """
    Returns weather impact metadata used by resource_planner and congestion scoring.

    Keys:
        severity          int  0-3
        severity_label    str  None/Low/Moderate/Severe
        resource_multiplier  float  (multiply base resource counts)
        congestion_adder  int  (add to congestion score after scaling)
        summary           str  short description
        condition         str  WMO label
        precipitation_mm  float
        wind_kmh          float
        temperature_c     float | None
    """
    w = get_current_weather(lat, lon)
    summary_parts = [w["condition"]]
    if w.get("temperature_c") is not None:
        summary_parts.append(f"{w['temperature_c']}°C")
    if w["precipitation_mm"] > 0:
        summary_parts.append(f"{w['precipitation_mm']}mm rain")
    if w["wind_kmh"] > 30:
        summary_parts.append(f"wind {w['wind_kmh']} km/h")

    return {
        **w,
        "summary": ", ".join(summary_parts),
    }


def get_weather_summary(lat: float, lon: float) -> str:
    """One-liner weather string suitable for LLM context / UI display."""
    w = get_weather_impact(lat, lon)
    if w.get("offline"):
        return "Weather data unavailable."
    parts = [f"{w['condition']}"]
    if w.get("temperature_c") is not None:
        parts.append(f"{w['temperature_c']}°C (feels {w.get('feels_like_c','?')}°C)")
    if w["precipitation_mm"] > 0:
        parts.append(f"precipitation {w['precipitation_mm']} mm")
    if w["wind_kmh"] > 20:
        parts.append(f"wind {w['wind_kmh']} km/h")
    if w.get("visibility_m") and w["visibility_m"] < 1000:
        parts.append(f"visibility {w['visibility_m']} m")
    impact = w["severity_label"]
    if impact != "None":
        parts.append(f"[traffic impact: {impact}]")
    return " | ".join(parts)


def get_forecast(lat: float, lon: float, hours: int = 6) -> list:
    """
    Hourly weather forecast for the next `hours` hours.

    Returns list of dicts: [{hour_label, temperature_c, precipitation_mm,
                              precipitation_prob_pct, wind_kmh, condition,
                              severity, resource_multiplier, congestion_adder}]
    """
    data = _fetch_open_meteo(lat, lon, forecast_hours=hours)
    if not data:
        return []

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precip = hourly.get("precipitation", [])
    precip_prob = hourly.get("precipitation_probability", [])
    wind = hourly.get("wind_speed_10m", [])
    codes = hourly.get("weather_code", [])

    results = []
    for i in range(min(hours, len(times))):
        code = int(codes[i] or 0) if i < len(codes) else 0
        label, severity = _WMO_CODES.get(code, ("Unknown", 0))
        results.append({
            "hour_label": str(times[i])[11:16] if i < len(times) else f"T+{i}",
            "temperature_c": round(float(temps[i]), 1) if i < len(temps) and temps[i] is not None else None,
            "precipitation_mm": round(float(precip[i]), 1) if i < len(precip) and precip[i] is not None else 0.0,
            "precipitation_prob_pct": int(precip_prob[i]) if i < len(precip_prob) and precip_prob[i] is not None else 0,
            "wind_kmh": round(float(wind[i]), 1) if i < len(wind) and wind[i] is not None else 0.0,
            "weather_code": code,
            "condition": label,
            "severity": severity,
            "resource_multiplier": _SEVERITY_MULTIPLIER[severity],
            "congestion_adder": _SEVERITY_CONGESTION_ADDER[severity],
        })
    return results
