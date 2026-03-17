from __future__ import annotations

from .models import CanonicalListing, DiffResult, ListingChange


TRACKED_FIELDS = (
    "source_url",
    "title",
    "address_line",
    "city",
    "state",
    "zip_code",
    "neighborhood",
    "latitude",
    "longitude",
    "rent_amount",
    "rent_currency",
    "rent_period",
    "beds",
    "baths",
    "sqft",
    "property_type",
    "available_date",
    "listing_status",
)

PRICE_FIELDS = {"rent_amount", "rent_currency", "rent_period"}


def diff_listings(
    previous: tuple[CanonicalListing, ...] | list[CanonicalListing],
    current: tuple[CanonicalListing, ...] | list[CanonicalListing],
) -> DiffResult:
    previous_by_id = {listing.listing_id: listing for listing in previous}
    current_by_id = {listing.listing_id: listing for listing in current}

    new: list[ListingChange] = []
    changed: list[ListingChange] = []
    removed: list[ListingChange] = []
    unchanged: list[CanonicalListing] = []

    for listing_id in sorted(current_by_id):
        current_listing = current_by_id[listing_id]
        previous_listing = previous_by_id.get(listing_id)
        if previous_listing is None:
            new.append(
                ListingChange(
                    listing_id=listing_id,
                    change_type="new",
                    previous=None,
                    current=current_listing,
                )
            )
            continue

        changed_fields = tuple(
            field_name
            for field_name in TRACKED_FIELDS
            if getattr(previous_listing, field_name) != getattr(current_listing, field_name)
        )
        if not changed_fields:
            unchanged.append(current_listing)
            continue

        change_type = "price_changed" if set(changed_fields).issubset(PRICE_FIELDS) else "details_changed"
        changed.append(
            ListingChange(
                listing_id=listing_id,
                change_type=change_type,
                previous=previous_listing,
                current=current_listing,
                changed_fields=changed_fields,
            )
        )

    for listing_id in sorted(previous_by_id):
        if listing_id in current_by_id:
            continue
        removed.append(
            ListingChange(
                listing_id=listing_id,
                change_type="removed",
                previous=previous_by_id[listing_id],
                current=None,
            )
        )

    return DiffResult(
        new=tuple(new),
        changed=tuple(changed),
        removed=tuple(removed),
        unchanged=tuple(sorted(unchanged, key=lambda item: item.listing_id)),
    )
