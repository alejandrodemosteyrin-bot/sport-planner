"""Command-line entry point.

  sport-planner status           integration status (what is live / fallback / missing)
  sport-planner run              build the report, print it, save snapshot
  sport-planner run --send       ...and deliver it (email by default, see DELIVERY_CHANNEL)
  sport-planner why              per-day, per-spot scores and the reasons (for tuning thresholds)
  sport-planner auth-calendar    run the one-time Google Calendar OAuth consent
  sport-planner test-delivery    send a short test message through the configured channel
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

from .delivery import email as email_delivery
from .delivery import telegram
from .planning import planner
from .preferences import load_preferences
from .report import diff, render, snapshot
from .settings import load_settings

log = logging.getLogger("sport_planner")


def _setup_logging(level: str, state_dir) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=level.upper(), format=fmt, handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(state_dir / "sport_planner.log", encoding="utf-8")])


def deliver(s, html: str, text: str, subject: str) -> str:
    """Send through the configured channel. Returns a human-readable receipt. Raises on failure."""
    miss = s.missing_for(s.delivery_channel)
    if miss:
        raise RuntimeError(f"cannot send via {s.delivery_channel}: missing {', '.join(miss)}")
    if s.delivery_channel == "email":
        mid = email_delivery.send(
            smtp_user=s.gmail_user, smtp_app_password=s.gmail_app_password, to_addr=s.email_to, subject=subject, html=html, text=text
        )
        return f"email to {s.email_to} accepted by Gmail (Message-ID {mid})"
    ids = telegram.send_html(s.telegram_bot_token, s.telegram_chat_id, html)
    return f"Telegram message ids {ids}"


def cmd_status(args) -> int:
    s = load_settings()
    prefs = load_preferences(s.preferences_file)
    rows = []
    rows.append(("home location", "set" if s.home_configured else "MISSING HOME_LAT/HOME_LON"))
    rows.append(("preferences", f"{len(prefs.surf_spots)} surf, {len(prefs.kite_spots)} kite, {len(prefs.mtb_routes)} mtb ({sum(r.verified for r in prefs.mtb_routes)} verified)"))
    rows.append(("delivery channel", s.delivery_channel))
    for feat in ("email", "telegram", "maps", "aemet"):
        miss = s.missing_for(feat)
        rows.append((feat, "configured" if not miss else "missing " + ", ".join(miss)))
    rows.append(("google calendar", "client file present" if s.google_oauth_client_file.exists() else f"MISSING {s.google_oauth_client_file}"))
    rows.append(("calendar token", "present" if (s.state_dir / "google_token.json").exists() else "not yet authorised (run auth-calendar)"))
    rows.append(("surf-forecast x-check", "enabled" if s.enable_surf_forecast else "disabled"))
    rows.append(("windguru", "enabled (no permitted access path implemented)" if s.enable_windguru else "disabled"))
    if args.live:
        print("Live checks:")
        b = planner.collect(s, prefs)
        if b.home and b.route_fn and prefs.surf_spots:
            b.route_fn(b.home, prefs.surf_spots[0].location, None)  # one real routing call
        for st in list(b.statuses) + list(getattr(b, "_maps_status", {}).values()):
            print(f"  {'OK ' if st.ok and st.mode == 'live' else 'NO '} {st.name:22s} {st.mode:12s} {st.detail}")
        if s.telegram_bot_token:
            try:
                print(f"  OK  telegram bot @{telegram.check_bot(s.telegram_bot_token)}")
            except Exception as exc:  # noqa: BLE001
                print(f"  NO  telegram {exc}")
    for k, v in rows:
        print(f"{k:24s} {v}")
    return 0


def cmd_run(args) -> int:
    s = load_settings()
    _setup_logging(s.log_level, s.state_dir)
    prefs = load_preferences(s.preferences_file)
    now = datetime.now(s.tz)
    log.info("collecting data for window starting %s", now.date())
    bundle = planner.collect(s, prefs, now=now)
    report = planner.plan(bundle, prefs, s)
    report.changes_since_yesterday = diff.changes(report, snapshot.load_previous(s.state_dir))
    html = render.render_html(report, prefs)
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(render.render_text(report, prefs))
    if not args.no_snapshot:
        snapshot.save(report, s.state_dir)
    if args.send:
        subject = f"Sport Planner {report.window_start:%a %d %b}: {report.days[0].chosen.value} — {report.days[0].itinerary.spot_name or 'rest'}"
        try:
            receipt = deliver(s, html, render.render_text(report, prefs), subject)
        except Exception as exc:  # noqa: BLE001
            log.error("delivery failed: %s", exc)
            print(f"\nNOT delivered: {exc}")
            return 2
        log.info("delivered: %s", receipt)
        print(f"\nDelivered: {receipt}")
    return 0


def cmd_why(args) -> int:
    from .explain import explain

    s = load_settings()
    prefs = load_preferences(s.preferences_file)
    bundle = planner.collect(s, prefs, now=datetime.now(s.tz))
    print(explain(bundle, prefs))
    return 0


def cmd_auth_calendar(args) -> int:
    s = load_settings()
    from .providers.google_calendar import _credentials

    creds = _credentials(s.google_oauth_client_file, s.state_dir / "google_token.json")
    print("Calendar authorised (read-only). Token saved in", s.state_dir / "google_token.json")
    print("Scopes:", creds.scopes)
    return 0


def cmd_test_delivery(args) -> int:
    s = load_settings()
    now = datetime.now(s.tz)
    body = f"<b>Sport Planner</b> test message at {now:%a %d %b %H:%M}.\n\nIf you can read this, the {s.delivery_channel} channel works."
    try:
        print("sent:", deliver(s, body, body.replace("<b>", "").replace("</b>", ""), "Sport Planner — test"))
        return 0
    except Exception as exc:  # noqa: BLE001
        print("NOT sent:", exc)
        return 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sport-planner", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--live", action="store_true", help="also call every provider")
    st.set_defaults(fn=cmd_status)
    run = sub.add_parser("run")
    run.add_argument("--send", action="store_true", help="deliver via Telegram")
    run.add_argument("--json", action="store_true", help="print the report as JSON instead of text")
    run.add_argument("--no-snapshot", action="store_true", help="do not overwrite yesterday's snapshot")
    run.set_defaults(fn=cmd_run)
    sub.add_parser("why", help="show how every spot scored each day").set_defaults(fn=cmd_why)
    sub.add_parser("auth-calendar").set_defaults(fn=cmd_auth_calendar)
    sub.add_parser("test-delivery", help="send a short test through the configured channel").set_defaults(fn=cmd_test_delivery)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
