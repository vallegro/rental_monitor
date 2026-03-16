"""Crawler package for fetching listings and writing snapshot handoff artifacts."""

from .browser import ChromiumBrowser, ChromiumBrowserError
from .models import DailyCrawlSnapshot, ProviderListing, SearchRequest, SnapshotWriteResult
from .provider_contracts import ListingProvider, ListingProviderError
from .providers import ZillowChromiumProvider
from .service import CrawlService
from .snapshot_store import SnapshotStore, SnapshotStoreError

__all__ = [
    "CrawlService",
    "ChromiumBrowser",
    "ChromiumBrowserError",
    "DailyCrawlSnapshot",
    "ListingProvider",
    "ListingProviderError",
    "ProviderListing",
    "SearchRequest",
    "SnapshotStore",
    "SnapshotStoreError",
    "SnapshotWriteResult",
    "ZillowChromiumProvider",
]
