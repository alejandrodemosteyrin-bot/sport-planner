"""`sport-planner why` — show how each spot scored each day, so thresholds can be tuned."""

from __future__ import annotations

from datetime import timedelta

from .planning.planner import Bundle, _day_slice
from .preferences import Preferences
from .scoring import kite as kite_scoring
from .scoring import surf as surf_scoring
from .scoring.common import daylight_hours


def explain(bundle: Bundle, prefs: Preferences, *, days: int = 5) -> str:
    out: list[str] = []
    for i in range(days):
        d = bundle.window_start + timedelta(days=i)
        out.append(f"\n=== {d:%a %d %b} ===")
        light = next((ld.light.get(d) for ld in bundle.by_spot.values() if ld.light.get(d)), None)
        out.append("KITE  (worthwhile >= %d, needs 2 consecutive hours)" % kite_scoring.WORTHWHILE)
        for k in prefs.kite_spots:
            ld = bundle.by_spot.get(k.id)
            if not ld or not ld.wind:
                out.append(f"  {k.name}: no wind data")
                continue
            rows = []
            for w in daylight_hours(_day_slice(ld.wind, d), light):
                sc, reasons, warnings, ev, size = kite_scoring.score_hour(k, prefs.rider, w)
                rows.append((sc, w, reasons, warnings, size))
            if not rows:
                continue
            best = max(rows, key=lambda r: r[0])
            hrs_ok = sum(1 for r in rows if r[0] >= kite_scoring.WORTHWHILE)
            winds = [r[1].wind_kn for r in rows if r[1].wind_kn is not None]
            gusts = [r[1].gust_kn for r in rows if r[1].gust_kn is not None]
            out.append(
                f"  {k.name}: best {best[0]}/100 at {best[1].time:%H:%M} "
                f"(wind {best[1].wind_kn:.0f} kn, gust {best[1].gust_kn:.0f} kn, dir {best[1].wind_dir_deg:.0f}°"
                f"{', ' + str(best[4]) + ' m' if best[4] else ''}); "
                f"day range wind {min(winds):.0f}–{max(winds):.0f} kn, gusts up to {max(gusts):.0f} kn; "
                f"{hrs_ok} h worthwhile"
            )
            out.append(f"      why: {'; '.join(best[2])}" + (f" | warnings: {'; '.join(best[3])}" if best[3] else ""))
            windiest = max(rows, key=lambda r: r[1].wind_kn or 0)
            if windiest is not best:
                out.append(
                    f"      windiest hour {windiest[1].time:%H:%M}: {windiest[1].wind_kn:.0f} kn gust {windiest[1].gust_kn:.0f} kn "
                    f"dir {windiest[1].wind_dir_deg:.0f}° → {windiest[0]}/100: {'; '.join(windiest[2])}"
                    + (f" | {'; '.join(windiest[3])}" if windiest[3] else "")
                )
        out.append("SURF  (worthwhile >= %d)" % surf_scoring.WORTHWHILE)
        for s in prefs.surf_spots:
            ld = bundle.by_spot.get(s.id)
            if not ld or not ld.sea or not ld.wind:
                out.append(f"  {s.name}: no data")
                continue
            wind_by_t = {p.time: p for p in ld.wind}
            rows = []
            for sp in daylight_hours(_day_slice(ld.sea, d), light):
                w = wind_by_t.get(sp.time)
                if w:
                    sc, reasons, warnings, ev = surf_scoring.score_hour(s, prefs.rider, sp, w)
                    rows.append((sc, sp, reasons, warnings))
            if not rows:
                continue
            best = max(rows, key=lambda r: r[0])
            out.append(
                f"  {s.name}: best {best[0]}/100 at {best[1].time:%H:%M} "
                f"(wave {best[1].wave_height_m:.1f} m, period {best[1].swell_period_s or 0:.0f} s) — {'; '.join(best[2])}"
            )
    return "\n".join(out)
