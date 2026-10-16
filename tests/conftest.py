"""Shared fixtures: a fake Open-Meteo / Maps / AEMET / Telegram transport and a fake calendar."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from sport_planner.preferences import load_preferences
from sport_planner.settings import Settings

TZ = ZoneInfo("Europe/Madrid")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def prefs():
    return load_preferences(ROOT / "config" / "preferences.yaml")


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        home_lat=36.277,
        home_lon=-6.088,
        google_maps_api_key="test-key",
        telegram_bot_token="123:abc",
        telegram_chat_id="42",
        aemet_api_key=None,
        enable_surf_forecast=False,
        state_dir=tmp_path / "state",
        preferences_file=ROOT / "config" / "preferences.yaml",
    )


class Scenario:
    """Hour-by-hour synthetic weather. Override per-day values with set_day()."""

    def __init__(self, start: date, days: int = 5):
        self.start = start
        self.days = days
        self.day: dict[int, dict] = {i: dict(wave=0.3, period=6, sdir=280, wind=5, gust=7, wdir=90, rain=0.0, code=1) for i in range(days)}

    def set_day(self, i: int, **kw):
        self.day[i].update(kw)
        return self

    def hours(self):
        for i in range(self.days):
            d = self.start + timedelta(days=i)
            for h in range(24):
                yield i, datetime.combine(d, datetime.min.time()).replace(hour=h)

    def marine(self):
        t, wh, sh, sp, sd = [], [], [], [], []
        for i, ts in self.hours():
            v = self.day[i]
            t.append(ts.strftime("%Y-%m-%dT%H:%M"))
            wh.append(v["wave"]); sh.append(v["wave"] * 0.9); sp.append(v["period"]); sd.append(v["sdir"])
        return {"hourly": {"time": t, "wave_height": wh, "swell_wave_height": sh, "swell_wave_period": sp, "swell_wave_direction": sd}}

    def forecast(self):
        t, ws, wg, wd, tc, pr, pp, wc = [], [], [], [], [], [], [], []
        for i, ts in self.hours():
            v = self.day[i]
            # optional diurnal shape: "wind_hours" restricts wind to a range of hours
            hrs = v.get("wind_hours")
            on = hrs is None or (hrs[0] <= ts.hour < hrs[1])
            t.append(ts.strftime("%Y-%m-%dT%H:%M"))
            ws.append(v["wind"] if on else 4); wg.append(v["gust"] if on else 6); wd.append(v["wdir"])
            tc.append(22); pr.append(v["rain"]); pp.append(80 if v["rain"] else 5); wc.append(v["code"])
        days = [self.start + timedelta(days=i) for i in range(self.days)]
        return {
            "hourly": {"time": t, "wind_speed_10m": ws, "wind_gusts_10m": wg, "wind_direction_10m": wd, "temperature_2m": tc, "precipitation": pr, "precipitation_probability": pp, "weather_code": wc},
            "daily": {"time": [d.isoformat() for d in days], "sunrise": [f"{d}T08:15" for d in days], "sunset": [f"{d}T19:45" for d in days]},
        }


def make_transport(scenario: Scenario, *, maps_ok=True, telegram_log: list | None = None, route_min=35, route_km=28):
    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if host == "marine-api.open-meteo.com":
            return httpx.Response(200, json=scenario.marine())
        if host == "api.open-meteo.com":
            return httpx.Response(200, json=scenario.forecast())
        if host == "routes.googleapis.com":
            if not maps_ok:
                return httpx.Response(403, json={"error": "denied"})
            return httpx.Response(200, json={"routes": [{"distanceMeters": route_km * 1000, "duration": f"{route_min * 60}s"}]})
        if host == "api.telegram.org":
            if telegram_log is not None:
                telegram_log.append(json.loads(req.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(telegram_log or []) or 1, "username": "testbot"}})
        return httpx.Response(404, text=f"unexpected {req.url}")

    return httpx.MockTransport(handler)


class FakeCalendar:
    """Minimal stand-in for googleapiclient's service.events().list().execute()."""

    def __init__(self, items: list[dict]):
        self._items = items

    def events(self):
        return self

    def list(self, **kw):
        self._kw = kw
        return self

    def execute(self):
        return {"items": self._items}


def timed_event(day: date, h0: int, m0: int, h1: int, m1: int, summary="Meeting", eid="e1"):
    s = datetime.combine(day, datetime.min.time(), tzinfo=TZ).replace(hour=h0, minute=m0)
    e = datetime.combine(day, datetime.min.time(), tzinfo=TZ).replace(hour=h1, minute=m1)
    return {"id": eid, "summary": summary, "start": {"dateTime": s.isoformat()}, "end": {"dateTime": e.isoformat()}}
