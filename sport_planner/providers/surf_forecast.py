"""Surf-Forecast.com — OPTIONAL best-effort cross-check (public break pages).

This adapter never drives the decision; it only adds a labelled second opinion
(daily max wave height / period) next to the Open-Meteo evidence. The HTML is
parsed defensively and any structural change results in "unavailable", not in
invented numbers. Enable/disable with ENABLE_SURF_FORECAST.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .base import ProviderResult, make_client, now_utc

BREAK_URL = "https://www.surf-forecast.com/breaks/{slug}/forecasts/latest"

# Surf-Forecast slugs for the configured spots. Add more as you add spots.
# Verified against https://www.surf-forecast.com/countries/Spain/breaks (Oct 2026).
SLUGS = {
    "el_palmar": "Playa-El-Palmar",
    "conil_fontanilla": "Conil",
    "zahora": None,  # no dedicated break page; nearest is Playa-El-Palmar
    "canos_de_meca": "Canosde-Meca",
}


def _floats(cells) -> list[float | None]:
    out: list[float | None] = []
    for c in cells:
        txt = c.get_text(" ", strip=True).replace(",", ".")
        try:
            out.append(float(txt.split()[0]))
        except (ValueError, IndexError):
            out.append(None)
    return out


def fetch_break_summary(
    spot_id: str, tz: ZoneInfo, *, enabled: bool = True, client: httpx.Client | None = None
) -> ProviderResult[dict[date, dict[str, float]]]:
    slug = SLUGS.get(spot_id)
    if not enabled:
        return ProviderResult("surf-forecast", None, "disabled", None, None, "ENABLE_SURF_FORECAST=0")
    if not slug:
        return ProviderResult("surf-forecast", None, "unavailable", None, None, f"no slug for {spot_id}")
    url = BREAK_URL.format(slug=slug)
    own = client is None
    client = client or make_client()
    try:
        r = client.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.select_one("table.forecast-table__table") or soup.select_one("table")
        if table is None:
            raise ValueError("forecast table not found")
        rows = {tr.get("data-row-name"): tr for tr in table.select("tr[data-row-name]")}
        days_row = rows.get("days")
        wave_row = rows.get("wave-height")
        period_row = rows.get("periods")
        if not (days_row and wave_row and period_row):
            raise ValueError("expected rows missing (days/wave-height/periods)")
        day_cells = days_row.find_all(["td", "th"])
        day_spans = [int(c.get("colspan", 1)) for c in day_cells]
        waves = _floats(wave_row.find_all("td"))
        periods = _floats(period_row.find_all("td"))
        today = datetime.now(tz).date()
        summary: dict[date, dict[str, float]] = {}
        idx = 0
        for i, span in enumerate(day_spans):
            w = [x for x in waves[idx : idx + span] if x is not None]
            p = [x for x in periods[idx : idx + span] if x is not None]
            idx += span
            if not w:
                continue
            d = date.fromordinal(today.toordinal() + i)
            summary[d] = {"wave_max_m": max(w), "period_max_s": max(p) if p else float("nan")}
        if not summary:
            raise ValueError("no numeric values parsed")
        res = ProviderResult("surf-forecast", summary, "live", url, now_utc())
        res.warnings.append("Surf-Forecast is a best-effort cross-check, not the decision source")
        return res
    except Exception as exc:  # noqa: BLE001
        return ProviderResult("surf-forecast", None, "unavailable", url, None, f"{type(exc).__name__}: {exc}")
    finally:
        if own:
            client.close()
