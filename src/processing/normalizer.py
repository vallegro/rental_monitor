from __future__ import annotations

from hashlib import sha1
import json
import re
from typing import Any, Mapping

from ..crawler.models import DailyCrawlSnapshot, ProviderListing, validate_zip_code
from .models import CanonicalListing


STATE_ZIP_PATTERN = re.compile(r"^(?P<state>[A-Z]{2})(?:\s+(?P<zip_code>\d{5})(?:-\d{4})?)?$")


def normalize_listing(
    source: str,
    item: ProviderListing,
    *,
    seen_at: str,
    first_seen_at: str | None = None,
) -> CanonicalListing:
    address_line, city, state, zip_code = _parse_address(item.address, fallback_zip_code=item.zip_code)
    source_listing_id = str(item.external_id)
    property_type = _optional_text(item.provider_payload.get("property_type"))
    neighborhood = _optional_text(item.provider_payload.get("neighborhood"))
    latitude = _coerce_float(item.provider_payload.get("latitude"))
    longitude = _coerce_float(item.provider_payload.get("longitude"))
    available_date = _optional_text(item.provider_payload.get("available_date"))
    listing_status = _normalize_listing_status(item.provider_payload.get("external_status"))
    title = _build_title(beds=item.beds, property_type=property_type, neighborhood=neighborhood)
    raw = dict(item.provider_payload)

    fingerprint_payload = {
        "source": source,
        "source_listing_id": source_listing_id,
        "source_url": item.url,
        "address_line": address_line,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "neighborhood": neighborhood,
        "rent_amount": item.rent,
        "rent_currency": "USD",
        "rent_period": "month",
        "beds": item.beds,
        "baths": item.baths,
        "sqft": item.sqft,
        "property_type": property_type,
        "available_date": available_date,
        "listing_status": listing_status,
    }
    fingerprint = sha1(json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")).hexdigest()

    return CanonicalListing(
        listing_id=f"{source}:{source_listing_id}",
        source=source,
        source_listing_id=source_listing_id,
        source_url=item.url,
        title=title,
        address_line=address_line,
        city=city,
        state=state,
        zip_code=validate_zip_code(zip_code),
        neighborhood=neighborhood,
        latitude=latitude,
        longitude=longitude,
        rent_amount=item.rent,
        rent_currency="USD",
        rent_period="month",
        beds=item.beds,
        baths=item.baths,
        sqft=item.sqft,
        property_type=property_type,
        available_date=available_date,
        listing_status=listing_status,
        first_seen_at=first_seen_at or seen_at,
        seen_at=seen_at,
        fingerprint=fingerprint,
        raw=raw,
    )


def normalize_snapshot(
    snapshot: DailyCrawlSnapshot,
    *,
    previous_listings_by_id: Mapping[str, CanonicalListing] | None = None,
) -> tuple[CanonicalListing, ...]:
    previous_listings_by_id = previous_listings_by_id or {}
    normalized: list[CanonicalListing] = []
    for item in snapshot.listings:
        listing_id = f"{snapshot.provider}:{item.external_id}"
        previous_listing = previous_listings_by_id.get(listing_id)
        normalized.append(
            normalize_listing(
                snapshot.provider,
                item,
                seen_at=snapshot.created_at,
                first_seen_at=previous_listing.first_seen_at if previous_listing is not None else None,
            )
        )
    return tuple(sorted(normalized, key=lambda item: item.listing_id))


def _parse_address(address: str, *, fallback_zip_code: str) -> tuple[str, str | None, str | None, str]:
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if not parts:
        return address.strip(), None, None, validate_zip_code(fallback_zip_code)
    if len(parts) >= 3:
        address_line = ", ".join(parts[:-2])
        city = parts[-2]
        state, zip_code = _parse_state_zip(parts[-1], fallback_zip_code=fallback_zip_code)
        return address_line, city or None, state, zip_code
    if len(parts) == 2:
        state, zip_code = _parse_state_zip(parts[-1], fallback_zip_code=fallback_zip_code)
        return parts[0], None, state, zip_code
    return parts[0], None, None, validate_zip_code(fallback_zip_code)


def _parse_state_zip(value: str, *, fallback_zip_code: str) -> tuple[str | None, str]:
    match = STATE_ZIP_PATTERN.match(value.strip().upper())
    if match is None:
        return None, validate_zip_code(fallback_zip_code)
    zip_code = match.group("zip_code") or fallback_zip_code
    return match.group("state"), validate_zip_code(zip_code)


def _build_title(*, beds: float | None, property_type: str | None, neighborhood: str | None) -> str | None:
    parts: list[str] = []
    if beds is not None:
        if beds.is_integer():
            parts.append(f"{int(beds)} bed")
        else:
            parts.append(f"{beds:g} bed")
    if property_type:
        parts.append(property_type)
    if not parts and not neighborhood:
        return None
    title = " ".join(parts) if parts else "rental listing"
    if neighborhood:
        return f"{title} in {neighborhood}"
    return title


def _normalize_listing_status(value: Any) -> str:
    text = _optional_text(value)
    if text is None:
        return "active"
    normalized = text.lower()
    if normalized in {"for_rent", "active", "available"}:
        return "active"
    if normalized in {"removed", "off_market", "inactive"}:
        return "removed"
    return normalized


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None
