from datetime import date, datetime, timedelta

import httpx

from sport_planner.delivery import telegram
from sport_planner.models import Activity
from sport_planner.planning import planner
from sport_planner.report import diff, render, snapshot
from tests.conftest import TZ, FakeCalendar, Scenario, make_transport, timed_event

WED = date(2026, 10, 14)  # Wednesday
SAT = date(2026, 10, 17)


def _run(settings, prefs, scenario, *, start, hour=9, events=None, **tkw):
    now = datetime.combine(start, datetime.min.time(), tzinfo=TZ).replace(hour=hour)
    client = httpx.Client(transport=make_transport(scenario, **tkw))
    cal = FakeCalendar(events or [])
    b = planner.collect(settings, prefs, now=now, http_client=client, calendar_service=cal)
    return planner.plan(b, prefs, settings), b


def good_surf(sc: Scenario, i: int):
    return sc.set_day(i, wave=1.0, period=11, sdir=280, wind=7, gust=9, wdir=100)


def good_kite(sc: Scenario, i: int, hours=(11, 18)):
    return sc.set_day(i, wind=19, gust=22, wdir=260, wind_hours=hours)


def test_exactly_five_days_and_window_advances(settings, prefs):
    r1, _ = _run(settings, prefs, Scenario(WED), start=WED)
    r2, _ = _run(settings, prefs, Scenario(WED + timedelta(days=1)), start=WED + timedelta(days=1))
    assert [d.day for d in r1.days] == [WED + timedelta(days=i) for i in range(5)]
    assert r2.days[0].day == WED + timedelta(days=1) and r2.days[-1].day == WED + timedelta(days=5)


def test_weekday_surf_respects_lunch_and_work(settings, prefs):
    sc = good_surf(Scenario(WED), 0)
    r, _ = _run(settings, prefs, sc, start=WED)
    d = r.days[0]
    assert d.chosen == Activity.SURF
    it = d.itinerary
    assert it.arrive_home <= it.lunch - timedelta(minutes=prefs.constraints.arrive_home_before_lunch_min)
    assert it.lunch.strftime("%H:%M") == "14:30" and it.work_start.strftime("%H:%M") == "15:00"
    assert it.depart_home >= datetime(2026, 10, 14, 9, 15, tzinfo=TZ)  # report at 09:00 + 15 min
    assert prefs.constraints.min_session_min <= it.activity_min <= prefs.constraints.max_session_min
    assert it.drive_out.verified and "verified" in render.render_text(r, prefs)


def test_weekday_calendar_conflict_blocks_session(settings, prefs):
    sc = good_surf(Scenario(WED), 0)
    ev = [timed_event(WED, 9, 30, 13, 30, "Client workshop")]
    r, _ = _run(settings, prefs, sc, start=WED, events=ev)
    d = r.days[0]
    assert d.chosen in (Activity.REST, Activity.MTB) or d.itinerary.proposal is not None
    assert any("Client workshop" in c for c in d.itinerary.conflicts)
    # the event is preserved verbatim in the report
    assert "Client workshop" in render.render_text(r, prefs)


def test_weekend_allows_long_session(settings, prefs):
    sc = good_kite(Scenario(SAT), 0, hours=(10, 19))
    r, _ = _run(settings, prefs, sc, start=SAT)
    d = r.days[0]
    assert d.is_weekend and d.chosen == Activity.KITE
    assert d.itinerary.lunch is None and d.itinerary.work_start is None
    assert prefs.constraints.min_session_min <= d.itinerary.activity_min <= prefs.constraints.max_session_min_weekend


def test_kite_vs_surf_picks_better_score_not_fixed_order(settings, prefs):
    sc = Scenario(WED)
    sc.set_day(0, wave=0.7, period=8, sdir=280, wind=19, gust=22, wdir=260, wind_hours=(9, 18))  # marginal surf, good kite
    r, _ = _run(settings, prefs, sc, start=WED)
    d = r.days[0]
    assert d.best_kite is not None
    assert d.chosen == Activity.KITE


def test_routing_failure_falls_back_and_is_labelled(settings, prefs):
    sc = good_surf(Scenario(WED), 0)
    r, b = _run(settings, prefs, sc, start=WED, maps_ok=False)
    d = r.days[0]
    assert d.chosen == Activity.SURF
    assert not d.itinerary.drive_out.verified
    assert d.confidence != "high"
    txt = render.render_text(r, prefs)
    assert "ESTIMATE, not verified" in txt
    assert any(p.name == "google-maps-routes" and p.mode == "fallback" for p in r.providers)


def test_forecast_gap_is_surfaced_not_guessed(settings, prefs):
    sc = good_surf(Scenario(WED), 0)

    def handler(req):
        if req.url.host == "marine-api.open-meteo.com":
            return httpx.Response(500, text="boom")
        return make_transport(sc).handler(req)

    now = datetime(2026, 10, 14, 9, 0, tzinfo=TZ)
    b = planner.collect(settings, prefs, now=now, http_client=httpx.Client(transport=httpx.MockTransport(handler)), calendar_service=FakeCalendar([]))
    r = planner.plan(b, prefs, settings)
    assert r.days[0].best_surf is None
    assert any("sea state unavailable" in m for m in r.days[0].missing_data)
    assert any(p.name == "open-meteo-marine" and not p.ok for p in r.providers)


def test_mtb_fallback_when_water_is_poor(settings, prefs):
    sc = Scenario(WED)  # flat and calm, dry
    r, _ = _run(settings, prefs, sc, start=WED)
    d = r.days[0]
    assert d.chosen == Activity.MTB and d.mtb_route_id
    assert any("not verified" in n for n in d.itinerary.notes)
    assert "SUGGESTED route" in render.render_text(r, prefs)


def test_rain_day_becomes_rest(settings, prefs):
    sc = Scenario(WED).set_day(0, rain=3.0, code=63)
    r, _ = _run(settings, prefs, sc, start=WED)
    assert r.days[0].chosen == Activity.REST


def test_campervan_proposal_is_a_proposal_not_a_change(settings, prefs):
    # Kite only good from 13:00 on a weekday: home option infeasible, van option works
    sc = good_kite(Scenario(WED), 0, hours=(13, 18))
    r, _ = _run(settings, prefs, sc, start=WED, route_min=30)
    d = r.days[0]
    it = d.itinerary
    assert it.proposal is not None
    assert it.proposal.kind in ("later_work_start", "campervan_remote_work")
    assert it.work_start.strftime("%H:%M") == "15:00"  # unchanged default
    txt = render.render_text(r, prefs)
    assert "Proposal" in txt and "not scheduled" in txt and "work-ready" in txt


def test_calendar_unavailable_lowers_confidence_and_says_so(settings, prefs):
    sc = good_surf(Scenario(WED), 0)
    now = datetime(2026, 10, 14, 9, 0, tzinfo=TZ)

    class Broken:
        def events(self):
            raise RuntimeError("token revoked")

    b = planner.collect(settings, prefs, now=now, http_client=httpx.Client(transport=make_transport(sc)), calendar_service=Broken())
    r = planner.plan(b, prefs, settings)
    assert r.days[0].confidence != "high"
    assert any("commitments NOT checked" in m for m in r.days[0].missing_data)


def test_dst_transition_keeps_local_times(settings, prefs):
    # EU DST ends Sun 25 Oct 2026. Window Thu 22 → Mon 26 crosses it.
    start = date(2026, 10, 22)
    sc = good_surf(Scenario(start), 4)  # Monday 26th, after the change
    r, _ = _run(settings, prefs, sc, start=start)
    mon = r.days[4]
    assert mon.day == date(2026, 10, 26) and mon.itinerary.lunch.strftime("%H:%M %z") == "14:30 +0100"
    assert r.days[0].itinerary.lunch.strftime("%z") == "+0200"


def test_snapshot_diff_and_telegram_delivery(settings, prefs):
    sc = good_surf(Scenario(WED), 0)
    r1, _ = _run(settings, prefs, sc, start=WED)
    r1.changes_since_yesterday = diff.changes(r1, None)
    assert "first report" in r1.changes_since_yesterday[0]
    snapshot.save(r1, settings.state_dir)
    prev = snapshot.load_previous(settings.state_dir)
    assert prev is not None and prev.days[0].chosen == Activity.SURF

    sc2 = Scenario(WED).set_day(0, rain=4.0, code=63)
    r2, _ = _run(settings, prefs, sc2, start=WED)
    ch = diff.changes(r2, prev)
    assert any("surf → rest" in c for c in ch)

    log: list = []
    client = httpx.Client(transport=make_transport(sc, telegram_log=log))
    html = render.render_html(r1, prefs)
    ids = telegram.send_html(settings.telegram_bot_token, settings.telegram_chat_id, html, client=client)
    assert ids and all(len(m["text"]) <= 4096 and m["parse_mode"] == "HTML" for m in log)
    assert "1. Five-day overview" in log[0]["text"]


def test_email_delivery_builds_multipart_and_dispatch(settings, prefs, monkeypatch):
    from sport_planner import cli
    from sport_planner.delivery import email as email_delivery

    sc = good_surf(Scenario(WED), 0)
    r, _ = _run(settings, prefs, sc, start=WED)
    html, text = render.render_html(r, prefs), render.render_text(r, prefs)

    sent = []

    class FakeSMTP:
        def send_message(self, msg):
            sent.append(msg)

    mid = email_delivery.send(smtp_user="me@gmail.com", smtp_app_password="x", to_addr="you@gmail.com", subject="s", html=html, text=text, smtp_client=FakeSMTP())
    assert mid and sent[0]["To"] == "you@gmail.com" and sent[0].is_multipart()
    parts = [p.get_content_type() for p in sent[0].iter_parts()]
    assert parts == ["text/plain", "text/html"]
    assert "1. Five-day overview" in sent[0].get_body(("plain",)).get_content()

    # dispatch: email channel with missing config must raise, not silently skip
    s2 = settings.model_copy(update={"delivery_channel": "email", "email_to": None})
    import pytest
    with pytest.raises(RuntimeError, match="EMAIL_TO"):
        cli.deliver(s2, html, text, "s")


def test_flex_proposal_only_on_great_days_without_meetings(settings, prefs):
    sc = good_surf(Scenario(WED), 0)  # scores ~99
    r, _ = _run(settings, prefs, sc, start=WED)
    it = r.days[0].itinerary
    assert it.proposal and it.proposal.kind == "later_work_start"
    assert it.proposal.work_ready_time.strftime("%H:%M") <= "16:00"
    assert it.work_start.strftime("%H:%M") == "15:00"  # schedule itself unchanged
    assert it.activity_min <= prefs.constraints.max_session_min  # base itinerary still 90 min

    # a 15:00 meeting removes the flex proposal (campervan one may still appear, so check the kind/rationale)
    r2, _ = _run(settings, prefs, sc, start=WED, events=[timed_event(WED, 15, 0, 16, 0, "Standup")])
    p2 = r2.days[0].itinerary.proposal
    assert p2 is None or "no meeting" not in p2.rationale

    # a mediocre day (score < 85) gets no flex proposal
    sc3 = Scenario(WED).set_day(0, wave=0.7, period=8, sdir=280, wind=14, gust=18, wdir=280)  # onshore, windswell
    r3, _ = _run(settings, prefs, sc3, start=WED)
    p3 = r3.days[0].itinerary.proposal
    assert p3 is None or p3.kind != "later_work_start" or "score" not in p3.rationale
