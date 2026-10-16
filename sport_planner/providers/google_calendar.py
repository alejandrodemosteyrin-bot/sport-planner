"""Google Calendar — read-only via OAuth (scope calendar.readonly).

First run opens a browser for consent; the refresh token is stored under
STATE_DIR/google_token.json (gitignored). The planner never writes to the
calendar: there is no code path for creating, moving or deleting events.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..models import CalendarEvent
from .base import ProviderResult, now_utc

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _credentials(client_file: Path, token_file: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not client_file.exists():
            raise FileNotFoundError(f"OAuth client file not found: {client_file}")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
        creds = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _parse_event(item: dict, tz: ZoneInfo, calendar_id: str) -> CalendarEvent | None:
    start, end = item.get("start", {}), item.get("end", {})
    if item.get("status") == "cancelled":
        return None
    if "date" in start:  # all-day
        s = datetime.combine(date.fromisoformat(start["date"]), time.min, tzinfo=tz)
        e = datetime.combine(date.fromisoformat(end["date"]), time.min, tzinfo=tz)
        all_day = True
    else:
        s = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
        e = datetime.fromisoformat(end["dateTime"]).astimezone(tz)
        all_day = False
    return CalendarEvent(
        id=item.get("id", ""),
        summary=item.get("summary", "(no title)"),
        start=s,
        end=e,
        all_day=all_day,
        calendar_id=calendar_id,
    )


def fetch_events(
    client_file: Path,
    token_file: Path,
    calendar_ids: list[str],
    window_start: date,
    days: int,
    tz: ZoneInfo,
    *,
    service=None,
) -> ProviderResult[list[CalendarEvent]]:
    t0 = datetime.combine(window_start, time.min, tzinfo=tz)
    t1 = t0 + timedelta(days=days)
    try:
        if service is None:
            from googleapiclient.discovery import build

            service = build("calendar", "v3", credentials=_credentials(client_file, token_file), cache_discovery=False)
        events: list[CalendarEvent] = []
        for cid in calendar_ids:
            page = None
            while True:
                resp = (
                    service.events()
                    .list(
                        calendarId=cid,
                        timeMin=t0.isoformat(),
                        timeMax=t1.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                        pageToken=page,
                    )
                    .execute()
                )
                for item in resp.get("items", []):
                    ev = _parse_event(item, tz, cid)
                    if ev:
                        events.append(ev)
                page = resp.get("nextPageToken")
                if not page:
                    break
        return ProviderResult("google-calendar", events, "live", "https://www.googleapis.com/calendar/v3", now_utc())
    except Exception as exc:  # noqa: BLE001
        return ProviderResult("google-calendar", None, "unavailable", None, None, f"{type(exc).__name__}: {exc}")
