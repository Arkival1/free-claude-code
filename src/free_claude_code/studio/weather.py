"""Weather now and the next few days for any place, from Open-Meteo (no key)."""

import re
from datetime import date

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_WMO = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "icy fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "heavy freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "violent showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "severe thunderstorms with hail",
}
_ASK = re.compile(
    r"\b(?:weather|forecast|temperature|how (?:hot|cold|warm)|(?:is it|will it|gonna|going to) "
    r"(?:be )?(?:rain|snow|storm|sunny|hot|cold))\b.*?\b(?:in|for|at|near)\s+"
    r"(?P<place>[A-Za-z][A-Za-z .'-]{1,60}?)"
    r"(?:\s+(?:today|tonight|tomorrow|this week|this weekend|right now|now|please))*[?.!]*\s*$",
    re.I,
)


_NOT_ASKING = re.compile(
    r"\b(?:build|make|create|write|code|app|website|site|widget|program|script|"
    r"api|component|page)\b",
    re.I,
)


class WeatherError(Exception):
    """The weather could not be fetched."""


def weather_request(text: str) -> str | None:
    """The place in 'what's the weather in Sydney tomorrow?', or None."""
    if _NOT_ASKING.search(text):
        return None
    found = _ASK.search(text.strip())
    return found.group("place").strip(" .") if found else None


def describe(code: object) -> str:
    return _WMO.get(code if isinstance(code, int) else -1, "mixed weather")


async def forecast(
    place: str,
    *,
    days: int = 3,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """A plain-words report: now, then each day's high, low, and rain chance."""
    days = max(1, min(7, days))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=15.0), transport=transport
    ) as client:
        try:
            found = await client.get(
                GEOCODE_URL,
                params={"name": place, "count": 1, "language": "en", "format": "json"},
            )
            results = found.json().get("results") if found.status_code < 400 else None
            if not results:
                raise WeatherError(f"No place called {place} was found.")
            spot = results[0]
            response = await client.get(
                FORECAST_URL,
                params={
                    "latitude": spot["latitude"],
                    "longitude": spot["longitude"],
                    "current": "temperature_2m,apparent_temperature,"
                    "relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max",
                    "timezone": "auto",
                    "forecast_days": days,
                },
            )
            body = response.json() if response.status_code < 400 else None
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise WeatherError(
                f"The weather service did not answer: {error}"
            ) from error
    if not isinstance(body, dict):
        raise WeatherError("The weather service did not answer.")
    where = ", ".join(
        str(part)
        for part in (spot.get("name"), spot.get("admin1"), spot.get("country"))
        if part
    )
    now = body.get("current") or {}
    lines = [
        f"Weather in {where}: now {round(now.get('temperature_2m', 0))}°C "
        f"(feels like {round(now.get('apparent_temperature', 0))}°C), "
        f"{describe(now.get('weather_code'))}, wind {round(now.get('wind_speed_10m', 0))} km/h, "
        f"humidity {round(now.get('relative_humidity_2m', 0))}%."
    ]
    daily = body.get("daily") or {}
    for index, day in enumerate(daily.get("time") or []):
        label = (
            "Today"
            if index == 0
            else "Tomorrow"
            if index == 1
            else date.fromisoformat(day).strftime("%A")
        )
        rain = (daily.get("precipitation_probability_max") or [None] * (index + 1))[
            index
        ]
        lines.append(
            f"{label}: {describe((daily.get('weather_code') or [None] * (index + 1))[index])}, "
            f"{round(daily['temperature_2m_max'][index])}°C high, "
            f"{round(daily['temperature_2m_min'][index])}°C low"
            + (f", {rain}% chance of rain." if rain is not None else ".")
        )
    return "\n".join(lines)
