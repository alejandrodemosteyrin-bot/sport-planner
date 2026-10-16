"""Render the six-section report as Telegram-compatible HTML (parse_mode=HTML).

Supported tags: <b>, <i>, <code>, <a href>. Everything else must be escaped.
"""

from __future__ import annotations

from html import escape as _e

from ..models import Activity, DayPlan, Itinerary, Report
from ..preferences import Preferences

ICON = {Activity.SURF: "🏄", Activity.KITE: "🪁", Activity.MTB: "🚵", Activity.REST: "😴"}


def _t(dt) -> str:
    return dt.strftime("%H:%M") if dt else "–"


def _overview_row(d: DayPlan) -> str:
    it = d.itinerary
    win = ""
    cw = d.best_surf if d.chosen == Activity.SURF else d.best_kite if d.chosen == Activity.KITE else None
    if cw:
        win = f" {cw.start:%H:%M}–{cw.end:%H:%M}"
    dest = _e(it.spot_name) if it.spot_name else "—"
    back = f"home {_t(it.arrive_home)}"
    flag = ""
    if it.proposal:
        only = any("ONLY feasible" in n for n in it.notes)
        flag = " 💡" + (" proposal-only" if only else " +proposal")
        if only:
            back = f"van work-ready {_t(it.proposal.work_ready_time)} (needs OK)"
    conf = {"high": "●●●", "medium": "●●○", "low": "●○○"}[d.confidence]
    kite = f" ({cw.kite_size_m} m)" if cw and cw.kite_size_m else ""
    if it.depart_home:
        chain = (
            f"leave home {_t(it.depart_home)} → session {_t(it.session_start)}–{_t(it.session_end)} "
            f"→ leave spot {_t(it.leave_spot)} → {back}"
        )
    else:
        chain = "no itinerary"
    return (
        f"<b>{d.day:%a %d %b}</b> {ICON[d.chosen]} {d.chosen.value}{kite}{flag} · {dest}{_e(win)} · {conf}\n"
        f"    {chain}"
    )


def _route_line(it: Itinerary) -> str:
    if not it.drive_out:
        return ""
    v = "verified" if (it.drive_out.verified and it.drive_back and it.drive_back.verified) else "ESTIMATE, not verified"
    link = f' <a href="{it.drive_out.maps_url}">route</a>' if it.drive_out.verified else ""
    return f"Round trip {it.round_trip_km:.0f} km, driving {it.driving_min:.0f} min ({v}){link}"


def _today_detail(d: DayPlan, prefs: Preferences) -> str:
    it = d.itinerary
    lines = [f"<b>2. Today — {ICON[d.chosen]} {d.chosen.value.upper()}</b>"]
    cw = d.best_surf if d.chosen == Activity.SURF else d.best_kite if d.chosen == Activity.KITE else None
    if cw:
        ev = ", ".join(f"{k} {v}" for k, v in cw.evidence.items())
        lines.append(f"Evidence: {_e(ev)}")
        lines.append(f"Why: {_e('; '.join(cw.reasons))}")
        if cw.warnings:
            lines.append(f"⚠️ {_e('; '.join(cw.warnings))}")
    elif d.chosen == Activity.MTB and d.mtb_route_id:
        r = prefs.mtb_route(d.mtb_route_id)
        tag = "verified route" if r.verified else "SUGGESTED route — not verified"
        lines.append(f"Route: {_e(r.name)} — {r.distance_km:.0f} km / {r.elevation_gain_m:.0f} m ↑, {_e(r.terrain)} ({tag})")
    if not cw:
        lines.append(f"Reason: {_e(d.reason)}")
    if it.depart_home:
        b = prefs.constraints.buffers_min
        lines.append(
            f"Leave home {_t(it.depart_home)} → arrive {_t(it.arrive_spot)} → setup {b.gear_setup} min → "
            f"<b>session {_t(it.session_start)}–{_t(it.session_end)}</b> ({it.activity_min} min) → "
            f"pack/change → <b>leave spot {_t(it.leave_spot)}</b> → home {_t(it.arrive_home)}"
        )
        if it.lunch:
            lines.append(f"Lunch {_t(it.lunch)} · work {_t(it.work_start)}")
        lines.append(_route_line(it))
    else:
        if it.lunch:
            lines.append(f"Lunch {_t(it.lunch)} · work {_t(it.work_start)} as usual")
    if it.proposal:
        p = it.proposal
        lines.append(
            f"💡 <i>Proposal ({p.kind.replace('_', ' ')}), not scheduled:</i> {_e(p.rationale)}. "
            f"Parking: {_e(p.parking)}. Connectivity: {_e(p.connectivity_assumption)}. "
            f"{_e(p.lunch_logistics)}. Setup {p.setup_min} min → <b>work-ready {_t(p.work_ready_time)}</b>."
        )
    for n in it.notes:
        lines.append(f"· {_e(n)}")
    return "\n".join(lines)


def _best(days: list[DayPlan]) -> str:
    def pick(attr):
        best = None
        for d in days:
            cw = getattr(d, attr)
            if cw and (best is None or cw.score > best[1].score):
                best = (d, cw)
        return best

    s, k = pick("best_surf"), pick("best_kite")
    m = max((d for d in days if d.chosen == Activity.MTB), default=None, key=lambda d: 1)
    lines = ["<b>3. Best opportunities</b>"]
    lines.append(f"Surf: {s[0].day:%a} {_e(s[1].spot_name)} {s[1].score}/100" if s else "Surf: nothing worthwhile this window")
    lines.append(f"Kite: {k[0].day:%a} {_e(k[1].spot_name)} {k[1].score}/100 ({k[1].kite_size_m} m)" if k else "Kite: nothing worthwhile this window")
    lines.append(f"MTB: {m.day:%a} {_e(m.itinerary.spot_name or '')}" if m else "MTB: not needed / no suitable day")
    cands = [(d, (d.best_surf or d.best_kite)) for d in days if d.chosen in (Activity.SURF, Activity.KITE)]
    if cands:
        d, cw = max(cands, key=lambda c: c[1].score if c[1] else 0)
        lines.append(f"Strongest overall: <b>{d.day:%a} {cw.activity.value} at {_e(cw.spot_name)}</b> ({cw.score}/100)")
    return "\n".join(lines)


def _calendar(days: list[DayPlan]) -> str:
    lines = ["<b>4. Calendar</b>"]
    any_ = False
    for d in days:
        for c in d.itinerary.conflicts:
            lines.append(f"{d.day:%a}: {_e(c)}")
            any_ = True
        if d.itinerary.proposal:
            lines.append(f"{d.day:%a}: proposed change → {_e(d.itinerary.proposal.kind.replace('_', ' '))} (needs your OK)")
            any_ = True
    if not any_:
        lines.append("No confirmed events in the window. Weekday lunch 14:30 / work 15:00 kept as confirmed.")
    return "\n".join(lines)


def _sources(r: Report) -> str:
    lines = ["<b>6. Sources & confidence</b>"]
    for p in r.providers:
        mark = "✅" if p.ok and p.mode == "live" else "⚠️" if p.mode == "fallback" else "⛔"
        ts = f" @ {p.retrieved_at:%H:%M}Z" if p.retrieved_at else ""
        detail = f" — {_e(p.detail)}" if p.detail and (not p.ok or p.mode != "live") else ""
        url = f' <a href="{p.source_url}">src</a>' if p.source_url and p.ok else ""
        lines.append(f"{mark} {_e(p.name)} ({p.mode}){ts}{url}{detail}")
    miss = sorted({m for d in r.days for m in d.missing_data})
    if miss:
        lines.append("Missing/uncertain: " + _e("; ".join(miss[:6])))
    lines.append("Days 4–5 are low confidence by design. Forecasts are predictions, not guarantees.")
    return "\n".join(lines)


def render_html(r: Report, prefs: Preferences) -> str:
    parts = [f"<b>🌊 Sport Planner — {r.window_start:%a %d %b} → {r.window_end:%a %d %b}</b>"]
    if r.alerts:
        parts.append("🚨 <b>Official warnings:</b> " + _e("; ".join(f"{a.severity}: {a.headline}" for a in r.alerts[:4])))
    parts.append("<b>1. Five-day overview</b>\n" + "\n".join(_overview_row(d) for d in r.days))
    parts.append(_today_detail(r.days[0], prefs))
    parts.append(_best(r.days))
    parts.append(_calendar(r.days))
    parts.append("<b>5. Changes since yesterday</b>\n" + "\n".join(f"· {_e(c)}" for c in r.changes_since_yesterday))
    parts.append(_sources(r))
    return "\n\n".join(parts)


def render_text(r: Report, prefs: Preferences) -> str:
    """Plain-text version for the terminal / logs (tags stripped)."""
    import re

    html = render_html(r, prefs)
    txt = re.sub(r"<a href=\"([^\"]+)\">[^<]*</a>", r"\1", html)
    txt = re.sub(r"</?[bi]>", "", txt)
    from html import unescape

    return unescape(txt)
