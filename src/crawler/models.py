from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
import re


ZIP_CODE_PATTERN = re.compile(r"^\d{5}$")


def ensure_iso8601_utc(value: str, *, field_name: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include timezone information")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_timestamp_string(value: datetime | None = None) -> str:
    current = value or utc_now()
    return current.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_date_string(value: date | datetime | None = None) -> str:
    current = value or utc_now()
    if isinstance(current, datetime):
        current = current.astimezone(UTC).date()
    return current.isoformat()


def validate_zip_code(zip_code: str) -> str:
    if not ZIP_CODE_PATTERN.match(zip_code):
        raise ValueError(f"zip_code must be a 5-digit string, got {zip_code!r}")
    return zip_code


@dataclass(frozen=True, slots=True)
class SearchRequest:
    zip_code: str
    min_rent: int | None = None
    max_rent: int | None = None
    beds: int | None = None
    baths: float | None = None
    property_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_zip_code(self.zip_code)
        if self.min_rent is not None and self.min_rent < 0:
            raise ValueError("min_rent cannot be negative")
        if self.max_rent is not None and self.max_rent < 0:
            raise ValueError("max_rent cannot be negative")
        if self.min_rent is not None and self.max_rent is not None and self.min_rent > self.max_rent:
            raise ValueError("min_rent cannot be greater than max_rent")
        if self.beds is not None and self.beds < 0:
            raise ValueError("beds cannot be negative")
        if self.baths is not None and self.baths < 0:
            raise ValueError("baths cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "zip_code": self.zip_code,
            "min_rent": self.min_rent,
            "max_rent": self.max_rent,
            "beds": self.beds,
            "baths": self.baths,
            "property_types": list(self.property_types),
        }


@dataclass(frozen=True, slots=True)
class ProviderListing:
    external_id: str
    url: str
    address: str
    zip_code: str
    rent: int | None
    beds: float | None
    baths: float | None
    sqft: int | None
    listed_at: str | None
    provider_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.external_id:
            raise ValueError("external_id is required")
        if not self.url:
            raise ValueError("url is required")
        if not self.address:
            raise ValueError("address is required")
        validate_zip_code(self.zip_code)
        if self.rent is not None and self.rent < 0:
            raise ValueError("rent cannot be negative")
        if self.sqft is not None and self.sqft < 0:
            raise ValueError("sqft cannot be negative")
        if self.listed_at is not None:
            ensure_iso8601_utc(self.listed_at, field_name="listed_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "url": self.url,
            "address": self.address,
            "zip_code": self.zip_code,
            "rent": self.rent,
            "beds": self.beds,
            "baths": self.baths,
            "sqft": self.sqft,
            "listed_at": self.listed_at,
            "provider_payload": self.provider_payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderListing":
        return cls(
            external_id=str(data["external_id"]),
            url=str(data["url"]),
            address=str(data["address"]),
            zip_code=str(data["zip_code"]),
            rent=data.get("rent"),
            beds=data.get("beds"),
            baths=data.get("baths"),
            sqft=data.get("sqft"),
            listed_at=data.get("listed_at"),
            provider_payload=dict(data.get("provider_payload", {})),
        )


@dataclass(frozen=True, slots=True)
class DailyCrawlSnapshot:
    snapshot_id: str
    snapshot_date: str
    created_at: str
    provider: str
    zip_code: str
    query: dict[str, Any]
    listing_count: int
    listings: tuple[ProviderListing, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("snapshot_id is required")
        if not self.provider:
            raise ValueError("provider is required")
        validate_zip_code(self.zip_code)
        ensure_iso8601_utc(self.created_at, field_name="created_at")
        if self.listing_count != len(self.listings):
            raise ValueError("listing_count must match number of listings")
        if self.snapshot_date != utc_date_string(date.fromisoformat(self.snapshot_date)):
            raise ValueError("snapshot_date must be an ISO 8601 date")

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_date": self.snapshot_date,
            "created_at": self.created_at,
            "provider": self.provider,
            "zip_code": self.zip_code,
            "query": self.query,
            "listing_count": self.listing_count,
            "listings": [listing.to_dict() for listing in self.listings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailyCrawlSnapshot":
        listings = tuple(ProviderListing.from_dict(item) for item in data.get("listings", []))
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            snapshot_date=str(data["snapshot_date"]),
            created_at=str(data["created_at"]),
            provider=str(data["provider"]),
            zip_code=str(data["zip_code"]),
            query=dict(data.get("query", {})),
            listing_count=int(data["listing_count"]),
            listings=listings,
        )


@dataclass(frozen=True, slots=True)
class SnapshotWriteResult:
    snapshot: DailyCrawlSnapshot
    path: Path
    content_hash: str
