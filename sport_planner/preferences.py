"""Load and validate config/preferences.yaml."""

from __future__ import annotations

from datetime import time
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from .models import KiteSpot, MtbRoute, SurfSpot


class WindBand(BaseModel):
    min: float
    ideal_min: float
    ideal_max: float
    max: float


class Rider(BaseModel):
    level: str = "advanced_beginner"
    kite_sizes_m: list[int] = [9, 12]
    kite_wind_bands_kn: dict[int, WindBand]
    max_gust_factor: float = 1.6
    gust_weight: float = 0.6
    surf_wave_min_m: float = 0.6
    surf_wave_max_m: float = 1.6
    mtb_speed_kmh: float = 13.0
    mtb_climb_min_per_100m: float = 2.5
    mtb_max_distance_km: float = 40.0


class Buffers(BaseModel):
    gear_setup: int = 20
    pack_down: int = 20
    change_shower: int = 15
    traffic_safety: int = 15


class Campervan(BaseModel):
    available: bool = False
    work_setup_min: int = 20
    connectivity_note: str = ""


class Flex(BaseModel):
    """'Stay longer when it is really good' — produces a later-work-start PROPOSAL on weekdays."""

    enabled: bool = True
    min_score: int = 85
    latest_work_start: time = time(16, 0)
    max_session_min: int = 150

    @field_validator("latest_work_start", mode="before")
    @classmethod
    def _parse_time(cls, v):
        if isinstance(v, str):
            h, m = v.split(":")
            return time(int(h), int(m))
        return v


class Constraints(BaseModel):
    max_drive_min: int = 90
    min_session_min: int = 75
    max_session_min: int = 90
    max_session_min_weekend: int = 90
    weekday_lunch: time = time(14, 30)
    weekday_work_start: time = time(15, 0)
    earliest_departure: time = time(8, 0)
    lunch_duration_min: int = 30
    work_from_home_default: bool = True
    arrive_home_before_lunch_min: int = 20
    buffers_min: Buffers = Field(default_factory=Buffers)
    campervan: Campervan = Field(default_factory=Campervan)
    flex: Flex = Field(default_factory=Flex)

    @field_validator("weekday_lunch", "weekday_work_start", "earliest_departure", mode="before")
    @classmethod
    def _parse_time(cls, v):
        if isinstance(v, str):
            h, m = v.split(":")
            return time(int(h), int(m))
        return v


class Preferences(BaseModel):
    rider: Rider
    constraints: Constraints
    surf_spots: list[SurfSpot]
    kite_spots: list[KiteSpot]
    mtb_routes: list[MtbRoute]

    def surf_spot(self, spot_id: str) -> SurfSpot:
        return next(s for s in self.surf_spots if s.id == spot_id)

    def kite_spot(self, spot_id: str) -> KiteSpot:
        return next(s for s in self.kite_spots if s.id == spot_id)

    def mtb_route(self, route_id: str) -> MtbRoute:
        return next(r for r in self.mtb_routes if r.id == route_id)


def load_preferences(path: Path) -> Preferences:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Preferences.model_validate(raw)
