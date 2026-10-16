"""MTB fallback: pick a route that fits the available time and the weather.

Routes come from preferences. `verified=False` routes are allowed but the
report labels them as suggestions, never as checked routes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import DayLight, MtbRoute, WindPoint
from ..preferences import Rider
from .common import daylight_hours


@dataclass
class MtbChoice:
    route: MtbRoute
    ride_min: int
    score: int
    reasons: list[str]
    warnings: list[str]


def ride_minutes(route: MtbRoute, rider: Rider) -> int:
    flat = route.distance_km / rider.mtb_speed_kmh * 60
    climb = route.elevation_gain_m / 100 * rider.mtb_climb_min_per_100m
    return int(round(flat + climb))


def weather_score(wind: list[WindPoint], light: DayLight | None) -> tuple[int, list[str], list[str]]:
    pts = daylight_hours(wind, light)
    reasons, warnings = [], []
    if not pts:
        return 0, ["no weather data"], ["missing data"]
    rain = sum((p.precip_mm or 0) for p in pts)
    max_prob = max((p.precip_prob_pct or 0) for p in pts)
    max_wind = max((p.wind_kn or 0) for p in pts)
    temps = [p.temp_c for p in pts if p.temp_c is not None]
    tmax = max(temps) if temps else None
    sc = 80
    if rain >= 5:
        sc -= 50
        warnings.append(f"{rain:.0f} mm rain forecast")
    elif rain >= 1 or max_prob >= 60:
        sc -= 20
        reasons.append("showers possible")
    else:
        reasons.append("dry")
    if max_wind >= 25:
        sc -= 20
        warnings.append(f"wind up to {max_wind:.0f} kn")
    if tmax is not None and tmax >= 33:
        sc -= 20
        warnings.append(f"hot, {tmax:.0f} °C — ride early")
    if any((p.weather_code or 0) in (95, 96, 99) for p in pts):
        sc = 0
        warnings.append("thunderstorm risk")
    return max(0, sc), reasons, warnings


def choose_route(
    routes: list[MtbRoute], rider: Rider, wind: list[WindPoint], light: DayLight | None, available_min: int
) -> MtbChoice | None:
    wsc, reasons, warnings = weather_score(wind, light)
    if wsc < 40:
        return None
    best: MtbChoice | None = None
    for r in routes:
        if r.distance_km > rider.mtb_max_distance_km:
            continue
        mins = ride_minutes(r, rider)
        if mins > available_min:
            continue
        fit = min(1.0, mins / max(available_min, 1))
        sc = int(wsc * (0.6 + 0.4 * fit))
        if r.verified:
            sc += 5
        rs = reasons + [f"{r.distance_km:.0f} km / {r.elevation_gain_m:.0f} m ↑ ≈ {mins} min at {rider.mtb_speed_kmh:.0f} km/h"]
        ws = list(warnings) + ([] if r.verified else ["route not verified — suggestion only"])
        c = MtbChoice(r, mins, sc, rs, ws)
        if best is None or c.score > best.score:
            best = c
    return best
