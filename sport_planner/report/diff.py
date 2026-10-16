"""Day-over-day comparison between today's report and yesterday's snapshot."""

from __future__ import annotations

from ..models import Report


def changes(today: Report, prev: Report | None) -> list[str]:
    if prev is None:
        return ["first report — nothing to compare yet"]
    out: list[str] = []
    prev_days = {d.day: d for d in prev.days}
    for d in today.days:
        p = prev_days.get(d.day)
        if p is None:
            out.append(f"{d.day:%a %d}: new day in the window")
            continue
        if p.chosen != d.chosen:
            out.append(f"{d.day:%a %d}: {p.chosen.value} → {d.chosen.value}")
        elif (p.itinerary.spot_name or "") != (d.itinerary.spot_name or "") and d.itinerary.spot_name:
            out.append(f"{d.day:%a %d}: destination {p.itinerary.spot_name} → {d.itinerary.spot_name}")
        for label, a, b in (("surf", p.best_surf, d.best_surf), ("kite", p.best_kite, d.best_kite)):
            sa, sb = (a.score if a else 0), (b.score if b else 0)
            if abs(sa - sb) >= 10:
                out.append(f"{d.day:%a %d}: {label} {'improved' if sb > sa else 'deteriorated'} {sa}→{sb}")
        pe = {e.id for e in p.calendar_events}
        for e in d.calendar_events:
            if e.id not in pe:
                out.append(f"{d.day:%a %d}: new calendar event — {e.summary}")
    prev_alerts = {a.headline for a in prev.alerts}
    for a in today.alerts:
        if a.headline not in prev_alerts:
            out.append(f"new weather alert: {a.headline}")
    return out or ["no material changes since yesterday"]
