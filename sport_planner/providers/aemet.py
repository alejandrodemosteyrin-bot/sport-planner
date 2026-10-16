"""AEMET OpenData — official weather warnings (CAP format) for Andalucía.

Endpoint: /api/avisos_cap/ultimoelaborado/area/{area}   (area 61 = Andalucía)
The API answers with a JSON envelope whose "datos" field is a URL to the payload:
a tar archive of CAP XML files (sometimes a single XML).  Requires a free API key.
Docs: https://opendata.aemet.es/dist/index.html
"""

from __future__ import annotations

import io
import tarfile
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from ..models import WeatherAlert
from .base import ProviderResult, make_client, now_utc

BASE = "https://opendata.aemet.es/opendata/api"
ANDALUCIA_AREA = "61"
CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}


def _parse_cap(xml_bytes: bytes, province_filter: str | None) -> list[WeatherAlert]:
    out: list[WeatherAlert] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for info in root.findall(".//cap:info", CAP_NS):
        lang = (info.findtext("cap:language", default="", namespaces=CAP_NS) or "").lower()
        if lang and not lang.startswith("es"):
            continue
        severity = info.findtext("cap:severity", default="Unknown", namespaces=CAP_NS) or "Unknown"
        headline = info.findtext("cap:headline", default="", namespaces=CAP_NS) or ""
        onset = info.findtext("cap:onset", default=None, namespaces=CAP_NS)
        expires = info.findtext("cap:expires", default=None, namespaces=CAP_NS)
        for area in info.findall("cap:area", CAP_NS):
            desc = area.findtext("cap:areaDesc", default="", namespaces=CAP_NS) or ""
            if province_filter and province_filter.lower() not in desc.lower():
                continue
            if severity.lower() in ("minor", "unknown") and not headline:
                continue
            out.append(
                WeatherAlert(
                    source="AEMET",
                    headline=headline or desc,
                    severity=severity,
                    onset=datetime.fromisoformat(onset) if onset else None,
                    expires=datetime.fromisoformat(expires) if expires else None,
                    area=desc,
                    url="https://www.aemet.es/es/eltiempo/prediccion/avisos",
                )
            )
    return out


def fetch_alerts(
    api_key: str | None,
    *,
    province_filter: str | None = "Cádiz",
    client: httpx.Client | None = None,
) -> ProviderResult[list[WeatherAlert]]:
    url = f"{BASE}/avisos_cap/ultimoelaborado/area/{ANDALUCIA_AREA}"
    if not api_key:
        return ProviderResult("aemet-alerts", None, "disabled", url, None, "AEMET_API_KEY not set")
    own = client is None
    client = client or make_client()
    try:
        env = client.get(url, params={"api_key": api_key}).json()
        if env.get("estado") != 200 or "datos" not in env:
            return ProviderResult("aemet-alerts", None, "unavailable", url, None, f"AEMET envelope: {env}")
        payload = client.get(env["datos"])
        payload.raise_for_status()
        raw = payload.content
        alerts: list[WeatherAlert] = []
        if tarfile.is_tarfile(io.BytesIO(raw)):
            with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
                for m in tf.getmembers():
                    if m.isfile():
                        f = tf.extractfile(m)
                        if f:
                            alerts += _parse_cap(f.read(), province_filter)
        else:
            alerts += _parse_cap(raw, province_filter)
        # Only keep alerts that are not yet expired.
        now = now_utc()
        alerts = [a for a in alerts if a.expires is None or a.expires > now]
        return ProviderResult("aemet-alerts", alerts, "live", url, now_utc())
    except Exception as exc:  # noqa: BLE001
        return ProviderResult("aemet-alerts", None, "unavailable", url, None, f"{type(exc).__name__}: {exc}")
    finally:
        if own:
            client.close()
