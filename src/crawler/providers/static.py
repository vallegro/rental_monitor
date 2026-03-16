from __future__ import annotations

from typing import Iterable

from ..models import ProviderListing, SearchRequest


class StaticListingProvider:
    """Simple in-memory provider useful for testing and local development."""

    def __init__(self, listings: Iterable[ProviderListing], *, name: str = "static") -> None:
        self._listings = tuple(listings)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def search(self, request: SearchRequest) -> list[ProviderListing]:
        matches: list[ProviderListing] = []
        for listing in self._listings:
            if listing.zip_code != request.zip_code:
                continue
            if request.min_rent is not None and listing.rent is not None and listing.rent < request.min_rent:
                continue
            if request.max_rent is not None and listing.rent is not None and listing.rent > request.max_rent:
                continue
            if request.beds is not None and listing.beds is not None and listing.beds < request.beds:
                continue
            if request.baths is not None and listing.baths is not None and listing.baths < request.baths:
                continue
            if request.property_types:
                allowed_property_types = {item.lower() for item in request.property_types}
                property_type = str(listing.provider_payload.get("property_type", "")).lower()
                if not property_type or property_type not in allowed_property_types:
                    continue
            matches.append(listing)
        return matches
