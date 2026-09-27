"""Load Factor Ingestion Service: orchestrates T-100, IR data, and system-wide fallbacks."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd

from config.settings import get_settings
from database.db_manager import DatabaseManager
from ingest_load_factors.bts_t100_parser import BTST100Parser
from ingest_load_factors.investor_relations import InvestorRelationsParser

logger = logging.getLogger(__name__)


class LoadFactorService:
    """Orchestrates historical load factor ingestion with gap handling and system-wide fallbacks."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.settings = get_settings()
        self.db = db or DatabaseManager()
        self.bts_parser = BTST100Parser()
        self.ir_parser = InvestorRelationsParser()

    def run_ingestion(
        self,
        t100_file: Optional[Union[str, Path]] = None,
        ir_file: Optional[Union[str, Path]] = None,
        generate_if_missing: bool = True
    ) -> pd.DataFrame:
        """Runs the complete load factor ingestion pipeline and stores results in the database."""
        dfs: List[pd.DataFrame] = []

        # 1. BTS T-100 data
        if t100_file and Path(t100_file).exists():
            df_bts = self.bts_parser.parse_csv(t100_file)
            dfs.append(df_bts)
        elif generate_if_missing:
            seed_path = Path("data/load_factors/bts_t100_sample.csv")
            if not seed_path.exists():
                df_bts = self.bts_parser.generate_seed_data(seed_path)
            else:
                df_bts = self.bts_parser.parse_csv(seed_path)
            dfs.append(df_bts)

        # 2. Investor Relations data
        if ir_file and Path(ir_file).exists():
            df_ir = self.ir_parser.parse_ir_csv(ir_file)
            dfs.append(df_ir)
        elif generate_if_missing:
            seed_ir_path = Path("data/load_factors/ir_sample.csv")
            if not seed_ir_path.exists():
                df_ir = self.ir_parser.generate_seed_ir_data(seed_ir_path)
            else:
                df_ir = self.ir_parser.parse_ir_csv(seed_ir_path)
            dfs.append(df_ir)

        combined_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

        # 3. Handle Gaps with System-Wide Fallbacks
        final_df = self.apply_system_wide_fallbacks(combined_df)

        # 4. Insert into Database
        rows_inserted = self.db.insert_load_factors(final_df)
        logger.info("Successfully ingested %d load factor records into database.", rows_inserted)
        return final_df

    def apply_system_wide_fallbacks(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fills gaps for configured routes/carriers with carrier system-wide average or default load factor."""
        carrier_defaults: Dict[str, float] = {
            c["code"]: c.get("default_load_factor", 0.80) for c in self.settings.carriers
        }

        # Calculate empirical system-wide averages from data
        system_wide_emp: Dict[str, float] = {}
        if not df.empty:
            sys_df = df[df["origin"] == "SYSTEM"]
            for _, r in sys_df.iterrows():
                system_wide_emp[r["carrier"]] = r["load_factor"]
            
            # For carriers without explicit SYSTEM rows, calculate mean across their reported routes
            for carrier, group in df[df["origin"] != "SYSTEM"].groupby("carrier"):
                if carrier not in system_wide_emp and not group.empty:
                    system_wide_emp[carrier] = round(group["load_factor"].mean(), 4)

        quarters = sorted(df["quarter"].unique().tolist()) if not df.empty else ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]
        existing_keys = set()
        if not df.empty:
            for _, r in df.iterrows():
                existing_keys.add((r["carrier"], r["origin"], r["dest"], r["quarter"]))

        fallback_rows = []
        for route in self.settings.routes:
            orig, dest = route["origin"], route["dest"]
            dist = route.get("distance_miles", 1000)

            for carrier_info in self.settings.carriers:
                carrier = carrier_info["code"]
                for q in quarters:
                    if (carrier, orig, dest, q) not in existing_keys:
                        # Fallback needed
                        fallback_lf = system_wide_emp.get(carrier, carrier_defaults.get(carrier, 0.80))
                        source_label = "BTS_SYSTEM_FALLBACK" if carrier in ["AA", "DL", "UA", "B6", "WN"] else "IR_SYSTEM_FALLBACK"
                        
                        fallback_rows.append({
                            "carrier": carrier,
                            "origin": orig,
                            "dest": dest,
                            "quarter": q,
                            "asm": 50000.0 * dist,
                            "rpm": 50000.0 * dist * fallback_lf,
                            "load_factor": round(fallback_lf, 4),
                            "source": source_label
                        })

        if fallback_rows:
            logger.info("Generated %d system-wide fallback load factor records for missing routes.", len(fallback_rows))
            all_df = pd.concat([df, pd.DataFrame(fallback_rows)], ignore_index=True)
        else:
            all_df = df

        # Filter out purely generic 'SYSTEM' origin/dest rows from final route table if needed,
        # but retain them for reference if desired. We keep only valid airport pairs for route economics:
        valid_routes_df = all_df[all_df["origin"] != "SYSTEM"].copy()
        return valid_routes_df.drop_duplicates(subset=["carrier", "origin", "dest", "quarter"])
