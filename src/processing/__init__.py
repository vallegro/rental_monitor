"""Processing package for turning crawler snapshots into daily digests."""

from .diff_engine import diff_listings
from .models import CanonicalListing, DailyDigest, DiffResult, EmailSummary, ListingChange
from .normalizer import normalize_listing, normalize_snapshot
from .service import build_daily_digest
from .summary import build_summary

__all__ = [
    "CanonicalListing",
    "DailyDigest",
    "DiffResult",
    "EmailSummary",
    "ListingChange",
    "build_daily_digest",
    "build_summary",
    "diff_listings",
    "normalize_listing",
    "normalize_snapshot",
]
