"""Top-level Pipeline Orchestrator for Airline Route Economics Analyzer."""

import argparse
import logging
from pathlib import Path
import sys
from typing import Optional

from config.settings import get_settings
from database.db_manager import DatabaseManager
from ingest_load_factors.load_factor_service import LoadFactorService
from ingest_delays.delay_service import DelayService
from estimate_delay_cost.delay_cost_service import DelayCostService
from scrape_pricing.pricing_service import PricingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("PipelineOrchestrator")


class RouteEconomicsPipeline:
    """Orchestrates end-to-end ingestion, cost estimation, and database synchronization."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.settings = get_settings()
        self.db = db or DatabaseManager()
        self.lf_service = LoadFactorService(self.db)
        self.delay_service = DelayService(self.db)
        self.cost_service = DelayCostService(self.db)
        self.pricing_service = PricingService(self.db)

    def run_stage_load_factors(
        self,
        t100_file: Optional[str] = None,
        ir_file: Optional[str] = None
    ) -> int:
        """Stage 1: Ingests historical BTS T-100 and Investor Relations quarterly load factors."""
        logger.info("=== STAGE 1: INGESTING HISTORICAL LOAD FACTORS ===")
        df = self.lf_service.run_ingestion(t100_file=t100_file, ir_file=ir_file, generate_if_missing=True)
        logger.info("Stage 1 completed: %d load factor records in database.", len(df))
        return len(df)

    def run_stage_delays(
        self,
        provider: Optional[str] = None,
        zenodo_file: Optional[str] = None
    ) -> int:
        """Stage 2: Ingests OpenSky Network delay monitoring records (Trino or Zenodo)."""
        logger.info("=== STAGE 2: INGESTING DELAYS (OPENSKY) ===")
        df = self.delay_service.run_ingestion(provider=provider, zenodo_file=zenodo_file, generate_if_missing=True)
        logger.info("Stage 2 completed: %d delay records in database.", len(df))
        return len(df)

    def run_stage_delay_costs(
        self,
        direct_cost_override: Optional[float] = None,
        pvot_override: Optional[float] = None
    ) -> int:
        """Stage 3: Applies A4A / DOT delay cost models across ingested flights."""
        logger.info("=== STAGE 3: ESTIMATING DELAY EXPENSES ===")
        if direct_cost_override or pvot_override:
            self.cost_service.update_cost_assumptions(
                direct_operating_cost_per_min=direct_cost_override,
                pvot_per_min=pvot_override
            )
        df = self.cost_service.run_estimation()
        logger.info("Stage 3 completed: %d delay cost records calculated.", len(df))
        return len(df)

    def run_stage_pricing(
        self,
        days_ahead: int = 14,
        window_days: int = 4,
        cabin_class: str = "economy",
        live_scrape: bool = False
    ) -> int:
        """Stage 4: Collects Skyscanner route pricing via Playwright scraper."""
        logger.info("=== STAGE 4: COLLECTING PRICING (SKYSCANNER) ===")
        df = self.pricing_service.run_pricing_ingestion(
            days_ahead=days_ahead,
            window_days=window_days,
            cabin_class=cabin_class,
            fallback_to_synthetic=True,
            live_scrape=live_scrape
        )
        logger.info("Stage 4 completed: %d pricing records in database.", len(df))
        return len(df)

    def run_full_pipeline(
        self,
        delay_provider: Optional[str] = None,
        t100_file: Optional[str] = None,
        zenodo_file: Optional[str] = None,
        live_scrape: bool = False
    ) -> None:
        """Executes all pipeline stages sequentially."""
        logger.info("Starting Full Airline Route Economics Pipeline Execution...")
        self.run_stage_load_factors(t100_file=t100_file)
        self.run_stage_delays(provider=delay_provider, zenodo_file=zenodo_file)
        self.run_stage_delay_costs()
        self.run_stage_pricing(live_scrape=live_scrape)
        logger.info("Full pipeline execution completed successfully! Database is ready for queries.")


def main():
    parser = argparse.ArgumentParser(description="Airline Route Economics Pipeline Orchestrator")
    parser.add_argument("--stage", choices=["all", "load_factors", "delays", "delay_costs", "pricing"], default="all",
                        help="Pipeline stage to execute")
    parser.add_argument("--delay-provider", choices=["zenodo", "trino"], default=None,
                        help="Delay data provider (zenodo or trino)")
    parser.add_argument("--t100-file", help="Path to BTS T-100 CSV file")
    parser.add_argument("--zenodo-file", help="Path to OpenSky Zenodo CSV dump")

    args = parser.parse_args()
    pipeline = RouteEconomicsPipeline()

    if args.stage == "all":
        pipeline.run_full_pipeline(delay_provider=args.delay_provider, t100_file=args.t100_file, zenodo_file=args.zenodo_file)
    elif args.stage == "load_factors":
        pipeline.run_stage_load_factors(t100_file=args.t100_file)
    elif args.stage == "delays":
        pipeline.run_stage_delays(provider=args.delay_provider, zenodo_file=args.zenodo_file)
    elif args.stage == "delay_costs":
        pipeline.run_stage_delay_costs()
    elif args.stage == "pricing":
        pipeline.run_stage_pricing()


if __name__ == "__main__":
    main()
