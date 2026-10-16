"""Typed runtime settings loaded from environment / .env.

Nothing personal is hardcoded here: home coordinates, tokens and keys come
from the environment only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    home_lat: float | None = None
    home_lon: float | None = None
    home_label: str = "Home"

    timezone: str = "Europe/Madrid"
    report_language: str = "en"

    delivery_channel: Literal["email", "telegram"] = "email"

    email_to: str | None = None
    gmail_user: str | None = None
    gmail_app_password: str | None = None

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    google_maps_api_key: str | None = None
    google_oauth_client_file: Path = Path("secrets/client_secret.json")
    google_calendar_ids: str = "primary"

    aemet_api_key: str | None = None

    enable_surf_forecast: bool = True
    enable_windguru: bool = False

    state_dir: Path = Path("state")
    preferences_file: Path = Path("config/preferences.yaml")
    log_level: str = "INFO"

    # Network
    http_timeout_s: float = Field(default=20.0, gt=0)

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        ZoneInfo(v)  # raises if unknown
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def calendar_ids(self) -> list[str]:
        return [c.strip() for c in self.google_calendar_ids.split(",") if c.strip()]

    @property
    def home_configured(self) -> bool:
        return self.home_lat is not None and self.home_lon is not None

    def missing_for(self, feature: str) -> list[str]:
        """Names of env vars still unset for a given feature."""
        need = {
            "home": ["HOME_LAT", "HOME_LON"],
            "email": ["EMAIL_TO", "GMAIL_USER", "GMAIL_APP_PASSWORD"],
            "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
            "maps": ["GOOGLE_MAPS_API_KEY"],
            "aemet": ["AEMET_API_KEY"],
        }[feature]
        values = {
            "HOME_LAT": self.home_lat,
            "HOME_LON": self.home_lon,
            "EMAIL_TO": self.email_to,
            "GMAIL_USER": self.gmail_user,
            "GMAIL_APP_PASSWORD": self.gmail_app_password,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id,
            "GOOGLE_MAPS_API_KEY": self.google_maps_api_key,
            "AEMET_API_KEY": self.aemet_api_key,
        }
        return [n for n in need if values[n] in (None, "")]


def load_settings() -> Settings:
    return Settings()
