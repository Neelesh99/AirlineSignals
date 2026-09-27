"""Delay Ingestion Service (2c): Unified interface for OpenSky Trino (2a) and Zenodo (2b)."""

from datetime import date, timedelta
import logging
from pathlib import Path
from typing import List, Optional, Union
import pandas as pd

from config.settings import get_settings
from database.db_manager import DatabaseManager
from ingest_delays.opensky_trino import OpenSkyTrinoClient
from ingest_delays.opensky_zenodo import OpenSkyZenodoParser

logger = logging.getLogger(__name__)


class DelayService:
    """Orchestrates delay monitoring ingestion across OpenSky Trino and Zenodo paths."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.settings = get_settings()
        self.db = db or DatabaseManager()
        self.trino_client = OpenSkyTrinoClient()
        self.zenodo_parser = OpenSkyZenodoParser()

    def run_ingestion(
        self,
        provider: Optional[str] = None,
        zenodo_file: Optional[Union[str, Path]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        generate_if_missing: bool = True
    ) -> pd.DataFrame:
        """Runs the delay ingestion module using either Trino (2a) or Zenodo (2b).
        
        Outputs standard schema:
        delay_stats(carrier, origin, dest, date, flight_no, scheduled_dep,
                    actual_dep, delay_min, scheduled_arr, actual_arr, delay_min_arr, data_source)
        """
        active_provider = provider or self.settings.opensky_config.get("active_provider", "zenodo").lower()
        logger.info("Running delay ingestion with provider: %s", active_provider)

        df = pd.DataFrame()

        if active_provider == "trino":
            # 2a Primary Path: Historical Trino/Impala Database
            s_date = start_date or (date(2024, 6, 1))
            e_date = end_date or (s_date + timedelta(days=14))
            
            dfs = []
            for route in self.settings.routes:
                orig, dest = route["origin"], route["dest"]
                for c in self.settings.carriers:
                    carrier = c["code"]
                    res = self.trino_client.fetch_delays(carrier, orig, dest, s_date, e_date, dry_run_or_mock=True)
                    if not res.empty:
                        dfs.append(res)
            if dfs:
                df = pd.concat(dfs, ignore_index=True)

        else:
            # 2b Fallback Path: Zenodo Crowdsourced CSV dumps
            target_file = zenodo_file or Path(self.settings.opensky_config.get("zenodo", {}).get("sample_file", "data/delays/zenodo_sample.csv"))
            target_path = Path(target_file)

            if not target_path.exists() and generate_if_missing:
                logger.info("Zenodo data file %s not found. Generating seed crowdsourced flight data.", target_path)
                self.zenodo_parser.generate_seed_zenodo_data(target_path, days=14)

            if target_path.exists():
                df = self.zenodo_parser.parse_csv(target_path)
            else:
                logger.warning("No Zenodo file available at %s", target_path)

        if not df.empty:
            # Clean and ensure schema compliance
            df["delay_min"] = df["delay_min"].fillna(0.0).round(1)
            df["delay_min_arr"] = df["delay_min_arr"].fillna(0.0).round(1)
            
            rows_inserted = self.db.insert_delay_stats(df)
            logger.info("Successfully ingested %d delay records into delay_stats (%s).", rows_inserted, active_provider)
            return df

        logger.warning("No delay records ingested.")
        return pd.DataFrame(columns=[
            "carrier", "origin", "dest", "date", "flight_no",
            "scheduled_dep", "actual_dep", "delay_min",
            "scheduled_arr", "actual_arr", "delay_min_arr", "data_source"
        ])
