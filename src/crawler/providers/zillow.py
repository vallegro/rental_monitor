from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from typing import Any, Iterable
from urllib.parse import quote, urljoin

from ..browser import ChromiumBrowser
from ..models import ProviderListing, SearchRequest
from ..provider_contracts import ListingProviderError


PRICE_PATTERN = re.compile(r"(\d[\d,]*)")
ZIP_CODE_PATTERN = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
SCRIPT_ASSIGNMENT_PATTERN = re.compile(
    r"(?:window\.__[A-Z0-9_]+__|__NEXT_DATA__|searchPageStore)\s*=\s*(\{.*\}|\[.*\]);?",
    re.DOTALL,
)
JSON_PARSE_PATTERN = re.compile(r"JSON\.parse\((\".*?\")\)", re.DOTALL)


class ZillowChromiumProvider:
    """Fetches Zillow rental results using headless Chromium."""

    def __init__(
        self,
        browser: ChromiumBrowser,
        *,
        base_url: str = "https://www.zillow.com",
        interactive_timeout_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.browser = browser
        self.base_url = base_url.rstrip("/")
        self.interactive_timeout_seconds = interactive_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    @property
    def name(self) -> str:
        return "zillow"

    def search(self, request: SearchRequest) -> list[ProviderListing]:
        url = self.build_search_url(request)
        html = self.browser.dump_dom(
            url,
            wait_until=self._is_ready_search_page,
            timeout_seconds=self.interactive_timeout_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
        )
        if self._looks_blocked(html):
            raise ListingProviderError(
                "Zillow returned a blocked or anti-bot page. If using an interactive browser session, "
                "complete the challenge in the opened browser window and retry."
            )

        listings = self.extract_listings(html, request.zip_code)
        return [listing for listing in listings if self._matches_request(listing, request)]

    def build_search_url(self, request: SearchRequest) -> str:
        return f"{self.base_url}/homes/for_rent/{quote(request.zip_code)}_rb/"

    def extract_listings(self, html: str, zip_code: str) -> list[ProviderListing]:
        listing_by_id: dict[str, ProviderListing] = {}
        parser = _ScriptTagCollector()
        parser.feed(html)

        for script in parser.scripts:
            for payload in _extract_json_payloads(script):
                for raw_listing in _walk_listing_candidates(payload):
                    listing = self._convert_candidate_to_listing(raw_listing, zip_code)
                    if listing is None:
                        continue
                    listing_by_id.setdefault(listing.external_id, listing)

        if listing_by_id:
            return sorted(listing_by_id.values(), key=lambda listing: listing.external_id)

        return self._extract_fallback_anchor_listings(html, zip_code)

    def _convert_candidate_to_listing(
        self,
        candidate: dict[str, Any],
        request_zip_code: str,
    ) -> ProviderListing | None:
        raw_external_id = _coalesce(
            candidate.get("zpid"),
            candidate.get("id"),
            _nested_get(candidate, "hdpData", "homeInfo", "zpid"),
        )
        url = _coalesce(candidate.get("detailUrl"), candidate.get("hdpUrl"), candidate.get("url"))
        external_id = self._normalize_external_id(raw_external_id, url)
        address = self._extract_address(candidate)
        zip_code = _coalesce(
            candidate.get("zipcode"),
            candidate.get("addressZipcode"),
            _nested_get(candidate, "address", "zipcode"),
            _extract_zip_code(address),
            request_zip_code,
        )

        if not external_id or not url or not address or not zip_code:
            return None

        rent = self._extract_price(candidate)
        beds = _coerce_float(_coalesce(candidate.get("beds"), candidate.get("bedrooms")))
        baths = _coerce_float(_coalesce(candidate.get("baths"), candidate.get("bathrooms")))
        sqft = _coerce_int(_coalesce(candidate.get("area"), candidate.get("livingArea"), candidate.get("sqft")))
        listed_at = _coalesce(candidate.get("listingDateTime"), candidate.get("listedDateTime"))

        provider_payload = dict(candidate)
        property_type = self._extract_property_type(candidate)
        if property_type and "property_type" not in provider_payload:
            provider_payload["property_type"] = property_type

        normalized_url = url if url.startswith("http") else urljoin(f"{self.base_url}/", url.lstrip("/"))
        return ProviderListing(
            external_id=external_id,
            url=normalized_url,
            address=address,
            zip_code=str(zip_code),
            rent=rent,
            beds=beds,
            baths=baths,
            sqft=sqft,
            listed_at=listed_at,
            provider_payload=provider_payload,
        )

    def _normalize_external_id(self, raw_external_id: Any, url: Any) -> str | None:
        if isinstance(raw_external_id, (int, float)):
            return str(int(raw_external_id))
        if isinstance(raw_external_id, str):
            stripped = raw_external_id.strip()
            if stripped.isdigit():
                return stripped
        if isinstance(url, str):
            match = re.search(r"/(\d+)_zpid/?", url)
            if match:
                return match.group(1)
        return None

    def _extract_address(self, candidate: dict[str, Any]) -> str | None:
        direct_address = candidate.get("address")
        if isinstance(direct_address, str) and direct_address.strip():
            return direct_address.strip()

        home_info = _nested_get(candidate, "hdpData", "homeInfo")
        if isinstance(home_info, dict):
            pieces = [
                home_info.get("streetAddress"),
                home_info.get("city"),
                home_info.get("state"),
                home_info.get("zipcode"),
            ]
            joined = ", ".join(str(piece).strip() for piece in pieces if piece)
            if joined:
                return joined

        address_parts = [
            candidate.get("streetAddress"),
            candidate.get("city"),
            candidate.get("state"),
            candidate.get("zipcode"),
        ]
        joined = ", ".join(str(piece).strip() for piece in address_parts if piece)
        return joined or None

    def _extract_price(self, candidate: dict[str, Any]) -> int | None:
        for value in (
            candidate.get("unformattedPrice"),
            candidate.get("price"),
            candidate.get("priceForHDP"),
            _nested_get(candidate, "units"),
        ):
            price = _coerce_price(value)
            if price is not None:
                return price
        return None

    def _extract_property_type(self, candidate: dict[str, Any]) -> str | None:
        for value in (
            candidate.get("propertyType"),
            candidate.get("propertyTypeDimension"),
            candidate.get("homeType"),
            _nested_get(candidate, "hdpData", "homeInfo", "homeType"),
        ):
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return None

    def _extract_fallback_anchor_listings(self, html: str, zip_code: str) -> list[ProviderListing]:
        anchors = re.findall(r'href="([^"]+/homedetails/[^"]+)"', html)
        deduped_urls = []
        seen_urls: set[str] = set()
        for url in anchors:
            absolute = url if url.startswith("http") else urljoin(f"{self.base_url}/", url.lstrip("/"))
            if absolute not in seen_urls:
                seen_urls.add(absolute)
                deduped_urls.append(absolute)

        listings: list[ProviderListing] = []
        for url in deduped_urls:
            zpid_match = re.search(r"/(\d+)_zpid/?", url)
            if not zpid_match:
                continue
            external_id = zpid_match.group(1)
            address = url.rstrip("/").split("/")[-2].replace("-", " ")
            listings.append(
                ProviderListing(
                    external_id=external_id,
                    url=url,
                    address=address,
                    zip_code=zip_code,
                    rent=None,
                    beds=None,
                    baths=None,
                    sqft=None,
                    listed_at=None,
                    provider_payload={"fallback_extraction": True},
                )
            )
        return listings

    def _matches_request(self, listing: ProviderListing, request: SearchRequest) -> bool:
        if listing.zip_code != request.zip_code:
            return False
        if request.min_rent is not None and listing.rent is not None and listing.rent < request.min_rent:
            return False
        if request.max_rent is not None and listing.rent is not None and listing.rent > request.max_rent:
            return False
        if request.beds is not None and listing.beds is not None and listing.beds < request.beds:
            return False
        if request.baths is not None and listing.baths is not None and listing.baths < request.baths:
            return False
        if request.property_types:
            property_type = str(listing.provider_payload.get("property_type", "")).lower().strip()
            if property_type and property_type not in {item.lower() for item in request.property_types}:
                return False
        return True

    def _looks_blocked(self, html: str) -> bool:
        lowered = html.lower()
        return any(marker in lowered for marker in ("captcha", "press & hold", "access denied"))

    def _is_ready_search_page(self, html: str) -> bool:
        if self._looks_blocked(html):
            return False
        lowered = html.lower()
        return "<html" in lowered and "</html>" in lowered


class _ScriptTagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._inside_script = False
        self._current_chunks: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._inside_script = True
            self._current_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside_script:
            content = "".join(self._current_chunks).strip()
            if content:
                self.scripts.append(content)
            self._inside_script = False
            self._current_chunks = []

    def handle_data(self, data: str) -> None:
        if self._inside_script:
            self._current_chunks.append(data)


def _extract_json_payloads(script_text: str) -> Iterable[Any]:
    stripped = script_text.strip()
    if not stripped:
        return []

    payloads: list[Any] = []
    direct_payload = _try_json_loads(stripped)
    if direct_payload is not None:
        payloads.append(direct_payload)

    for match in SCRIPT_ASSIGNMENT_PATTERN.finditer(script_text):
        payload = _try_json_loads(match.group(1))
        if payload is not None:
            payloads.append(payload)

    for match in JSON_PARSE_PATTERN.finditer(script_text):
        try:
            encoded_string = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        payload = _try_json_loads(encoded_string)
        if payload is not None:
            payloads.append(payload)

    return payloads


def _walk_listing_candidates(payload: Any) -> Iterable[dict[str, Any]]:
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if _looks_like_listing(current):
                yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _looks_like_listing(candidate: dict[str, Any]) -> bool:
    keys = set(candidate.keys())
    has_id = "zpid" in keys or "id" in keys or _nested_get(candidate, "hdpData", "homeInfo", "zpid") is not None
    has_address = "address" in keys or "streetAddress" in keys or _nested_get(candidate, "hdpData", "homeInfo") is not None
    has_url = any(key in keys for key in ("detailUrl", "hdpUrl", "url"))
    has_housing_signal = any(key in keys for key in ("beds", "baths", "price", "priceForHDP", "unformattedPrice"))
    return has_id and has_address and (has_url or has_housing_signal)


def _try_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _nested_get(mapping: dict[str, Any], *path: str) -> Any | None:
    current: Any = mapping
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _coalesce(*values: Any) -> Any | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _coerce_price(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, list):
        prices = [_coerce_price(item) for item in value]
        valid_prices = [price for price in prices if price is not None]
        return min(valid_prices) if valid_prices else None
    if isinstance(value, str):
        match = PRICE_PATTERN.search(value.replace("$", ""))
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().lower().replace("+", "")
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = PRICE_PATTERN.search(value)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _extract_zip_code(address: str | None) -> str | None:
    if not address:
        return None
    match = ZIP_CODE_PATTERN.search(address)
    return match.group(1) if match else None
