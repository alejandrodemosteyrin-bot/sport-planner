from datetime import datetime

from sport_planner.models import SeaPoint, WindPoint
from sport_planner.scoring import kite, surf
from sport_planner.scoring.common import in_window
from tests.conftest import TZ


def _t(h):
    return datetime(2026, 10, 14, h, 0, tzinfo=TZ)


def test_in_window_wraps_north():
    assert in_window(10, [(300, 40)])
    assert in_window(350, [(300, 40)])
    assert not in_window(180, [(300, 40)])
    assert in_window(90, [(60, 120)])


def test_surf_bigger_is_not_better(prefs):
    spot = prefs.surf_spot("el_palmar")
    wind = WindPoint(time=_t(10), wind_kn=5, gust_kn=7, wind_dir_deg=90)
    good = SeaPoint(time=_t(10), wave_height_m=1.0, swell_period_s=11, swell_dir_deg=280)
    big = SeaPoint(time=_t(10), wave_height_m=2.6, swell_period_s=11, swell_dir_deg=280)
    tiny = SeaPoint(time=_t(10), wave_height_m=0.2, swell_period_s=11, swell_dir_deg=280)
    s_good, _, _, _ = surf.score_hour(spot, prefs.rider, good, wind)
    s_big, _, w_big, _ = surf.score_hour(spot, prefs.rider, big, wind)
    s_tiny, _, _, _ = surf.score_hour(spot, prefs.rider, tiny, wind)
    assert s_good >= surf.WORTHWHILE
    assert s_big < s_good and any("too big" in w for w in w_big)
    assert s_tiny < surf.WORTHWHILE


def test_surf_onshore_wind_kills_it(prefs):
    spot = prefs.surf_spot("el_palmar")
    sea = SeaPoint(time=_t(10), wave_height_m=1.0, swell_period_s=11, swell_dir_deg=280)
    offshore = WindPoint(time=_t(10), wind_kn=8, gust_kn=10, wind_dir_deg=100)
    onshore = WindPoint(time=_t(10), wind_kn=20, gust_kn=25, wind_dir_deg=280)
    assert surf.score_hour(spot, prefs.rider, sea, offshore)[0] > surf.score_hour(spot, prefs.rider, sea, onshore)[0] + 15


def test_kite_picks_size_and_blocks_offshore(prefs):
    spot = prefs.kite_spot("valdevaqueros")
    twelve = WindPoint(time=_t(13), wind_kn=18, gust_kn=21, wind_dir_deg=260)
    nine = WindPoint(time=_t(13), wind_kn=24, gust_kn=28, wind_dir_deg=260)
    levante = WindPoint(time=_t(13), wind_kn=24, gust_kn=28, wind_dir_deg=10)  # northerly = straight offshore
    s12, _, _, _, k12 = kite.score_hour(spot, prefs.rider, twelve)
    s9, _, _, _, k9 = kite.score_hour(spot, prefs.rider, nine)
    s0, _, w0, _, _ = kite.score_hour(spot, prefs.rider, levante)
    assert k12 == 12 and s12 >= kite.WORTHWHILE
    assert k9 == 9 and s9 >= kite.WORTHWHILE
    assert s0 == 0 and "offshore wind" in w0


def test_kite_sized_for_gusts(prefs):
    # Tarifa Levante 14 Oct 2026: 20 kn gusting 29 → a 9 m, not a 12 m
    spot = prefs.kite_spot("los_lances")
    gusty = WindPoint(time=_t(18), wind_kn=20, gust_kn=29, wind_dir_deg=80)
    steady = WindPoint(time=_t(18), wind_kn=20, gust_kn=22, wind_dir_deg=80)
    s_g, r_g, _, _, k_g = kite.score_hour(spot, prefs.rider, gusty)
    s_s, _, _, _, k_s = kite.score_hour(spot, prefs.rider, steady)
    assert k_g == 9 and k_s == 12
    assert any("sized for gusts" in x for x in r_g)
    assert s_s > s_g  # steadier wind scores higher at the same average


def test_spot_gust_adjust_applies_by_direction(prefs):
    valde = prefs.kite_spot("valdevaqueros")
    levante = WindPoint(time=_t(13), wind_kn=24, gust_kn=30, wind_dir_deg=90)
    poniente = WindPoint(time=_t(13), wind_kn=24, gust_kn=30, wind_dir_deg=250)
    _, _, _, ev_l, _ = kite.score_hour(valde, prefs.rider, levante)
    _, _, _, ev_p, _ = kite.score_hour(valde, prefs.rider, poniente)
    assert "×1.2" in ev_l["gust_kn"] and "×" not in ev_p["gust_kn"]


def test_kite_storm_and_gusts_unsafe(prefs):
    spot = prefs.kite_spot("los_lances")
    storm = WindPoint(time=_t(13), wind_kn=35, gust_kn=48, wind_dir_deg=90)
    gusty = WindPoint(time=_t(13), wind_kn=18, gust_kn=30, wind_dir_deg=90)
    steady = WindPoint(time=_t(13), wind_kn=18, gust_kn=21, wind_dir_deg=90)
    assert kite.score_hour(spot, prefs.rider, storm)[0] == 0  # gusts >= 45 kn remain a hard stop
    s, _, w, _, _ = kite.score_hour(spot, prefs.rider, gusty)
    assert any("gusty" in x for x in w)  # flagged, not vetoed
    assert s < kite.score_hour(spot, prefs.rider, steady)[0]


def test_kite_window_requires_two_hours(prefs):
    spot = prefs.kite_spot("los_lances")
    pts = [WindPoint(time=_t(h), wind_kn=18 if h == 13 else 5, gust_kn=20, wind_dir_deg=260) for h in range(8, 19)]
    assert kite.best_window(spot, prefs.rider, pts, None) is None
    pts = [WindPoint(time=_t(h), wind_kn=18 if 12 <= h <= 15 else 5, gust_kn=20, wind_dir_deg=260) for h in range(8, 19)]
    cw = kite.best_window(spot, prefs.rider, pts, None)
    assert cw and cw.start.hour == 12 and cw.end.hour == 16 and cw.kite_size_m == 12
