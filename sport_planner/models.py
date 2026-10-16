"""Typed domain models. Units are explicit in field names:
_m metres, _s seconds, _km kilometres, _min minutes, _kn knots, _deg compass degrees, _c celsius, _mm millimetres.
All datetimes are timezone-aware.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Activity(str, Enum):
    SURF = "surf"
    KITE = "kite"
    MTB = "mtb"
    REST = "rest"


Confidence = Literal["high", "medium", "low"]


class LatLon(BaseModel):
    lat: float
    lon: float

    def maps_str(self) -> str:
        return f"{self.lat:.6f},{self.lon:.6f}"


# ---------- Preferences-side models (loaded from YAML) ----------


class SpotBase(BaseModel):
    id: str
    name: str
    location: LatLon
    parking_walk_min: int = 5
    campervan_ok: bool = False
    campervan_connectivity_note: str | None = None
    notes: str | None = None


DegWindow = tuple[int, int]  # (from, to) clockwise, degrees


class SurfSpot(SpotBase):
    faces_deg: int = Field(description="Direction the beach faces, degrees")
    swell_dirs_deg: list[DegWindow] = Field(description="Working swell windows")
    offshore_dirs_deg: list[DegWindow] = Field(description="Offshore wind windows")
    wave_min_m: float = 0.6
    wave_max_m: float = 1.6
    min_period_s: float = 7.0


class GustAdjust(BaseModel):
    dirs_deg: list[DegWindow]
    factor: float = Field(gt=0.5, lt=2.0, description="Multiply model gusts by this for these directions")


class KiteSpot(SpotBase):
    safe_wind_dirs_deg: list[DegWindow] = Field(description="Launchable wind windows")
    unsafe_wind_dirs_deg: list[DegWindow] = Field(default_factory=list, description="Offshore / forbidden windows")
    gust_adjust: list[GustAdjust] = Field(default_factory=list, description="Local gust corrections by direction")
    restrictions: str | None = None


class MtbRoute(BaseModel):
    id: str
    name: str
    start: LatLon
    distance_km: float
    elevation_gain_m: float
    terrain: str = "mixed"
    verified: bool = Field(default=False, description="True only for routes the user has ridden/checked")
    source_url: str | None = None
    notes: str | None = None


# ---------- Forecast / data models ----------


class SeaPoint(BaseModel):
    time: datetime
    wave_height_m: float | None = None
    swell_height_m: float | None = None
    swell_period_s: float | None = None
    swell_dir_deg: float | None = None


class WindPoint(BaseModel):
    time: datetime
    wind_kn: float | None = None
    gust_kn: float | None = None
    wind_dir_deg: float | None = None
    temp_c: float | None = None
    precip_mm: float | None = None
    precip_prob_pct: float | None = None
    weather_code: int | None = None


class DayLight(BaseModel):
    day: date
    sunrise: datetime
    sunset: datetime


class WeatherAlert(BaseModel):
    source: str
    headline: str
    severity: str
    onset: datetime | None = None
    expires: datetime | None = None
    area: str | None = None
    url: str | None = None


class CalendarEvent(BaseModel):
    id: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool = False
    calendar_id: str = "primary"


class RouteResult(BaseModel):
    origin: LatLon
    destination: LatLon
    distance_km: float
    duration_min: float
    verified: bool = Field(description="True when from a live Google Maps Routes call")
    departure_time: datetime | None = None
    maps_url: str
    source: str


class ProviderStatus(BaseModel):
    name: str
    ok: bool
    mode: Literal["live", "fallback", "disabled", "unavailable"]
    detail: str = ""
    retrieved_at: datetime | None = None
    source_url: str | None = None


# ---------- Scoring / planning ----------


class ConditionWindow(BaseModel):
    """A contiguous span where an activity is worthwhile at one spot."""

    activity: Activity
    spot_id: str
    spot_name: str
    start: datetime
    end: datetime
    score: int = Field(ge=0, le=100)
    reasons: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, str] = {}
    kite_size_m: int | None = None

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class Proposal(BaseModel):
    """A suggested schedule change. Never applied automatically."""

    kind: Literal["later_work_start", "campervan_remote_work"]
    work_ready_time: datetime
    parking: str
    connectivity_assumption: str
    setup_min: int
    lunch_logistics: str
    rationale: str


class Itinerary(BaseModel):
    day: date
    activity: Activity
    spot_id: str | None = None
    spot_name: str | None = None
    depart_home: datetime | None = None
    arrive_spot: datetime | None = None
    session_start: datetime | None = None
    session_end: datetime | None = None
    leave_spot: datetime | None = None
    arrive_home: datetime | None = None
    lunch: datetime | None = None
    work_start: datetime | None = None
    drive_out: RouteResult | None = None
    drive_back: RouteResult | None = None
    activity_min: int = 0
    round_trip_km: float = 0.0
    driving_min: float = 0.0
    mtb_route_id: str | None = None
    proposal: Proposal | None = None
    conflicts: list[str] = []
    notes: list[str] = []


class DayPlan(BaseModel):
    day: date
    is_weekend: bool
    chosen: Activity
    confidence: Confidence
    reason: str
    best_surf: ConditionWindow | None = None
    best_kite: ConditionWindow | None = None
    mtb_route_id: str | None = None
    itinerary: Itinerary
    daylight: DayLight | None = None
    missing_data: list[str] = []
    calendar_events: list[CalendarEvent] = []


class Report(BaseModel):
    generated_at: datetime
    window_start: date
    window_end: date
    days: list[DayPlan]
    alerts: list[WeatherAlert] = []
    providers: list[ProviderStatus] = []
    changes_since_yesterday: list[str] = []

    @model_validator(mode="after")
    def _five_days(self) -> "Report":
        if len(self.days) != 5:
            raise ValueError(f"A report must cover exactly five days, got {len(self.days)}")
        return self
