"""Pricing Ingestion Service: orchestrates route price scraping and database persistence."""

from datetime import date, timedelta
import logging
from typing import Dict, List, Optional, Tuple
import pandas as pd

from config.settings import get_settings
from database.db_manager import DatabaseManager
from scrape_pricing.skyscanner_scraper import SkyscannerScraper

logger = logging.getLogger(__name__)


class PricingService:
    """Manages Skyscanner flight search scraping, retry cycles, and database insertion."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.settings = get_settings()
        self.db = db or DatabaseManager()
        self.scraper = SkyscannerScraper()

    def run_pricing_ingestion(
        self,
        routes: Optional[List[Tuple[str, str]]] = None,
        days_ahead: int = 14,
        window_days: int = 5,
        cabin_class: str = "economy",
        fallback_to_synthetic: bool = True,
        live_scrape: Optional[bool] = None
    ) -> pd.DataFrame:
        """Collects pricing across target routes and dates, inserting results into `pricing` table."""
        target_routes = routes or [(r["origin"], r["dest"]) for r in self.settings.routes]
        base_date = date.today() + timedelta(days=days_ahead)
        
        all_fares: List[Dict] = []

        for orig, dest in target_routes:
            for day_offset in range(window_days):
                travel_date = base_date + timedelta(days=day_offset)
                logger.info("Collecting fares for %s -> %s for travel date %s", orig, dest, travel_date)
                fares = self.scraper.scrape_route(
                    origin=orig,
                    dest=dest,
                    travel_date=travel_date,
                    cabin_class=cabin_class,
                    fallback_to_synthetic=fallback_to_synthetic,
                    live_scrape=live_scrape
                )
                all_fares.extend(fares)

        if all_fares:
            df = pd.DataFrame(all_fares)
            # Deduplicate by primary key
            df = df.drop_duplicates(subset=["carrier", "origin", "dest", "travel_date", "cabin_class", "stops"])
            rows_inserted = self.db.insert_pricing(df)
            logger.info("Successfully ingested %d pricing records into pricing table.", rows_inserted)
            return df

        logger.warning("No pricing records collected.")
        return pd.DataFrame(columns=[
            "carrier", "origin", "dest", "travel_date", "search_date", "price", "cabin_class", "stops"
        ])

    def retry_failed_lookups(self) -> int:
        """Retries lookups that failed in previous scraping attempts."""
        if not self.scraper.failed_lookups:
            logger.info("No failed lookups to retry.")
            return 0

        pending = list(self.scraper.failed_lookups)
        self.scraper.failed_lookups.clear()
        recovered: List[Dict] = []

        for item in pending:
            fares = self.scraper.scrape_route(
                origin=item["origin"],
                dest=item["dest"],
                travel_date=item["travel_date"],
                cabin_class=item["cabin_class"],
                fallback_to_synthetic=True
            )
            recovered.extend(fares)

        if recovered:
            df = pd.DataFrame(recovered).drop_duplicates(
                subset=["carrier", "origin", "dest", "travel_date", "cabin_class", "stops"]
            )
            inserted = self.db.insert_pricing(df)
            logger.info("Recovered %d pricing records from retry queue.", inserted)
            return inserted

        return 0
