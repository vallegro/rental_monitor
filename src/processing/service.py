from __future__ import annotations

from ..crawler.models import DailyCrawlSnapshot
from .diff_engine import diff_listings
from .models import DailyDigest
from .normalizer import normalize_snapshot
from .summary import build_summary


def build_daily_digest(
    *,
    current_snapshot: DailyCrawlSnapshot,
    previous_snapshot: DailyCrawlSnapshot | None = None,
) -> DailyDigest:
    if previous_snapshot is not None:
        if previous_snapshot.provider != current_snapshot.provider:
            raise ValueError("previous_snapshot provider must match current_snapshot provider")
        if previous_snapshot.zip_code != current_snapshot.zip_code:
            raise ValueError("previous_snapshot zip_code must match current_snapshot zip_code")

    previous_listings = normalize_snapshot(previous_snapshot) if previous_snapshot is not None else ()
    previous_listings_by_id = {listing.listing_id: listing for listing in previous_listings}
    current_listings = normalize_snapshot(
        current_snapshot,
        previous_listings_by_id=previous_listings_by_id,
    )
    diff = diff_listings(previous_listings, current_listings)
    summary = build_summary(diff, zip_code=current_snapshot.zip_code, snapshot_date=current_snapshot.snapshot_date)
    return DailyDigest(
        current_snapshot_id=current_snapshot.snapshot_id,
        previous_snapshot_id=previous_snapshot.snapshot_id if previous_snapshot is not None else None,
        snapshot_date=current_snapshot.snapshot_date,
        zip_code=current_snapshot.zip_code,
        current_listings=current_listings,
        previous_listings=previous_listings,
        diff=diff,
        summary=summary,
    )
