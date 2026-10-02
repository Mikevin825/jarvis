"""Weather, via Open-Meteo.

Read-only and needs no API key. Also a useful test case: it is the tool most
likely to fail (bad city name, no network), so it exercises the "explain the
failure, don't crash" path.
"""

from __future__ import annotations

import httpx

from .base import Tool, ToolError

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes, as used by Open-Meteo.
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snowfall", 73: "moderate snowfall", 75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}

_PARAMS = {
    "type": "OBJECT",
    "properties": {
        "city": {
            "type": "STRING",
            "description": "The city to report weather for, e.g. 'Lagos' or 'Paris, France'.",
        },
        "units": {
            "type": "STRING",
            "description": "Either 'celsius' (default) or 'fahrenheit'.",
            "enum": ["celsius", "fahrenheit"],
        },
    },
    "required": ["city"],
}

_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


def get_weather(city: str, units: str = "celsius") -> str:
    city = (city or "").strip()
    if not city:
        raise ToolError("No city was given. Ask the user which city they mean.")

    try:
        geo = httpx.get(
            GEOCODE_URL, params={"name": city, "count": 1}, timeout=_TIMEOUT
        )
        geo.raise_for_status()
        results = geo.json().get("results") or []
    except httpx.TimeoutException as exc:
        raise ToolError("The weather service did not respond in time.") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach the weather service: {exc}") from exc

    if not results:
        raise ToolError(
            f"I could not find a place called '{city}'. Try a larger nearby city."
        )

    place = results[0]
    lat, lon = place["latitude"], place["longitude"]
    label = ", ".join(
        part for part in (place.get("name"), place.get("country")) if part
    )

    fahrenheit = (units or "celsius").lower().startswith("f")
    try:
        fc = httpx.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                "temperature_unit": "fahrenheit" if fahrenheit else "celsius",
                "wind_speed_unit": "mph" if fahrenheit else "kmh",
                "timezone": "auto",
            },
            timeout=_TIMEOUT,
        )
        fc.raise_for_status()
        current = fc.json().get("current") or {}
    except httpx.TimeoutException as exc:
        raise ToolError("The weather service did not respond in time.") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach the weather service: {exc}") from exc

    if not current:
        raise ToolError(f"No current weather was returned for {label}.")

    temp_unit = "°F" if fahrenheit else "°C"
    wind_unit = "mph" if fahrenheit else "km/h"
    condition = _WMO.get(current.get("weather_code"), "unknown conditions")

    return (
        f"{label}: {condition}, {current.get('temperature_2m')}{temp_unit}, "
        f"wind {current.get('wind_speed_10m')} {wind_unit}, "
        f"humidity {current.get('relative_humidity_2m')}%. "
        f"Local time {current.get('time')}."
    )


def build() -> list[Tool]:
    return [
        Tool(
            name="get_weather",
            description=(
                "Use this to look up the current weather conditions in a city. "
                "Call it when the user asks about the weather, temperature, or "
                "conditions anywhere."
            ),
            parameters=_PARAMS,
            func=get_weather,
        )
    ]
