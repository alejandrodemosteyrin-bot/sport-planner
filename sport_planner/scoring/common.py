from __future__ import annotations

from datetime import datetime, timedelta

from ..models import Activity, ConditionWindow, DayLight


def in_window(deg: float | None, windows: list[tuple[int, int]]) -> bool:
    """True if a compass direction falls inside any (from, to) clockwise window."""
    if deg is None:
        return False
    d = deg % 360
    for a, b in windows:
        a, b = a % 360, b % 360
        if a <= b:
            if a <= d <= b:
                return True
        elif d >= a or d <= b:  # wraps through north
            return True
    return False


def compass(deg: float | None) -> str:
    if deg is None:
        return "?"
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int((deg % 360) / 22.5 + 0.5) % 16]


def daylight_hours(points: list, light: DayLight | None, margin_min: int = 30):
    """Filter hourly points to civil-ish daylight (sunrise+margin .. sunset-margin)."""
    if light is None:
        return points
    lo = light.sunrise + timedelta(minutes=margin_min)
    hi = light.sunset - timedelta(minutes=margin_min)
    return [p for p in points if lo <= p.time <= hi]


def best_contiguous_window(
    hourly: list[tuple[datetime, int, list[str], list[str], dict[str, str]]],
    *,
    threshold: int,
    min_hours: int,
    activity: Activity,
    spot_id: str,
    spot_name: str,
    extra: dict | None = None,
) -> ConditionWindow | None:
    """From (time, score, reasons, warnings, evidence) tuples, return the best run of
    consecutive hours scoring >= threshold, at least min_hours long. Score of the
    window is the mean; reasons/warnings/evidence taken from the peak hour."""
    best: ConditionWindow | None = None
    run: list[tuple] = []

    def flush():
        nonlocal best
        if len(run) >= min_hours:
            mean = int(round(sum(r[1] for r in run) / len(run)))
            peak = max(run, key=lambda r: r[1])
            cw = ConditionWindow(
                activity=activity,
                spot_id=spot_id,
                spot_name=spot_name,
                start=run[0][0],
                end=run[-1][0] + timedelta(hours=1),
                score=mean,
                reasons=peak[2],
                warnings=sorted({w for r in run for w in r[3]}),
                evidence=peak[4],
                **(extra or {}),
            )
            # prefer higher score, then longer
            if best is None or (cw.score, cw.duration_min) > (best.score, best.duration_min):
                best = cw

    for item in hourly:
        if item[1] >= threshold and (not run or item[0] - run[-1][0] == timedelta(hours=1)):
            run.append(item)
        else:
            flush()
            run = [item] if item[1] >= threshold else []
    flush()
    return best
