"""Calendar via private iCal (.ics) links — no OAuth, no token expiry.

Google Calendar: Settings → your calendar → Integrate calendar →
"Secret address in iCal format". Recurring events are expanded.
Read-only by construction: an .ics feed cannot be written to.
The URLs are secrets (anyone holding one can read the calendar), so they are
never logged or put into the report; only a host name is shown.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from ..models import CalendarEvent
from .base import ProviderResult, make_client, now_utc


def split_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [u.strip() for u in raw.replace("\n", ",").replace(" ", ",").split(",") if u.strip()]


def _to_dt(v, tz: ZoneInfo) -> tuple[datetime, bool]:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=tz)
        return v.astimezone(tz), False
    if isinstance(v, date):
        return datetime.combine(v, time.min, tzinfo=tz), True
    raise TypeError(f"unsupported date value {v!r}")


def parse_ics(text: str, window_start: date, days: int, tz: ZoneInfo, source: str = "ical") -> list[CalendarEvent]:
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(text)
    t0 = datetime.combine(window_start, time.min, tzinfo=tz)
    t1 = t0 + timedelta(days=days)
    out: list[CalendarEvent] = []
    for comp in recurring_ical_events.of(cal).between(t0, t1):
        if str(comp.get("STATUS", "")).upper() == "CANCELLED":
            continue
        if str(comp.get("TRANSP", "")).upper() == "TRANSPARENT":  # marked "free", e.g. reminders
            continue
        start, all_day = _to_dt(comp.decoded("DTSTART"), tz)
        if comp.get("DTEND") is not None:
            end, _ = _to_dt(comp.decoded("DTEND"), tz)
        elif comp.get("DURATION") is not None:
            end = start + comp.decoded("DURATION")
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
        uid = str(comp.get("UID", "")) + "@" + start.isoformat()
        out.append(
            CalendarEvent(
                id=uid,
                summary=str(comp.get("SUMMARY", "(no title)")),
                start=start,
                end=end,
                all_day=all_day,
                calendar_id=source,
            )
        )
    out.sort(key=lambda e: e.start)
    return out


def fetch_events(
    urls: list[str], window_start: date, days: int, tz: ZoneInfo, *, client: httpx.Client | None = None
) -> ProviderResult[list[CalendarEvent]]:
    if not urls:
        return ProviderResult("calendar-ical", None, "disabled", None, None, "CALENDAR_ICS_URLS not set")
    own = client is None
    client = client or make_client()
    events: list[CalendarEvent] = []
    failed: list[str] = []
    try:
        for i, url in enumerate(urls, 1):
            label = f"feed {i} ({httpx.URL(url).host})"
            try:
                r = client.get(url)
                r.raise_for_status()
                if "BEGIN:VCALENDAR" not in r.text[:500]:
                    raise ValueError("response is not an iCal feed (link revoked or not public?)")
                events += parse_ics(r.text, window_start, days, tz, source=f"ical-{i}")
            except Exception as exc:  # noqa: BLE001 — report per feed, never leak the URL
                failed.append(f"{label}: {type(exc).__name__}")
        if failed and not events and len(failed) == len(urls):
            return ProviderResult("calendar-ical", None, "unavailable", None, None, "; ".join(failed))
        res = ProviderResult("calendar-ical", events, "live", None, now_utc(), "; ".join(failed))
        if failed:
            res.warnings.append("some calendar feeds failed: " + "; ".join(failed))
        return res
    finally:
        if own:
            client.close()
