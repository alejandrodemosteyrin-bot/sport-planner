"""Windguru — OPTIONAL. Not implemented as a data source.

Windguru's public forecast pages are rendered client-side by JavaScript, so a
plain HTTP fetch returns only a loading shell. Scraping them would require a
headless browser and sits in a grey area of Windguru's terms; Windguru offers a
paid PRO API for programmatic access. Until a permitted access path exists this
adapter reports itself as unavailable and the report says so explicitly.
"""

from __future__ import annotations

from .base import ProviderResult

SPOT_URL = "https://www.windguru.cz/{spot_id}"
# Public Windguru spot numbers (for the human reader, not for fetching)
SPOT_NUMBERS = {
    "valdevaqueros": 43,
    "los_lances": 48,
    "el_palmar": 236718,
}


def fetch(spot_id: str, *, enabled: bool = False) -> ProviderResult[None]:
    url = SPOT_URL.format(spot_id=SPOT_NUMBERS.get(spot_id, "")) if spot_id in SPOT_NUMBERS else None
    if not enabled:
        return ProviderResult("windguru", None, "disabled", url, None, "ENABLE_WINDGURU=0")
    return ProviderResult(
        "windguru",
        None,
        "unavailable",
        url,
        None,
        "page is JavaScript-rendered; no permitted programmatic path implemented (PRO API is paid)",
    )
