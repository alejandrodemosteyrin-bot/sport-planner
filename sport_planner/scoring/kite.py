"""Kite suitability for an advanced beginner with 9 m and 12 m kites.

Safety rules are hard: offshore/forbidden direction, gusts over 35 kn, thunder
or heavy rain → score 0 regardless of average wind.
"""

from __future__ import annotations

from ..models import Activity, ConditionWindow, DayLight, KiteSpot, WindPoint
from ..preferences import Rider
from .common import best_contiguous_window, compass, daylight_hours, in_window

WORTHWHILE = 55
STORM_GUST_KN = 45
THUNDER_CODES = {95, 96, 99}
HEAVY_RAIN_CODES = {65, 67, 82}


def sizing_wind(rider: Rider, wind_kn: float, gust_kn: float | None) -> float:
    """Wind used to choose the kite: part-way from the average towards the gust.
    gust_weight 0 = size for the average, 1 = size for the gusts. Default 0.6."""
    if gust_kn is None or gust_kn <= wind_kn:
        return wind_kn
    return wind_kn + rider.gust_weight * (gust_kn - wind_kn)


def pick_kite(rider: Rider, wind_kn: float, gust_kn: float | None = None) -> tuple[int | None, float]:
    """Return (kite size, fit 0..1) for the sizing wind, or (None, 0) if no kite fits."""
    sw = sizing_wind(rider, wind_kn, gust_kn)
    best: tuple[int | None, float] = (None, 0.0)
    for size, band in rider.kite_wind_bands_kn.items():
        if size not in rider.kite_sizes_m or not (band.min <= sw <= band.max):
            continue
        if band.ideal_min <= sw <= band.ideal_max:
            fit = 1.0
        elif sw < band.ideal_min:
            fit = 0.6 + 0.4 * (sw - band.min) / max(band.ideal_min - band.min, 0.1)
        else:
            fit = 0.6 + 0.4 * (band.max - sw) / max(band.max - band.ideal_max, 0.1)
        # prefer the smaller kite when two fit equally well in gusty air
        if fit > best[1] or (fit == best[1] and best[0] is not None and size < best[0] and gust_kn and gust_kn > wind_kn * 1.25):
            best = (size, fit)
    return best


def score_hour(spot: KiteSpot, rider: Rider, w: WindPoint) -> tuple[int, list[str], list[str], dict[str, str], int | None]:
    reasons: list[str] = []
    warnings: list[str] = []
    ev = {
        "wind_kn": f"{w.wind_kn:.0f}" if w.wind_kn is not None else "?",
        "gust_kn": f"{w.gust_kn:.0f}" if w.gust_kn is not None else "?",
        "wind_dir": compass(w.wind_dir_deg),
    }
    if w.wind_kn is None or w.wind_dir_deg is None:
        return 0, ["missing wind data"], ["missing data"], ev, None

    # Hard safety stops
    if in_window(w.wind_dir_deg, spot.unsafe_wind_dirs_deg):
        return 0, [f"{compass(w.wind_dir_deg)} is offshore/unsafe at {spot.name}"], ["offshore wind"], ev, None
    if w.gust_kn is not None and w.gust_kn >= STORM_GUST_KN:
        return 0, [f"gusts {w.gust_kn:.0f} kn"], ["storm-force gusts"], ev, None
    if w.weather_code in THUNDER_CODES:
        return 0, ["thunderstorm risk"], ["thunderstorm"], ev, None
    if w.weather_code in HEAVY_RAIN_CODES:
        return 0, ["heavy rain"], ["heavy rain"], ev, None

    # Spot-specific gust correction (e.g. Levante accelerating off the hills at Valdevaqueros)
    gust = w.gust_kn
    for adj in spot.gust_adjust:
        if gust is not None and in_window(w.wind_dir_deg, adj.dirs_deg):
            gust = gust * adj.factor
            ev["gust_kn"] = f"{gust:.0f} (model {w.gust_kn:.0f} ×{adj.factor})"
            break
    if gust is not None and gust >= STORM_GUST_KN:
        return 0, [f"gusts {gust:.0f} kn"], ["storm-force gusts"], ev, None

    size, fit = pick_kite(rider, w.wind_kn, gust)
    sw = sizing_wind(rider, w.wind_kn, gust)
    if size is None:
        reasons.append(f"{w.wind_kn:.0f} kn gusting {gust:.0f} — no kite fits (sizing wind {sw:.0f} kn)" if gust else f"{w.wind_kn:.0f} kn — no kite in range")
        return int(10 * min(w.wind_kn / 14, 1)), reasons, warnings, ev, None
    # Quality also depends on the *average*: a kite sized for the gusts is underpowered in the lulls
    band = rider.kite_wind_bands_kn[size]
    if w.wind_kn >= band.ideal_min:
        lull = 1.0
    else:
        lull = max(0.0, (w.wind_kn - band.min + 3) / max(band.ideal_min - band.min + 3, 0.1))
        if lull < 0.7:
            warnings.append(f"underpowered in lulls ({w.wind_kn:.0f} kn average on the {size} m)")
    base = int(55 * fit * (0.5 + 0.5 * lull))
    reasons.append(f"{w.wind_kn:.0f} kn gusting {gust:.0f} → sized for gusts ({sw:.0f} kn) → {size} m" if gust else f"{w.wind_kn:.0f} kn → {size} m kite")

    # Direction quality 0..15
    if in_window(w.wind_dir_deg, spot.safe_wind_dirs_deg):
        dirsc = 15
        reasons.append(f"{compass(w.wind_dir_deg)} launchable")
    else:
        dirsc = 4
        warnings.append(f"{compass(w.wind_dir_deg)} is outside the spot's safe window")

    # Gustiness 0..30 — the biggest quality factor after the wind itself
    gf = (gust / w.wind_kn) if (gust and w.wind_kn) else 1.0
    if gf <= 1.2:
        gsc = 30
        reasons.append("steady")
    elif gf <= 1.35:
        gsc = 20
        reasons.append(f"a bit gusty (×{gf:.2f})")
    elif gf <= rider.max_gust_factor:
        gsc = 10
        warnings.append(f"gusty (×{gf:.2f}, gusts {gust:.0f} kn)")
    else:
        gsc = 2
        warnings.append(f"very gusty (×{gf:.2f}, gusts {gust:.0f} kn)")

    rain = 0
    if w.precip_mm and w.precip_mm >= 1.0:
        rain = -10
        warnings.append("rain")
    score = max(0, min(100, base + dirsc + gsc + rain))
    return score, reasons, warnings, ev, size


def best_window(
    spot: KiteSpot, rider: Rider, wind: list[WindPoint], light: DayLight | None, *, min_hours: int = 2
) -> ConditionWindow | None:
    rows, sizes = [], {}
    for w in daylight_hours(wind, light):
        sc, r, wn, ev, size = score_hour(spot, rider, w)
        rows.append((w.time, sc, r, wn, ev))
        sizes[w.time] = size
    cw = best_contiguous_window(
        rows, threshold=WORTHWHILE, min_hours=min_hours, activity=Activity.KITE, spot_id=spot.id, spot_name=spot.name
    )
    if cw:
        # kite size at the peak hour
        peak = max((r for r in rows if cw.start <= r[0] < cw.end), key=lambda r: r[1])
        cw.kite_size_m = sizes.get(peak[0])
        if spot.restrictions:
            cw.warnings.append(spot.restrictions)
    return cw
