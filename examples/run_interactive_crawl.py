from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.crawler import ChromiumBrowser, CrawlService, SearchRequest, SnapshotStore, ZillowChromiumProvider


DEFAULT_LOCATIONS = {
    "sunnyvale": "94086",
    "mountain-view": "94040",
    "santa-clara": "95050",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an interactive Zillow crawl and write snapshot files.")
    parser.add_argument("zip_codes", nargs="*", help="ZIP codes to crawl. Defaults to Sunnyvale, Mountain View, and Santa Clara examples.")
    parser.add_argument("--snapshot-dir", default="tmp/live-snapshots", help="Directory where snapshot JSON files will be written.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    browser = ChromiumBrowser(
        headless=False,
        user_data_dir=Path.home() / ".rental-monitor" / "chromium-profile",
        remote_debugging_port=9222,
        interactive_timeout_seconds=300,
        poll_interval_seconds=2.0,
    )
    provider = ZillowChromiumProvider(browser, interactive_timeout_seconds=300, poll_interval_seconds=2.0)
    snapshot_store = SnapshotStore(Path(args.snapshot_dir))
    crawl_service = CrawlService(provider, snapshot_store)

    locations = DEFAULT_LOCATIONS if not args.zip_codes else {zip_code: zip_code for zip_code in args.zip_codes}
    for label, zip_code in locations.items():
        result = crawl_service.crawl(SearchRequest(zip_code=zip_code), created_at=datetime.now(UTC))
        print(f"{label}\t{zip_code}\t{result.path}\t{result.snapshot.listing_count}")


if __name__ == "__main__":
    main()
