from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from .models import (
    DailyCrawlSnapshot,
    ProviderListing,
    SnapshotWriteResult,
    utc_date_string,
    utc_timestamp_string,
)


class SnapshotStoreError(RuntimeError):
    """Raised when a snapshot cannot be written or read safely."""


class SnapshotStore:
    """Persists and loads immutable crawler snapshot artifacts."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    def write_snapshot(
        self,
        *,
        provider: str,
        zip_code: str,
        query: dict[str, Any],
        listings: Iterable[ProviderListing],
        created_at: datetime | None = None,
    ) -> SnapshotWriteResult:
        if not provider:
            raise SnapshotStoreError("provider is required")

        created_at_value = (created_at or datetime.now(UTC)).astimezone(UTC)
        created_at_text = utc_timestamp_string(created_at_value)
        snapshot_date = utc_date_string(created_at_value)
        normalized_listings = tuple(sorted(listings, key=lambda item: item.external_id))
        snapshot = DailyCrawlSnapshot(
            snapshot_id=self._build_snapshot_id(provider=provider, zip_code=zip_code, created_at=created_at_text),
            snapshot_date=snapshot_date,
            created_at=created_at_text,
            provider=provider,
            zip_code=zip_code,
            query=query,
            listing_count=len(normalized_listings),
            listings=normalized_listings,
        )

        payload = snapshot.to_dict()
        serialized = json.dumps(payload, indent=2, sort_keys=True)
        content_hash = sha256(serialized.encode("utf-8")).hexdigest()
        path = self._build_snapshot_path(
            provider=provider,
            snapshot_date=snapshot.snapshot_date,
            zip_code=zip_code,
            created_at=snapshot.created_at,
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise SnapshotStoreError(f"snapshot already exists at {path}")

        path.write_text(serialized + "\n", encoding="utf-8")
        return SnapshotWriteResult(snapshot=snapshot, path=path, content_hash=content_hash)

    def load_snapshot(self, path: str | Path) -> DailyCrawlSnapshot:
        snapshot_path = Path(path)
        if not snapshot_path.exists():
            raise SnapshotStoreError(f"snapshot does not exist: {snapshot_path}")
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return DailyCrawlSnapshot.from_dict(data)

    def _build_snapshot_id(self, *, provider: str, zip_code: str, created_at: str) -> str:
        return f"{provider}-{zip_code}-{created_at}"

    def _build_snapshot_path(self, *, provider: str, snapshot_date: str, zip_code: str, created_at: str) -> Path:
        safe_timestamp = created_at.replace(":", "-")
        return (
            self.base_dir
            / f"provider={provider}"
            / f"date={snapshot_date}"
            / f"zip={zip_code}"
            / f"crawl-{safe_timestamp}.json"
        )
