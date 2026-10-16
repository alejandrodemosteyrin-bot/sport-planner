"""Build a timed itinerary for one option on one day, or declare it infeasible."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from ..models import Activity, ConditionWindow, Itinerary, LatLon, Proposal, RouteResult
from ..preferences import Preferences
from ..scoring.mtb import MtbChoice
from .calendar_rules import DayConstraints

RouteFn = Callable[[LatLon, LatLon, datetime | None], RouteResult]


def _m(minutes: float) -> timedelta:
    return timedelta(minutes=minutes)


def _timed(
    *,
    dc: DayConstraints,
    prefs: Preferences,
    home: LatLon,
    dest: LatLon,
    parking_walk_min: int,
    window: tuple[datetime, datetime] | None,  # None = any time (MTB)
    fixed_duration_min: int | None,  # MTB ride length
    deadline: datetime | None,
    route_fn: RouteFn,
    cap_min: int | None = None,
) -> tuple[Itinerary, RouteResult, RouteResult] | None:
    b = prefs.constraints.buffers_min
    ignore_home = deadline is None or (dc.must_be_home_by is not None and deadline > dc.must_be_home_by)
    block_start, block_end = dc.free_block_for(ignore_home_deadline=ignore_home)
    hard_end = min(block_end, deadline) if deadline else block_end
    if block_end - block_start < _m(prefs.constraints.min_session_min):
        return None

    out = route_fn(home, dest, block_start)
    back = route_fn(dest, home, None)

    earliest_session_start = block_start + _m(out.duration_min + parking_walk_min + b.gear_setup)
    latest_session_end = hard_end - _m(b.pack_down + b.change_shower + back.duration_min + b.traffic_safety)

    if window:
        s = max(window[0], earliest_session_start)
        e = min(window[1], latest_session_end, dc.latest_outdoor_end)
        cap = _m(cap_min or (prefs.constraints.max_session_min_weekend if dc.is_weekend else prefs.constraints.max_session_min))
        if e - s > cap:
            # Keep the latest-possible slice: morning light wind/tide aside, this leaves slack before the deadline
            # only when the deadline binds; otherwise start at the window start.
            if deadline and e >= latest_session_end:
                s = e - cap
            else:
                e = s + cap
    else:
        s = earliest_session_start
        e = min(latest_session_end, dc.latest_outdoor_end, s + _m(fixed_duration_min or 0))
    if e - s < _m(prefs.constraints.min_session_min):
        return None

    # Re-query the outbound route for the actual departure time (traffic-aware when live).
    depart = s - _m(out.duration_min + parking_walk_min + b.gear_setup)
    out2 = route_fn(home, dest, depart)
    if abs(out2.duration_min - out.duration_min) > 1:
        out = out2
        depart = s - _m(out.duration_min + parking_walk_min + b.gear_setup)
        if depart < block_start:
            s = block_start + _m(out.duration_min + parking_walk_min + b.gear_setup)
            depart = block_start
    if e - s < _m(prefs.constraints.min_session_min):
        return None

    leave = e + _m(b.pack_down + b.change_shower)
    back = route_fn(dest, home, leave)
    arrive_home = leave + _m(back.duration_min + b.traffic_safety)
    it = Itinerary(
        day=dc.day,
        activity=Activity.REST,  # caller sets
        depart_home=depart,
        arrive_spot=depart + _m(out.duration_min),
        session_start=s,
        session_end=e,
        leave_spot=leave,
        arrive_home=arrive_home,
        lunch=dc.lunch,
        work_start=dc.work_start,
        drive_out=out,
        drive_back=back,
        activity_min=int((e - s).total_seconds() // 60),
        round_trip_km=round(out.distance_km + back.distance_km, 1),
        driving_min=out.duration_min + back.duration_min,
    )
    return it, out, back


def build_for_window(
    cw: ConditionWindow, dc: DayConstraints, prefs: Preferences, home: LatLon, route_fn: RouteFn
) -> Itinerary | None:
    spot = prefs.surf_spot(cw.spot_id) if cw.activity == Activity.SURF else prefs.kite_spot(cw.spot_id)
    base = _timed(
        dc=dc,
        prefs=prefs,
        home=home,
        dest=spot.location,
        parking_walk_min=spot.parking_walk_min,
        window=(cw.start, cw.end),
        fixed_duration_min=None,
        deadline=dc.must_be_home_by,
        route_fn=route_fn,
    )
    it = None
    if base:
        it = base[0]
        it.activity, it.spot_id, it.spot_name = cw.activity, spot.id, spot.name
        # Drive-time limit
        if it.drive_out and it.drive_out.duration_min > prefs.constraints.max_drive_min:
            it.notes.append(f"drive {it.drive_out.duration_min:.0f} min exceeds the {prefs.constraints.max_drive_min} min limit")
            return None

    # "Really good day" flex proposal: later work start from home, only if no meeting gets in the way.
    fx = prefs.constraints.flex
    if (not dc.is_weekend) and fx.enabled and dc.work_start and cw.score >= fx.min_score:
        latest = datetime.combine(dc.day, fx.latest_work_start, tzinfo=dc.work_start.tzinfo)
        first_meeting = min((e.start for e in dc.blocking_events if e.start > dc.earliest_departure), default=None)
        if first_meeting is not None:
            latest = min(latest, first_meeting)
        if latest > dc.work_start:
            c = prefs.constraints
            flex_deadline = latest - _m(c.lunch_duration_min + c.arrive_home_before_lunch_min)
            alt = _timed(
                dc=dc, prefs=prefs, home=home, dest=spot.location, parking_walk_min=spot.parking_walk_min,
                window=(cw.start, cw.end), fixed_duration_min=None, deadline=flex_deadline, route_fn=route_fn,
                cap_min=fx.max_session_min,
            )
            if alt:
                alt_it = alt[0]
                gain = alt_it.activity_min - (it.activity_min if it else 0)
                if gain >= 20 and not (alt_it.drive_out and alt_it.drive_out.duration_min > c.max_drive_min):
                    work_ready = alt_it.arrive_home + _m(c.arrive_home_before_lunch_min + c.lunch_duration_min)
                    prop = Proposal(
                        kind="later_work_start",
                        work_ready_time=work_ready,
                        parking="home",
                        connectivity_assumption="home",
                        setup_min=0,
                        lunch_logistics=f"lunch at home {alt_it.arrive_home + _m(c.arrive_home_before_lunch_min):%H:%M}",
                        rationale=(
                            f"score {cw.score}/100 ≥ {fx.min_score} and "
                            + (f"no meeting before {first_meeting:%H:%M}" if first_meeting else "no meetings today")
                            + f": +{gain} min, session until {alt_it.session_end:%H:%M}"
                        ),
                    )
                    if it:
                        it.proposal = prop
                    else:
                        alt_it.activity, alt_it.spot_id, alt_it.spot_name = cw.activity, spot.id, spot.name
                        alt_it.proposal = prop
                        alt_it.notes.append("ONLY feasible with the proposed later work start — not scheduled by default")
                        return alt_it
                    return it

    # Campervan / later-work proposal on weekdays, only when it adds real time and the spot allows it.
    cv = prefs.constraints.campervan
    if (not dc.is_weekend) and cv.available and spot.campervan_ok and dc.work_start:
        alt = _timed(
            dc=dc,
            prefs=prefs,
            home=home,
            dest=spot.location,
            parking_walk_min=spot.parking_walk_min,
            window=(cw.start, cw.end),
            fixed_duration_min=None,
            deadline=None,
            route_fn=route_fn,
        )
        if alt:
            alt_it = alt[0]
            gain = alt_it.activity_min - (it.activity_min if it else 0)
            if gain >= 30:
                b = prefs.constraints.buffers_min
                work_ready = (
                    alt_it.session_end
                    + _m(b.pack_down + b.change_shower + prefs.constraints.lunch_duration_min + cv.work_setup_min)
                )
                kind = "campervan_remote_work" if work_ready <= dc.work_start else "later_work_start"
                prop = Proposal(
                    kind=kind,
                    work_ready_time=work_ready,
                    parking=f"{spot.name} car park (campervan ok)",
                    connectivity_assumption=spot.campervan_connectivity_note or cv.connectivity_note,
                    setup_min=cv.work_setup_min,
                    lunch_logistics=f"lunch at the van {alt_it.session_end + _m(b.pack_down + b.change_shower):%H:%M}, {prefs.constraints.lunch_duration_min} min",
                    rationale=f"+{gain} min on the water vs going home (session until {alt_it.session_end:%H:%M})",
                )
                if it:
                    it.proposal = prop
                else:
                    # Home option infeasible; the only way to do this is the proposal → present as proposal only.
                    alt_it.activity, alt_it.spot_id, alt_it.spot_name = cw.activity, spot.id, spot.name
                    alt_it.proposal = prop
                    alt_it.notes.append("ONLY feasible with the proposed remote-work change — not scheduled by default")
                    if alt_it.drive_out and alt_it.drive_out.duration_min > prefs.constraints.max_drive_min:
                        return None
                    return alt_it
    return it


def build_for_mtb(
    choice: MtbChoice, dc: DayConstraints, prefs: Preferences, home: LatLon, route_fn: RouteFn
) -> Itinerary | None:
    r = choice.route
    base = _timed(
        dc=dc,
        prefs=prefs,
        home=home,
        dest=r.start,
        parking_walk_min=5,
        window=None,
        fixed_duration_min=choice.ride_min,
        deadline=dc.must_be_home_by,
        route_fn=route_fn,
    )
    if not base:
        return None
    it = base[0]
    it.activity, it.spot_id, it.spot_name, it.mtb_route_id = Activity.MTB, r.id, r.name, r.id
    if it.drive_out and it.drive_out.duration_min > prefs.constraints.max_drive_min:
        return None
    return it


def available_minutes_for_mtb(dc: DayConstraints, prefs: Preferences) -> int:
    """Rough upper bound on ride time for route selection (before real routing)."""
    s, e = dc.free_block
    b = prefs.constraints.buffers_min
    total = (min(e, dc.latest_outdoor_end) - s).total_seconds() / 60
    return int(total - 2 * 25 - b.gear_setup - b.pack_down - b.change_shower - b.traffic_safety)
