"""Current weather via Open-Meteo - free, no API key, no signup.

  geocoding-api.open-meteo.com/v1/search?name=Pune   -> lat/lon
  api.open-meteo.com/v1/forecast?latitude=..&current=..  -> conditions
"""

from __future__ import annotations

from typing import Any

import httpx

from nexa.tools.base import Tool

_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST = "https://api.open-meteo.com/v1/forecast"

# WMO weather-interpretation codes -> words
_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "light snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with heavy hail",
}


class WeatherTool(Tool):
    name = "get_weather"
    description = (
        "Current weather conditions for a place. If the user does not name a "
        "place, omit 'location' and it uses their default city."
    )
    parameters = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City or place name, e.g. 'Pune' or 'Berlin'.",
            }
        },
        "required": [],
    }

    def __init__(self, default_location: str, client: httpx.Client | None = None) -> None:
        self._default = default_location
        self._client = client or httpx.Client(timeout=httpx.Timeout(10.0))

    def run(self, location: str | None = None, **kwargs: Any) -> str:
        place = (location or self._default or "").strip()
        if not place:
            return "No location given and no default is set."

        try:
            geo = self._client.get(_GEOCODE, params={"name": place, "count": 1, "language": "en"}).json()
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't reach the weather service ({exc})."
        results = geo.get("results") or []
        if not results:
            return f"I couldn't find a place called {place}."
        r = results[0]
        name = ", ".join(x for x in (r.get("name"), r.get("country")) if x)

        try:
            cur = self._client.get(
                _FORECAST,
                params={
                    "latitude": r["latitude"],
                    "longitude": r["longitude"],
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                },
            ).json()["current"]
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't get conditions for {name} ({exc})."

        desc = _CODES.get(int(cur.get("weather_code", -1)), "unclear conditions")
        return (
            f"{name}: {desc}, {round(cur['temperature_2m'])}°C "
            f"(feels like {round(cur['apparent_temperature'])}°C), "
            f"humidity {round(cur['relative_humidity_2m'])}%, "
            f"wind {round(cur['wind_speed_10m'])} km/h."
        )
