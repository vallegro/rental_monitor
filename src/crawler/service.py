from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .models import SearchRequest, SnapshotWriteResult
from .provider_contracts import ListingProvider
from .snapshot_store import SnapshotStore


class CrawlService:
    """Coordinates provider fetches and snapshot persistence."""

    def __init__(self, provider: ListingProvider, snapshot_store: SnapshotStore) -> None:
        self.provider = provider
        self.snapshot_store = snapshot_store

    def crawl(self, request: SearchRequest, *, created_at: datetime | None = None) -> SnapshotWriteResult:
        listings = tuple(self.provider.search(request))
        return self.snapshot_store.write_snapshot(
            provider=self.provider.name,
            zip_code=request.zip_code,
            query=request.to_dict(),
            listings=listings,
            created_at=created_at,
        )

    def crawl_many(
        self,
        requests: Iterable[SearchRequest],
        *,
        created_at: datetime | None = None,
    ) -> list[SnapshotWriteResult]:
        return [self.crawl(request, created_at=created_at) for request in requests]
