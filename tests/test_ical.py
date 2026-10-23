from datetime import date, datetime, timedelta

import httpx

from sport_planner.planning import planner
from sport_planner.providers import ical
from tests.conftest import TZ, Scenario, make_transport

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:standup
DTSTART;TZID=Europe/Madrid:20261019T153000
DTEND;TZID=Europe/Madrid:20261019T160000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR
SUMMARY:Standup
END:VEVENT
BEGIN:VEVENT
UID:holiday
DTSTART;VALUE=DATE:20261022
DTEND;VALUE=DATE:20261023
SUMMARY:Holiday
END:VEVENT
BEGIN:VEVENT
UID:dentist
DTSTART:20261023T080000Z
DTEND:20261023T090000Z
SUMMARY:Dentist
END:VEVENT
BEGIN:VEVENT
UID:free
DTSTART;TZID=Europe/Madrid:20261023T120000
DTEND;TZID=Europe/Madrid:20261023T130000
TRANSP:TRANSPARENT
SUMMARY:Reminder
END:VEVENT
END:VCALENDAR
"""

URL = "https://calendar.google.com/calendar/ical/x%40gmail.com/private-abc/basic.ics"


def test_parse_expands_recurrence_and_timezones():
    evs = ical.parse_ics(ICS, date(2026, 10, 19), 5, TZ)
    names = [(e.summary, e.start.strftime("%a %H:%M"), e.all_day) for e in evs]
    assert ("Standup", "Mon 15:30", False) in names
    assert ("Standup", "Wed 15:30", False) in names
    assert ("Standup", "Fri 15:30", False) in names
    assert ("Holiday", "Thu 00:00", True) in names
    assert ("Dentist", "Fri 10:00", False) in names  # 08:00Z → 10:00 CEST
    assert not any(e.summary == "Reminder" for e in evs)  # "free" events don't block


def test_split_urls():
    assert ical.split_urls(" a , b\nc ") == ["a", "b", "c"]
    assert ical.split_urls(None) == []


def test_planner_uses_ics_and_keeps_url_secret(settings, prefs):
    s = settings.model_copy(update={"calendar_ics_urls": URL})
    sc = Scenario(date(2026, 10, 19)).set_day(0, wave=1.0, period=11, sdir=280, wind=7, gust=9, wdir=100)
    base = make_transport(sc)

    def handler(req):
        if req.url.host == "calendar.google.com":
            return httpx.Response(200, text=ICS)
        return base.handler(req)

    now = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    b = planner.collect(s, prefs, now=now, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = planner.plan(b, prefs, s)
    st = next(p for p in r.providers if p.name == "calendar-ical")
    assert st.ok and st.mode == "live"
    assert any("Standup" in c for c in r.days[0].itinerary.conflicts)
    # a 15:30 meeting caps any "later work start" proposal at 15:30
    p = r.days[0].itinerary.proposal
    assert p is None or p.work_ready_time.strftime("%H:%M") <= "15:30"
    assert "private-abc" not in r.model_dump_json()


def test_revoked_feed_is_reported_not_guessed(settings, prefs):
    s = settings.model_copy(update={"calendar_ics_urls": URL})
    sc = Scenario(date(2026, 10, 19))
    base = make_transport(sc)

    def handler(req):
        if req.url.host == "calendar.google.com":
            return httpx.Response(404, text="Not Found")
        return base.handler(req)

    b = planner.collect(s, prefs, now=datetime(2026, 10, 19, 9, 0, tzinfo=TZ), http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = planner.plan(b, prefs, s)
    assert any("commitments NOT checked" in m for m in r.days[0].missing_data)
    assert "private-abc" not in r.model_dump_json()
