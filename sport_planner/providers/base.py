"""Common provider plumbing: a result wrapper that never hides failure."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, TypeVar

import httpx

from ..models import ProviderStatus

T = TypeVar("T")


class ProviderError(RuntimeError):
    """Raised by adapters when a source cannot be used. Callers decide how to report it."""


@dataclass
class ProviderResult(Generic[T]):
    name: str
    data: T | None
    mode: str  # live | fallback | disabled | unavailable
    source_url: str | None = None
    retrieved_at: datetime | None = None
    detail: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.data is not None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            ok=self.ok,
            mode=self.mode,  # type: ignore[arg-type]
            detail=self.detail,
            retrieved_at=self.retrieved_at,
            source_url=self.source_url,
        )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_client(timeout_s: float = 30.0, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """One place to build HTTP clients so tests can inject a MockTransport.
    Real clients retry failed connections (e.g. TLS handshake timeouts) 3 times."""
    return httpx.Client(
        timeout=httpx.Timeout(timeout_s, connect=15.0),
        transport=transport or httpx.HTTPTransport(retries=3),
        headers={"User-Agent": "sport-planner/0.1 (personal, non-commercial)"},
        follow_redirects=True,
    )
