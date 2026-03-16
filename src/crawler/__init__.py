"""Crawler package for fetching listings and writing snapshot handoff artifacts."""

from .models import DailyCrawlSnapshot, ProviderListing, SearchRequest, SnapshotWriteResult
from .provider_contracts import ListingProvider, ListingProviderError
from .providers import StaticListingProvider
from .service import CrawlService
from .snapshot_store import SnapshotStore, SnapshotStoreError

__all__ = [
    "CrawlService",
    "DailyCrawlSnapshot",
    "ListingProvider",
    "ListingProviderError",
    "ProviderListing",
    "SearchRequest",
    "SnapshotStore",
    "SnapshotStoreError",
    "SnapshotWriteResult",
    "StaticListingProvider",
]
