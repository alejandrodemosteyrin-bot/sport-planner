"""Orchestration: collect data once, then plan five days.

`collect()` talks to providers (all injectable for tests). `plan()` is pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from ..models import (
    Activity,
    CalendarEvent,
    ConditionWindow,
    DayLight,
    DayPlan,
    Itinerary,
    LatLon,
    ProviderStatus,
    Report,
    RouteResult,
    SeaPoint,
    WeatherAlert,
    WindPoint,
)
from ..preferences import Preferences
from ..providers import aemet, google_calendar, google_maps, open_meteo, surf_forecast, windguru
from ..scoring import kite as kite_scoring
from ..scoring import mtb as mtb_scoring
from ..scoring import surf as surf_scoring
from ..settings import Settings
from .calendar_rules import build_constraints
from .itinerary import available_minutes_for_mtb, build_for_mtb, build_for_window

DAYS = 5


@dataclass
class LocationData:
    sea: list[SeaPoint] | None = None
    wind: list[WindPoint] | None = None
    light: dict[date, DayLight] = field(default_factory=dict)


@dataclass
class Bundle:
    now: datetime
    window_start: date
    home: LatLon | None
    by_spot: dict[str, LocationData] = field(default_factory=dict)
    events: list[CalendarEvent] | None = None
    alerts: list[WeatherAlert] = field(default_factory=list)
    statuses: list[ProviderStatus] = field(default_factory=list)
    surf_forecast_xcheck: dict[str, dict] = field(default_factory=dict)
    routes_verified: bool = True
    missing: list[str] = field(default_factory=list)
    _route_cache: dict = field(default_factory=dict)
    route_fn: Callable[[LatLon, LatLon, datetime | None], RouteResult] | None = None


def collect(settings: Settings, prefs: Preferences, *, now: datetime | None = None, http_client=None, calendar_service=None) -> Bundle:
    tz = settings.tz
    now = now or datetime.now(tz)
    b = Bundle(now=now, window_start=now.date(), home=LatLon(lat=settings.home_lat, lon=settings.home_lon) if settings.home_configured else None)
    if b.home is None:
        b.missing.append("HOME_LAT/HOME_LON not set — itineraries cannot be timed")

    # --- forecasts per spot (Open-Meteo, primary)
    locs: dict[str, tuple[LatLon, bool]] = {}
    for s in prefs.surf_spots:
        locs[s.id] = (s.location, True)
    for k in prefs.kite_spots:
        locs[k.id] = (k.location, False)
    for r in prefs.mtb_routes:
        locs[r.id] = (r.start, False)
    seen_status = set()
    for sid, (loc, want_sea) in locs.items():
        ld = LocationData()
        ww = open_meteo.fetch_wind_weather(loc, tz, DAYS, client=http_client)
        if ww.ok:
            ld.wind, light = ww.data
            ld.light = {d.day: d for d in light}
        else:
            b.missing.append(f"wind/weather unavailable for {sid}: {ww.detail}")
        if want_sea:
            sea = open_meteo.fetch_sea(loc, tz, DAYS, client=http_client)
            if sea.ok:
                ld.sea = sea.data
            else:
                b.missing.append(f"sea state unavailable for {sid}: {sea.detail}")
            if "sea" not in seen_status:
                b.statuses.append(sea.status())
                seen_status.add("sea")
        if "wind" not in seen_status:
            b.statuses.append(ww.status())
            seen_status.add("wind")
        b.by_spot[sid] = ld

    # --- optional cross-checks
    for s in prefs.surf_spots:
        sf = surf_forecast.fetch_break_summary(s.id, tz, enabled=settings.enable_surf_forecast, client=http_client)
        if sf.ok:
            b.surf_forecast_xcheck[s.id] = sf.data
        if "sf" not in seen_status:
            b.statuses.append(sf.status())
            seen_status.add("sf")
    b.statuses.append(windguru.fetch("valdevaqueros", enabled=settings.enable_windguru).status())

    # --- alerts
    al = aemet.fetch_alerts(settings.aemet_api_key, client=http_client)
    b.statuses.append(al.status())
    if al.ok:
        b.alerts = al.data
    else:
        b.missing.append(f"official warnings not checked: {al.detail}")

    # --- calendar
    cal = google_calendar.fetch_events(
        settings.google_oauth_client_file,
        settings.state_dir / "google_token.json",
        settings.calendar_ids,
        b.window_start,
        DAYS,
        tz,
        service=calendar_service,
    )
    b.statuses.append(cal.status())
    if cal.ok:
        b.events = cal.data
    else:
        b.missing.append(f"calendar unavailable — commitments NOT checked: {cal.detail}")

    # --- routing (cached per origin/dest/hour)
    maps_status: dict[str, ProviderStatus] = {}

    def route_fn(o: LatLon, d: LatLon, dep: datetime | None) -> RouteResult:
        key = (o.maps_str(), d.maps_str(), dep.strftime("%Y%m%d%H") if dep else None)
        if key not in b._route_cache:
            res = google_maps.compute_route(o, d, settings.google_maps_api_key, departure_time=dep, client=http_client)
            if not res.data.verified:
                b.routes_verified = False
            maps_status.setdefault("maps", res.status())
            b._route_cache[key] = res.data
        return b._route_cache[key]

    b.route_fn = route_fn
    b._maps_status = maps_status  # type: ignore[attr-defined]
    return b


def _confidence(day_idx: int, bundle: Bundle, missing: list[str]) -> str:
    c = ["high", "high", "medium", "low", "low"][day_idx]
    if missing or not bundle.routes_verified or bundle.events is None:
        c = {"high": "medium", "medium": "low", "low": "low"}[c]
    return c


def _day_slice(points, day: date):
    return [p for p in points if p.time.date() == day] if points else []


def plan(bundle: Bundle, prefs: Preferences, settings: Settings) -> Report:
    tz: ZoneInfo = settings.tz
    days: list[DayPlan] = []
    events = bundle.events or []
    for i in range(DAYS):
        d = bundle.window_start + timedelta(days=i)
        missing: list[str] = []
        light = next((ld.light.get(d) for ld in bundle.by_spot.values() if ld.light.get(d)), None)
        dc = build_constraints(d, bundle.now, prefs.constraints, events, light, tz)

        # Surf
        best_surf: ConditionWindow | None = None
        for s in prefs.surf_spots:
            ld = bundle.by_spot.get(s.id, LocationData())
            if not (ld.sea and ld.wind):
                missing.append(f"no sea/wind data for {s.name}")
                continue
            cw = surf_scoring.best_window(s, prefs.rider, _day_slice(ld.sea, d), _day_slice(ld.wind, d), light)
            if cw and (best_surf is None or cw.score > best_surf.score):
                best_surf = cw
        # Kite
        best_kite: ConditionWindow | None = None
        for k in prefs.kite_spots:
            ld = bundle.by_spot.get(k.id, LocationData())
            if not ld.wind:
                missing.append(f"no wind data for {k.name}")
                continue
            cw = kite_scoring.best_window(k, prefs.rider, _day_slice(ld.wind, d), light)
            if cw and (best_kite is None or cw.score > best_kite.score):
                best_kite = cw

        chosen = Activity.REST
        reason = "no worthwhile and feasible option"
        itin: Itinerary | None = None
        mtb_id = None
        if bundle.home and bundle.route_fn:
            candidates: list[tuple[ConditionWindow, Itinerary]] = []
            for cw in (best_surf, best_kite):
                if cw:
                    it = build_for_window(cw, dc, prefs, bundle.home, bundle.route_fn)
                    if it:
                        candidates.append((cw, it))
            if candidates:
                cw, it = max(candidates, key=lambda c: (c[0].score, c[1].activity_min))
                chosen, itin = cw.activity, it
                reason = f"{cw.activity.value} {cw.score}/100 at {cw.spot_name}: " + "; ".join(cw.reasons[:3])
                if it.proposal and "ONLY feasible" in " ".join(it.notes):
                    reason += " (only with the remote-work proposal)"
            else:
                avail = available_minutes_for_mtb(dc, prefs)
                wind_any = next((bundle.by_spot[r.id].wind for r in prefs.mtb_routes if bundle.by_spot.get(r.id) and bundle.by_spot[r.id].wind), None)
                choice = mtb_scoring.choose_route(prefs.mtb_routes, prefs.rider, _day_slice(wind_any, d), light, avail) if wind_any else None
                if choice:
                    it = build_for_mtb(choice, dc, prefs, bundle.home, bundle.route_fn)
                    if it:
                        chosen, itin, mtb_id = Activity.MTB, it, choice.route.id
                        it.notes += choice.warnings
                        reason = f"surf/kite not worthwhile; MTB {choice.route.name} ({'verified' if choice.route.verified else 'suggested'}): " + "; ".join(choice.reasons)
                if chosen == Activity.REST:
                    if best_surf or best_kite:
                        reason = "conditions exist but no itinerary fits the calendar/work constraints"
                    else:
                        reason = "no worthwhile surf or kite window and no suitable MTB day — rest day"
        else:
            reason = "home location not configured; cannot time an itinerary"

        if itin is None:
            itin = Itinerary(day=d, activity=Activity.REST, lunch=dc.lunch, work_start=dc.work_start)
        itin.conflicts = [n for n in dc.notes if n.startswith("calendar:")]
        itin.notes += [n for n in dc.notes if not n.startswith("calendar")]
        days.append(
            DayPlan(
                day=d,
                is_weekend=dc.is_weekend,
                chosen=chosen,
                confidence=_confidence(i, bundle, missing),  # type: ignore[arg-type]
                reason=reason,
                best_surf=best_surf,
                best_kite=best_kite,
                mtb_route_id=mtb_id,
                itinerary=itin,
                daylight=light,
                missing_data=missing + ([] if i else bundle.missing),
                calendar_events=[e for e in events if e.start.date() == d],
            )
        )
    maps_status = getattr(bundle, "_maps_status", {})
    if not maps_status:
        maps_status = {
            "maps": ProviderStatus(
                name="google-maps-routes",
                ok=False,
                mode="fallback" if settings.google_maps_api_key else "disabled",
                detail="no routes requested this run" if settings.google_maps_api_key else "GOOGLE_MAPS_API_KEY not set",
            )
        }
    statuses = list(bundle.statuses) + list(maps_status.values())
    return Report(
        generated_at=bundle.now,
        window_start=bundle.window_start,
        window_end=bundle.window_start + timedelta(days=DAYS - 1),
        days=days,
        alerts=bundle.alerts,
        providers=statuses,
    )
