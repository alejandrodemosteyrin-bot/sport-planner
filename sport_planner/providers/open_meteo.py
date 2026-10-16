"""Open-Meteo adapters (primary, documented, keyless).

Marine API:  wave / swell height, period, direction.
Forecast API: wind, gusts, direction, temperature, precipitation, sunrise/sunset.

Docs: https://open-meteo.com/en/docs and https://open-meteo.com/en/docs/marine-weather-api
Non-commercial use is free; rate limits are generous but we cache per run anyway.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from ..models import DayLight, LatLon, SeaPoint, WindPoint
from .base import ProviderResult, make_client, now_utc

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _parse_local(ts: str, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(ts).replace(tzinfo=tz)


def fetch_sea(
    loc: LatLon, tz: ZoneInfo, days: int = 5, *, client: httpx.Client | None = None
) -> ProviderResult[list[SeaPoint]]:
    params = {
        "latitude": loc.lat,
        "longitude": loc.lon,
        "hourly": "wave_height,swell_wave_height,swell_wave_period,swell_wave_direction",
        "timezone": tz.key,
        "forecast_days": days,
    }
    url = f"{MARINE_URL}?{httpx.QueryParams(params)}"
    own = client is None
    client = client or make_client()
    try:
        r = client.get(MARINE_URL, params=params)
        r.raise_for_status()
        h = r.json()["hourly"]
        pts = [
            SeaPoint(
                time=_parse_local(t, tz),
                wave_height_m=h["wave_height"][i],
                swell_height_m=h["swell_wave_height"][i],
                swell_period_s=h["swell_wave_period"][i],
                swell_dir_deg=h["swell_wave_direction"][i],
            )
            for i, t in enumerate(h["time"])
        ]
        return ProviderResult("open-meteo-marine", pts, "live", url, now_utc())
    except Exception as exc:  # noqa: BLE001 — report, never guess
        return ProviderResult("open-meteo-marine", None, "unavailable", url, None, f"{type(exc).__name__}: {exc}")
    finally:
        if own:
            client.close()


def fetch_wind_weather(
    loc: LatLon, tz: ZoneInfo, days: int = 5, *, client: httpx.Client | None = None
) -> ProviderResult[tuple[list[WindPoint], list[DayLight]]]:
    params = {
        "latitude": loc.lat,
        "longitude": loc.lon,
        "hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m,precipitation,precipitation_probability,weather_code",
        "daily": "sunrise,sunset",
        "wind_speed_unit": "kn",
        "timezone": tz.key,
        "forecast_days": days,
    }
    url = f"{FORECAST_URL}?{httpx.QueryParams(params)}"
    own = client is None
    client = client or make_client()
    try:
        r = client.get(FORECAST_URL, params=params)
        r.raise_for_status()
        j = r.json()
        h = j["hourly"]
        pts = [
            WindPoint(
                time=_parse_local(t, tz),
                wind_kn=h["wind_speed_10m"][i],
                gust_kn=h["wind_gusts_10m"][i],
                wind_dir_deg=h["wind_direction_10m"][i],
                temp_c=h["temperature_2m"][i],
                precip_mm=h["precipitation"][i],
                precip_prob_pct=h["precipitation_probability"][i],
                weather_code=h["weather_code"][i],
            )
            for i, t in enumerate(h["time"])
        ]
        d = j["daily"]
        light = [
            DayLight(
                day=date.fromisoformat(d["time"][i]),
                sunrise=_parse_local(d["sunrise"][i], tz),
                sunset=_parse_local(d["sunset"][i], tz),
            )
            for i in range(len(d["time"]))
        ]
        return ProviderResult("open-meteo-forecast", (pts, light), "live", url, now_utc())
    except Exception as exc:  # noqa: BLE001
        return ProviderResult("open-meteo-forecast", None, "unavailable", url, None, f"{type(exc).__name__}: {exc}")
    finally:
        if own:
            client.close()
