from __future__ import annotations

from .models import CanonicalListing, DiffResult, EmailSummary, ListingChange


def build_summary(
    diff: DiffResult,
    *,
    zip_code: str,
    snapshot_date: str | None = None,
) -> EmailSummary:
    price_changes = tuple(change for change in diff.changed if change.change_type == "price_changed")
    detail_changes = tuple(change for change in diff.changed if change.change_type != "price_changed")

    update_count = diff.update_count
    subject = f"Rental monitor: {update_count} update{'s' if update_count != 1 else ''} in {zip_code}"

    lines = [f"ZIP code: {zip_code}"]
    if snapshot_date is not None:
        lines.append(f"Snapshot date: {snapshot_date}")
    lines.extend(
        [
            "",
            f"Updates: {update_count}",
            f"New listings: {len(diff.new)}",
            f"Price changes: {len(price_changes)}",
            f"Detail changes: {len(detail_changes)}",
            f"Removed listings: {len(diff.removed)}",
        ]
    )

    if update_count == 0:
        lines.extend(["", "No listing changes detected."])
    else:
        if diff.new:
            lines.extend(["", "New listings:"])
            lines.extend(f"- {_format_listing_line(change.current)}" for change in diff.new if change.current is not None)
        if price_changes:
            lines.extend(["", "Price changes:"])
            lines.extend(f"- {_format_price_change(change)}" for change in price_changes)
        if detail_changes:
            lines.extend(["", "Detail changes:"])
            lines.extend(f"- {_format_detail_change(change)}" for change in detail_changes)
        if diff.removed:
            lines.extend(["", "Removed listings:"])
            lines.extend(
                f"- {_format_removed_listing(change.previous)}" for change in diff.removed if change.previous is not None
            )

    listing_ids = _collect_listing_ids(diff)
    return EmailSummary(
        subject=subject,
        text_body="\n".join(lines),
        html_body=None,
        listing_ids=listing_ids,
    )


def _collect_listing_ids(diff: DiffResult) -> tuple[str, ...]:
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for collection in (diff.new, diff.changed, diff.removed):
        for change in collection:
            if change.listing_id in seen:
                continue
            seen.add(change.listing_id)
            ordered_ids.append(change.listing_id)
    return tuple(ordered_ids)


def _format_listing_line(listing: CanonicalListing | None) -> str:
    if listing is None:
        return "unknown listing"
    details = [listing.address_line]
    rent_text = _format_rent(listing.rent_amount, listing.rent_period)
    if rent_text is not None:
        details.append(rent_text)
    layout_text = _format_layout(listing.beds, listing.baths)
    if layout_text is not None:
        details.append(layout_text)
    return " — ".join(details)


def _format_price_change(change: ListingChange) -> str:
    current = change.current
    previous = change.previous
    if current is None or previous is None:
        return change.listing_id
    previous_rent = _format_rent(previous.rent_amount, previous.rent_period) or "unknown rent"
    current_rent = _format_rent(current.rent_amount, current.rent_period) or "unknown rent"
    return f"{current.address_line} — {previous_rent} -> {current_rent}"


def _format_detail_change(change: ListingChange) -> str:
    current = change.current
    if current is None:
        return change.listing_id
    fields = ", ".join(change.changed_fields) if change.changed_fields else "details"
    return f"{current.address_line} — changed: {fields}"


def _format_removed_listing(listing: CanonicalListing | None) -> str:
    if listing is None:
        return "unknown listing"
    rent_text = _format_rent(listing.rent_amount, listing.rent_period)
    if rent_text is None:
        return listing.address_line
    return f"{listing.address_line} — last seen at {rent_text}"


def _format_rent(rent_amount: int | None, rent_period: str) -> str | None:
    if rent_amount is None:
        return None
    period_suffix = "/mo" if rent_period == "month" else f"/{rent_period}"
    return f"${rent_amount:,}{period_suffix}"


def _format_layout(beds: float | None, baths: float | None) -> str | None:
    parts: list[str] = []
    if beds is not None:
        parts.append(f"{beds:g} bd")
    if baths is not None:
        parts.append(f"{baths:g} ba")
    if not parts:
        return None
    return " / ".join(parts)
