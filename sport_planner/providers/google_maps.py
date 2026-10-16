"""Google Maps Routes API — verified driving distance and duration.

POST https://routes.googleapis.com/directions/v2:computeRoutes
Docs: https://developers.google.com/maps/documentation/routes/compute_route_directions
When the key is missing or the call fails, the planner receives a clearly
labelled *estimate* (straight-line distance × road factor) so the itinerary
math can still run, and the report states that the time is NOT verified.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import httpx

from ..models import LatLon, RouteResult
from .base import ProviderResult, make_client, now_utc

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration,routes.distanceMeters,routes.staticDuration"


def maps_link(origin: LatLon, dest: LatLon) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin.maps_str()}&destination={dest.maps_str()}&travelmode=driving"
    )


def _haversine_km(a: LatLon, b: LatLon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def estimate_route(origin: LatLon, dest: LatLon) -> RouteResult:
    """Fallback only. Rural Cádiz roads: ~1.35× straight line at ~60 km/h average."""
    km = _haversine_km(origin, dest) * 1.35
    return RouteResult(
        origin=origin,
        destination=dest,
        distance_km=round(km, 1),
        duration_min=round(km / 60 * 60, 0),
        verified=False,
        maps_url=maps_link(origin, dest),
        source="estimate (straight-line × 1.35, 60 km/h) — NOT verified",
    )


def compute_route(
    origin: LatLon,
    dest: LatLon,
    api_key: str | None,
    *,
    departure_time: datetime | None = None,
    client: httpx.Client | None = None,
) -> ProviderResult[RouteResult]:
    if not api_key:
        return ProviderResult(
            "google-maps-routes", estimate_route(origin, dest), "fallback", None, None, "GOOGLE_MAPS_API_KEY not set"
        )
    body: dict = {
        "origin": {"location": {"latLng": {"latitude": origin.lat, "longitude": origin.lon}}},
        "destination": {"location": {"latLng": {"latitude": dest.lat, "longitude": dest.lon}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "units": "METRIC",
    }
    # The API rejects departure times in the past; only send future ones.
    if departure_time and departure_time > datetime.now(timezone.utc):
        body["departureTime"] = departure_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    own = client is None
    client = client or make_client()
    try:
        r = client.post(
            ROUTES_URL,
            json=body,
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK},
        )
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
                reason = ", ".join(d.get("reason", "") for d in err.get("details", []) if d.get("reason")) or err.get("status", "")
                raise ValueError(f"HTTP {r.status_code} {reason}: {err.get('message', r.text[:200])}")
            except ValueError:
                raise
            except Exception:  # noqa: BLE001 — non-JSON error body
                raise ValueError(f"HTTP {r.status_code}: {r.text[:200]}")
        routes = r.json().get("routes") or []
        if not routes:
            raise ValueError("no routes returned")
        rt = routes[0]
        secs = float(str(rt["duration"]).rstrip("s"))
        res = RouteResult(
            origin=origin,
            destination=dest,
            distance_km=round(rt["distanceMeters"] / 1000, 1),
            duration_min=round(secs / 60, 0),
            verified=True,
            departure_time=departure_time,
            maps_url=maps_link(origin, dest),
            source="Google Maps Routes API (traffic-aware)",
        )
        return ProviderResult("google-maps-routes", res, "live", ROUTES_URL, now_utc())
    except Exception as exc:  # noqa: BLE001
        return ProviderResult(
            "google-maps-routes",
            estimate_route(origin, dest),
            "fallback",
            ROUTES_URL,
            None,
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        if own:
            client.close()
