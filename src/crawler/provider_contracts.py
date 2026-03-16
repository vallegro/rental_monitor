from __future__ import annotations

from typing import Protocol, Sequence

from .models import ProviderListing, SearchRequest


class ListingProviderError(RuntimeError):
    """Raised when a provider cannot return listings for a search request."""


class ListingProvider(Protocol):
    """Contract implemented by every crawler provider adapter."""

    @property
    def name(self) -> str:
        ...

    def search(self, request: SearchRequest) -> Sequence[ProviderListing]:
        ...
