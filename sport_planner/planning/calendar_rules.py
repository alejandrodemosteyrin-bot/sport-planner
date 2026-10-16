"""Turn the calendar + weekday defaults into hard time constraints for a day.

Rules (from CLAUDE.md):
- Weekdays: lunch 14:30, work 15:00 from home by default. An empty calendar
  does NOT make work optional.
- Weekends: no default work constraint; calendar events still apply.
- Every confirmed timed event is preserved. All-day events are reported but
  do not block (they are usually holidays / reminders); the reader decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..models import CalendarEvent, DayLight
from ..preferences import Constraints


@dataclass
class DayConstraints:
    day: date
    is_weekend: bool
    earliest_departure: datetime
    must_be_home_by: datetime | None  # hard deadline to be back home (None on a free weekend day)
    lunch: datetime | None
    work_start: datetime | None
    latest_outdoor_end: datetime  # sunset-based cap
    blocking_events: list[CalendarEvent] = field(default_factory=list)
    all_day_events: list[CalendarEvent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def free_block(self) -> tuple[datetime, datetime]:
        return self.free_block_for(ignore_home_deadline=False)

    def free_block_for(self, *, ignore_home_deadline: bool) -> tuple[datetime, datetime]:
        """Largest gap between departure and the deadline not covered by timed events."""
        start = self.earliest_departure
        end = self.latest_outdoor_end if ignore_home_deadline else (self.must_be_home_by or self.latest_outdoor_end)
        end = min(end, self.latest_outdoor_end + timedelta(hours=2))  # driving back after dark is fine
        gaps: list[tuple[datetime, datetime]] = []
        cursor = start
        for ev in sorted(self.blocking_events, key=lambda e: e.start):
            if ev.end <= cursor:
                continue
            if ev.start > cursor:
                gaps.append((cursor, min(ev.start, end)))
            cursor = max(cursor, ev.end)
            if cursor >= end:
                break
        if cursor < end:
            gaps.append((cursor, end))
        if not gaps:
            return (start, start)
        return max(gaps, key=lambda g: g[1] - g[0])


def build_constraints(
    day: date,
    now: datetime,
    cons: Constraints,
    events: list[CalendarEvent],
    light: DayLight | None,
    tz: ZoneInfo,
) -> DayConstraints:
    is_weekend = day.weekday() >= 5
    at = lambda t: datetime.combine(day, t, tzinfo=tz)  # noqa: E731
    earliest = at(cons.earliest_departure)
    if day == now.date():
        earliest = max(earliest, now + timedelta(minutes=15))
    sunset = light.sunset if light else at(time(19, 0))
    todays = [e for e in events if e.start.date() <= day <= (e.end - timedelta(seconds=1)).date()]
    timed = [e for e in todays if not e.all_day]
    all_day = [e for e in todays if e.all_day]

    lunch = work = deadline = None
    notes: list[str] = []
    if not is_weekend:
        lunch = at(cons.weekday_lunch)
        work = at(cons.weekday_work_start)
        deadline = lunch - timedelta(minutes=cons.arrive_home_before_lunch_min)
    else:
        notes.append("weekend: no default work constraint")

    dc = DayConstraints(
        day=day,
        is_weekend=is_weekend,
        earliest_departure=earliest,
        must_be_home_by=deadline,
        lunch=lunch,
        work_start=work,
        latest_outdoor_end=sunset - timedelta(minutes=30),
        blocking_events=timed,
        all_day_events=all_day,
        notes=notes,
    )
    for e in timed:
        notes.append(f"calendar: {e.summary} {e.start:%H:%M}–{e.end:%H:%M} (confirmed, kept)")
    for e in all_day:
        notes.append(f"calendar (all-day): {e.summary} — not treated as blocking")
    return dc
