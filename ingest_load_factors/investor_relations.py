"""Supplementary Load Factor Ingestion from Airline Investor Relations (10-Q / Quarterly Reports)."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd

from ingest_load_factors.normalizer import Normalizer
from config.settings import get_settings

logger = logging.getLogger(__name__)


class InvestorRelationsParser:
    """Parses international carrier quarterly reports and investor decks (10-Q / quarterly statistical disclosures)."""

    def __init__(self):
        self.normalizer = Normalizer()
        self.settings = get_settings()

    def parse_ir_csv(self, file_path: Union[str, Path]) -> pd.DataFrame:
        """Parses custom IR reports formatted as CSV.
        
        Expected columns:
        - CARRIER: e.g. BA, LH, AF, SQ
        - ORIGIN: e.g. LHR, CDG, FRA, SIN (or 'SYSTEM' for system-wide disclosures)
        - DEST: e.g. JFK, ORD, FRA, CDG (or 'SYSTEM')
        - QUARTER: e.g. 2024Q1
        - ASM: available seat miles
        - RPM: revenue passenger miles
        - LOAD_FACTOR: load factor decimal (0.0 to 1.0)
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"IR report file not found: {path}")

        df = pd.read_csv(path)
        df.columns = [str(c).strip().upper() for c in df.columns]

        records = []
        for _, row in df.iterrows():
            carrier = self.normalizer.normalize_carrier(str(row.get("CARRIER", "")))
            origin_raw = str(row.get("ORIGIN", "SYSTEM")).strip()
            dest_raw = str(row.get("DEST", "SYSTEM")).strip()

            origin = "SYSTEM" if origin_raw == "SYSTEM" else self.normalizer.normalize_airport(origin_raw)
            dest = "SYSTEM" if dest_raw == "SYSTEM" else self.normalizer.normalize_airport(dest_raw)

            quarter = str(row.get("QUARTER", "2024Q1")).strip()
            asm = float(row.get("ASM", 0.0))
            rpm = float(row.get("RPM", 0.0))
            lf = float(row.get("LOAD_FACTOR", 0.82))

            records.append({
                "carrier": carrier,
                "origin": origin,
                "dest": dest,
                "quarter": quarter,
                "asm": asm,
                "rpm": rpm,
                "load_factor": round(lf, 4),
                "source": "IR_REPORT"
            })

        return pd.DataFrame(records)

    def generate_seed_ir_data(self, output_path: Optional[Path] = None) -> pd.DataFrame:
        """Generates realistic quarterly IR statistics for non-US carriers and international routes."""
        international_carriers = {
            "BA": {"base_lf": 0.818, "routes": [("JFK", "LHR"), ("BOS", "LHR"), ("LHR", "CDG"), ("LHR", "FRA")]},
            "LH": {"base_lf": 0.809, "routes": [("LHR", "FRA"), ("ORD", "CDG")]},
            "AF": {"base_lf": 0.840, "routes": [("ORD", "CDG"), ("LHR", "CDG")]},
            "SQ": {"base_lf": 0.855, "routes": [("SFO", "SIN")]}
        }
        quarters = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]
        
        rows = []
        import random
        random.seed(99)

        for carrier, data in international_carriers.items():
            base_lf = data["base_lf"]
            # 1. System-wide IR disclosure
            for q in quarters:
                sys_lf = round(base_lf + random.uniform(-0.015, 0.015), 4)
                rows.append({
                    "carrier": carrier,
                    "origin": "SYSTEM",
                    "dest": "SYSTEM",
                    "quarter": q,
                    "asm": 5000000000.0,
                    "rpm": round(5000000000.0 * sys_lf, 0),
                    "load_factor": sys_lf,
                    "source": "IR_REPORT_SYSTEM"
                })

            # 2. Specific routes operated by carrier
            for orig, dest in data["routes"]:
                for q in quarters:
                    seasonal = 0.02 if "Q3" in q else (-0.01 if "Q1" in q else 0.005)
                    route_lf = round(min(0.95, max(0.68, base_lf + seasonal + random.uniform(-0.02, 0.02))), 4)
                    asm = 45000000.0
                    rpm = round(asm * route_lf, 0)
                    rows.append({
                        "carrier": carrier,
                        "origin": orig,
                        "dest": dest,
                        "quarter": q,
                        "asm": asm,
                        "rpm": rpm,
                        "load_factor": route_lf,
                        "source": "IR_REPORT_ROUTE"
                    })

        df = pd.DataFrame(rows)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False)
            logger.info("Saved seed IR load factor data to %s", output_path)

        return df
