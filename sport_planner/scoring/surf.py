"""Surf suitability for an advanced beginner. Bigger is not better.

Inputs per hour: wave height, swell period/direction (Open-Meteo marine), wind
speed/direction (Open-Meteo forecast). Tides are NOT available from Open-Meteo;
the window carries an explicit warning so the reader checks a tide table.
"""

from __future__ import annotations

from ..models import Activity, ConditionWindow, DayLight, SeaPoint, SurfSpot, WindPoint
from ..preferences import Rider
from .common import best_contiguous_window, compass, daylight_hours, in_window

WORTHWHILE = 55


def score_hour(spot: SurfSpot, rider: Rider, sea: SeaPoint, wind: WindPoint) -> tuple[int, list[str], list[str], dict[str, str]]:
    reasons: list[str] = []
    warnings: list[str] = []
    h, per, sdir = sea.wave_height_m, sea.swell_period_s, sea.swell_dir_deg
    w, wdir = wind.wind_kn, wind.wind_dir_deg
    if h is None or w is None:
        return 0, ["missing wave or wind data"], ["missing data"], {}

    lo = max(spot.wave_min_m, rider.surf_wave_min_m)
    hi = min(spot.wave_max_m, rider.surf_wave_max_m)
    # Wave height: 0..45
    if lo <= h <= hi:
        mid = (lo + hi) / 2
        size = 45 - int(abs(h - mid) / max(hi - mid, 0.1) * 10)
        reasons.append(f"wave {h:.1f} m in your range {lo:.1f}–{hi:.1f} m")
    elif h < lo:
        size = int(max(0, 45 * (h / lo) - 20))
        reasons.append(f"wave {h:.1f} m, below {lo:.1f} m minimum")
    else:
        over = h - hi
        size = int(max(0, 30 - over * 40))
        reasons.append(f"wave {h:.1f} m, above your {hi:.1f} m comfort limit")
        if over >= 0.5:
            warnings.append(f"waves {h:.1f} m — too big for your level")

    # Period: 0..20
    if per is None:
        period = 8
        warnings.append("no swell period data")
    elif per >= spot.min_period_s + 3:
        period = 20
        reasons.append(f"long period {per:.0f} s")
    elif per >= spot.min_period_s:
        period = 14
    else:
        period = 4
        reasons.append(f"short period {per:.0f} s (windswell)")

    # Swell direction: 0..10
    sw = 10 if in_window(sdir, spot.swell_dirs_deg) else 3
    if sw < 10 and sdir is not None:
        reasons.append(f"swell from {compass(sdir)} is off the spot's window")

    # Wind: 0..25
    offshore = in_window(wdir, spot.offshore_dirs_deg)
    onshore = in_window(wdir, [((spot.faces_deg + 180 - 60) % 360, (spot.faces_deg + 180 + 60) % 360)])
    if w <= 6:
        windsc = 25
        reasons.append("glassy")
    elif offshore and w <= 15:
        windsc = 24
        reasons.append(f"offshore {compass(wdir)} {w:.0f} kn")
    elif offshore:
        windsc = 12
        warnings.append(f"strong offshore {w:.0f} kn")
    elif onshore and w <= 10:
        windsc = 14
    elif onshore:
        windsc = max(0, 10 - int((w - 10) * 1.5))
        reasons.append(f"onshore {compass(wdir)} {w:.0f} kn")
    else:  # cross-shore
        windsc = 18 if w <= 10 else max(0, 15 - int((w - 10)))
        reasons.append(f"cross-shore {compass(wdir)} {w:.0f} kn")

    score = max(0, min(100, size + period + sw + windsc))
    # Wave size outside the rider's range caps the day regardless of how clean it is.
    if h < lo:
        score = min(score, 40)
    elif h > hi:
        score = min(score, 45)
    evidence = {
        "wave_m": f"{h:.1f}",
        "period_s": f"{per:.0f}" if per is not None else "?",
        "swell_dir": compass(sdir),
        "wind_kn": f"{w:.0f}",
        "wind_dir": compass(wdir),
    }
    return score, reasons, warnings, evidence


def best_window(
    spot: SurfSpot,
    rider: Rider,
    sea: list[SeaPoint],
    wind: list[WindPoint],
    light: DayLight | None,
    *,
    min_hours: int = 2,
) -> ConditionWindow | None:
    wind_by_t = {p.time: p for p in wind}
    rows = []
    for s in daylight_hours(sea, light):
        w = wind_by_t.get(s.time)
        if w is None:
            continue
        rows.append((s.time, *score_hour(spot, rider, s, w)))
    cw = best_contiguous_window(
        rows, threshold=WORTHWHILE, min_hours=min_hours, activity=Activity.SURF, spot_id=spot.id, spot_name=spot.name
    )
    if cw:
        cw.warnings.append("tide not modelled — check a tide table for this window")
    return cw
