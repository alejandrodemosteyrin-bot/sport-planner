# Sport Planner

A personal five-day surf / kitesurf / MTB planner for the Conil de la Frontera area. Every morning at 09:00 (Europe/Madrid) it scores conditions at your spots, builds a timed itinerary around your calendar and the 14:30 lunch / 15:00 work defaults, and emails the report (Gmail), with Telegram available as an alternative channel.

It never invents numbers: when a source is missing or a route is unverified, the report says so.

## What it uses

| Need | Source | Access | Status in report |
|---|---|---|---|
| Waves, swell period/direction | [Open-Meteo Marine](https://open-meteo.com/en/docs/marine-weather-api) | free, no key | primary |
| Wind, gusts, rain, temperature, sunrise/sunset | [Open-Meteo Forecast](https://open-meteo.com/en/docs) | free, no key | primary |
| Official weather warnings (Cádiz) | [AEMET OpenData](https://opendata.aemet.es/) | free API key | live when key set |
| Calendar commitments | Google Calendar API | OAuth, **read-only** scope | live after one-time consent |
| Driving distance / time | Google Maps **Routes API** | API key | live; otherwise a labelled estimate |
| Report delivery | Gmail SMTP (default) or Telegram Bot API | Gmail App Password, or bot token + chat id | — |
| Surf-Forecast | public break pages | HTML parse, optional | cross-check only, never decides |
| Windguru | — | not implemented (JS-rendered; PRO API is paid) | reported as unavailable |

Tides are not modelled (Open-Meteo has none). Surf windows carry an explicit "check a tide table" warning.

## Install (macOS)

```bash
cd ~ && git clone <your-repo-url> sport-planner && cd sport-planner   # NOT in Downloads/Desktop/Documents (see below)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # then edit .env
mkdir -p secrets state
pytest                          # 23 tests, all offline
```

Python 3.11+ required (developed on 3.13). **macOS ships Python 3.9, which is too old**: install Python 3.12 from <https://www.python.org/downloads/macos/> first and create the venv with `python3.12 -m venv .venv`. The stock `pip` is also too old for `pyproject.toml`-only projects, so run `python -m pip install --upgrade pip` inside the venv before `pip install -e`. If you see `CERTIFICATE_VERIFY_FAILED`, run `"/Applications/Python 3.12/Install Certificates.command"` once.

### Fill in `.env`

1. **Home**: `HOME_LAT` / `HOME_LON` in decimal degrees. These never go in the repo.
2. **Email (default)**: `EMAIL_TO` is where the report goes; `GMAIL_USER` is the Gmail account that sends it (can be the same). `GMAIL_APP_PASSWORD` is a 16-character *App Password*: Google Account → Security → 2-Step Verification (must be on) → App passwords → create one named "sport-planner". Never your normal password. Check with `sport-planner test-delivery`.
   **Telegram (optional, later)**: set `DELIVERY_CHANNEL=telegram`, talk to `@BotFather` → `/newbot` → token into `TELEGRAM_BOT_TOKEN`; message your bot once, open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id":…}` into `TELEGRAM_CHAT_ID`.
3. **Google Maps**: in Google Cloud Console create a project, enable **Routes API**, create an API key restricted to that API → `GOOGLE_MAPS_API_KEY`. The free monthly credit covers this volume comfortably (≈10–20 requests per day).
4. **Google Calendar**: same project → enable **Google Calendar API** → OAuth consent screen (External, add yourself as test user) → Credentials → *OAuth client ID*, type **Desktop app** → download JSON to `secrets/client_secret.json`. Then run `sport-planner auth-calendar` once; a browser opens, you approve read-only access, the token is stored in `state/google_token.json`.
   **Work calendar on another Google account?** Share it with your personal account (work account → Calendar settings → Share with specific people → your Gmail, "See all event details" or "See only free/busy"), accept the invite, and add its id to `GOOGLE_CALENDAR_IDS=primary,you@work.com`.
5. **AEMET**: request a key at <https://opendata.aemet.es/centrodedescargas/altaUsuario> (arrives by email) → `AEMET_API_KEY`.

### Check everything

```bash
sport-planner status          # config overview
sport-planner status --live   # calls every provider and prints live / fallback / unavailable
sport-planner run             # full report in the terminal, no delivery
sport-planner run --send      # ...and deliver through DELIVERY_CHANNEL (email by default)
```

### Schedule at 09:00

```bash
./deploy/install_launchd.sh
```

**The project must not live in Downloads, Desktop or Documents**: macOS blocks background jobs from those folders ("Operation not permitted", exit 126). `~/sport-planner` is a good location; the installer refuses protected paths.

This installs a per-user launchd job that runs `deploy/run_daily.sh` (`sport-planner run --send`) at 09:00 in the Mac's local time zone (DST handled by macOS). If the Mac is asleep at 09:00, the job runs at the next wake; if it is powered off, that day is skipped. Logs: `state/launchd.*.log` and `state/sport_planner.log`.

Automation is only "active" once you have seen a scheduled run arrive in your inbox: `launchctl kickstart -k gui/$(id -u)/com.sportplanner.daily` triggers one now. `./deploy/install_launchd.sh --uninstall` removes it.

## Running in the cloud (GitHub Actions) — recommended

Runs every morning without your Mac. `.github/workflows/daily.yml` schedules both 07:00 and 08:00 UTC and runs only the slot that is 09:00 in Madrid, so DST is handled. GitHub may start scheduled runs 5–30 min late.

1. Push this project to a **private** GitHub repository.
2. Repository → Settings → Secrets and variables → Actions → *New repository secret*, one per line of your `.env`:
   `HOME_LAT`, `HOME_LON`, `EMAIL_TO`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `GOOGLE_MAPS_API_KEY`, optional `AEMET_API_KEY`, optional `GOOGLE_CALENDAR_IDS`,
   and `GOOGLE_TOKEN_JSON` = the full contents of `state/google_token.json` (on the Mac: `pbcopy < state/google_token.json`, then paste).
3. **Publish the OAuth app**: Google Cloud Console → Google Auth Platform → Audience → *Publish app*. Apps left in "Testing" get refresh tokens that expire after 7 days, which silently breaks the calendar. After publishing, run `sport-planner auth-calendar` once more on the Mac and update the `GOOGLE_TOKEN_JSON` secret.
4. Actions tab → *Daily sport report* → *Run workflow*. When that email arrives, it is live.
5. Remove the Mac job to avoid duplicate emails: `./deploy/install_launchd.sh --uninstall`.

GitHub emails you if a run fails. "Changes since yesterday" uses the Actions cache to keep the previous report.

## Preferences

`config/preferences.yaml` holds spots, your kite sizes (9 / 12 m), level, wave/wind bands, MTB routes, buffers and the weekday rules. Spot coordinates are public beach locations. Key things to tune:

- `rider.kite_wind_bands_kn` — the usable and ideal wind per kite.
- `surf_spots[].swell_dirs_deg` / `offshore_dirs_deg` — starting values for the Conil area; refine as you learn the spots.
- `kite_spots[].unsafe_wind_dirs_deg` — only straight-offshore directions are excluded. Levante is allowed at Valdevaqueros and Los Lances and flagged as gusty; the planner informs rather than vetoes. Hard stops that remain: thunderstorms and gusts ≥ 45 kn.
- `mtb_routes[].verified` — false until you have ridden the route; the report labels unverified routes as suggestions.
- `constraints` — 90 min max drive, 75 min minimum / 90 min maximum session, 08:00 earliest departure, buffers, campervan settings.

## How a day is decided

1. Surf and kite are scored **independently** (0–100) per hour per spot, daylight only. Surf rewards waves inside your range (bigger is not better), period, swell direction and offshore/light wind. Kite sizes the kite for the **gusts**, not the average (`rider.gust_weight`, default 0.6 of the way from average to gust: 20 kn gusting 29 → 9 m), penalises lulls when the average is below the chosen kite's ideal range, weights steadiness (gust factor) as the largest quality factor after the wind itself, and applies per-spot gust corrections by direction (`kite_spots[].gust_adjust`, e.g. Levante at Valdevaqueros ×1.2). Straight-offshore wind, gusts ≥ 45 kn and thunder score 0; everything else is a warning in the report.
2. The best ≥ 2 h window per sport is turned into an itinerary: departure → drive (Google Maps, traffic-aware) → parking/walk → setup → session → pack-down → change → drive home → safety buffer. On weekdays the session must end so you are home 20 min before lunch at 14:30. Confirmed calendar events are never overlapped.
3. The higher-scoring feasible sport wins. If neither is worthwhile, an MTB route that fits the time and the weather is proposed. If nothing fits: rest day.
4. **Flex rule** (`constraints.flex`): on a weekday whose best surf/kite score is ≥ 85 and with no meeting before 16:00 (or before your first meeting, whichever is earlier), the report adds a **proposal** to start work later: the session is extended to at most 150 min and the exact work-ready time is given. It is a proposal only; the 15:00 default stays in the itinerary.
5. If a weekday session would gain ≥ 30 min by working from the campervan (spot must allow it), the report adds a **proposal** with parking, connectivity assumption, lunch logistics and the exact work-ready time. It is never applied: your 15:00 work start stays as the schedule unless you decide otherwise. The planner has no code path that writes to your calendar.
6. Confidence: days 1–2 high, day 3 medium, days 4–5 low; lowered when routes are estimates, the calendar could not be read, or data is missing.

## Report sections

1. Five-day overview · 2. Today's itinerary with evidence and route link · 3. Best surf / kite / MTB day and strongest overall · 4. Calendar conflicts and proposals · 5. Changes since yesterday (from `state/latest_report.json`) · 6. Sources with timestamps, mode (live / fallback / disabled / unavailable) and what was missing.

## Tests

`pytest` runs 23 offline tests covering scoring rules, exactly-five-day windows, weekday lunch/work constraints, calendar conflicts, weekend sessions, routing failure fallback, forecast gaps, campervan and flex proposals, the October DST transition, snapshot diff, Telegram chunking and email multipart/dispatch. Live checks are manual via `sport-planner status --live`.

## Layout

```
sport_planner/
  settings.py        env-driven typed settings
  preferences.py     YAML preferences model
  models.py          typed domain models, explicit units
  providers/         one adapter per source (open_meteo, aemet, google_calendar, google_maps, surf_forecast, windguru)
  scoring/           surf.py, kite.py, mtb.py, common.py
  planning/          calendar_rules.py, itinerary.py, planner.py
  report/            render.py (HTML + plain text), snapshot.py, diff.py
  delivery/          email.py (Gmail SMTP), telegram.py
  cli.py
config/preferences.yaml
deploy/              launchd template + install script
tests/
```

## Limitations and notes

- Surf-Forecast parsing depends on their page markup and is a cross-check only; set `ENABLE_SURF_FORECAST=0` if you prefer not to fetch their pages. Windguru is listed for the reader but not fetched.
- The AEMET endpoint used is `avisos_cap/ultimoelaborado/area/61` (Andalucía), filtered to areas mentioning "Cádiz". Verify on the first live run with `status --live`.
- Route estimates (no Maps key or API error) are straight-line × 1.35 at 60 km/h and are always labelled as not verified.
- No tide data; no spot-level crowd or sandbank knowledge — refine spot windows over time.
- Secrets: `.env`, `secrets/`, `state/` are gitignored. `.env.example` has placeholders only.
