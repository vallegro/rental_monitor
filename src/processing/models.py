from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CanonicalListing:
    listing_id: str
    source: str
    source_listing_id: str
    source_url: str
    title: str | None
    address_line: str
    city: str | None
    state: str | None
    zip_code: str
    neighborhood: str | None
    latitude: float | None
    longitude: float | None
    rent_amount: int | None
    rent_currency: str
    rent_period: str
    beds: float | None
    baths: float | None
    sqft: int | None
    property_type: str | None
    available_date: str | None
    listing_status: str
    first_seen_at: str | None
    seen_at: str
    fingerprint: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "source": self.source,
            "source_listing_id": self.source_listing_id,
            "source_url": self.source_url,
            "title": self.title,
            "address_line": self.address_line,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "neighborhood": self.neighborhood,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "rent_amount": self.rent_amount,
            "rent_currency": self.rent_currency,
            "rent_period": self.rent_period,
            "beds": self.beds,
            "baths": self.baths,
            "sqft": self.sqft,
            "property_type": self.property_type,
            "available_date": self.available_date,
            "listing_status": self.listing_status,
            "first_seen_at": self.first_seen_at,
            "seen_at": self.seen_at,
            "fingerprint": self.fingerprint,
            "raw": self.raw,
        }


@dataclass(frozen=True, slots=True)
class ListingChange:
    listing_id: str
    change_type: str
    previous: CanonicalListing | None
    current: CanonicalListing | None
    changed_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "change_type": self.change_type,
            "previous": self.previous.to_dict() if self.previous is not None else None,
            "current": self.current.to_dict() if self.current is not None else None,
            "changed_fields": list(self.changed_fields),
        }


@dataclass(frozen=True, slots=True)
class DiffResult:
    new: tuple[ListingChange, ...]
    changed: tuple[ListingChange, ...]
    removed: tuple[ListingChange, ...]
    unchanged: tuple[CanonicalListing, ...]

    @property
    def update_count(self) -> int:
        return len(self.new) + len(self.changed) + len(self.removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "new": [item.to_dict() for item in self.new],
            "changed": [item.to_dict() for item in self.changed],
            "removed": [item.to_dict() for item in self.removed],
            "unchanged": [item.to_dict() for item in self.unchanged],
        }


@dataclass(frozen=True, slots=True)
class EmailSummary:
    subject: str
    text_body: str
    html_body: str | None
    listing_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "text_body": self.text_body,
            "html_body": self.html_body,
            "listing_ids": list(self.listing_ids),
        }


@dataclass(frozen=True, slots=True)
class DailyDigest:
    current_snapshot_id: str
    previous_snapshot_id: str | None
    snapshot_date: str
    zip_code: str
    current_listings: tuple[CanonicalListing, ...]
    previous_listings: tuple[CanonicalListing, ...]
    diff: DiffResult
    summary: EmailSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_snapshot_id": self.current_snapshot_id,
            "previous_snapshot_id": self.previous_snapshot_id,
            "snapshot_date": self.snapshot_date,
            "zip_code": self.zip_code,
            "current_listings": [item.to_dict() for item in self.current_listings],
            "previous_listings": [item.to_dict() for item in self.previous_listings],
            "diff": self.diff.to_dict(),
            "summary": self.summary.to_dict(),
        }
