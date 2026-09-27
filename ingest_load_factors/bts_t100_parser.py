"""BTS Form 41 / T-100 Segment Ingestion and Parser for US Carriers."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd
import requests

from ingest_load_factors.normalizer import Normalizer
from config.settings import get_settings

logger = logging.getLogger(__name__)


class BTST100Parser:
    """Parses DOT BTS T-100 Segment data (CSV or API)."""

    def __init__(self):
        self.normalizer = Normalizer()
        self.settings = get_settings()

    def parse_csv(self, file_path: Union[str, Path]) -> pd.DataFrame:
        """Parses a BTS T-100 Segment CSV file into structured DataFrame.
        
        Expected typical BTS columns:
        - UNIQUE_CARRIER or CARRIER: 2-character IATA or 3-character ICAO
        - ORIGIN: 3-letter IATA or 4-letter ICAO
        - DEST: 3-letter IATA or 4-letter ICAO
        - PASSENGERS: Revenue passengers transported
        - SEATS: Available seats
        - DISTANCE: Stage distance in miles
        - YEAR: 4-digit year
        - QUARTER: 1-4
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"T-100 file not found: {path}")

        logger.info("Reading BTS T-100 data from %s", path)
        df = pd.read_csv(path)
        return self._transform_t100_dataframe(df, source_label="BTS_T100")

    def _transform_t100_dataframe(self, df: pd.DataFrame, source_label: str = "BTS_T100") -> pd.DataFrame:
        """Standardizes raw BTS T-100 column names, computes ASM/RPM, and normalizes codes."""
        # Standardize column names to uppercase
        df.columns = [str(c).strip().upper() for c in df.columns]

        # Identify carrier column
        carrier_col = next((c for c in ["UNIQUE_CARRIER", "CARRIER", "CARRIER_CODE"] if c in df.columns), None)
        origin_col = next((c for c in ["ORIGIN", "ORIGIN_AIRPORT_ID"] if c in df.columns), None)
        dest_col = next((c for c in ["DEST", "DEST_AIRPORT_ID"] if c in df.columns), None)
        seats_col = next((c for c in ["SEATS", "AVAILABLE_SEATS"] if c in df.columns), None)
        pax_col = next((c for c in ["PASSENGERS", "REV_PAX"] if c in df.columns), None)
        dist_col = next((c for c in ["DISTANCE", "STAGE_DISTANCE"] if c in df.columns), None)
        year_col = next((c for c in ["YEAR"] if c in df.columns), None)
        quarter_col = next((c for c in ["QUARTER"] if c in df.columns), None)
        month_col = next((c for c in ["MONTH"] if c in df.columns), None)

        if not all([carrier_col, origin_col, dest_col]):
            raise ValueError(f"Missing essential T-100 columns in DataFrame: {df.columns.tolist()}")

        records: List[Dict] = []
        for _, row in df.iterrows():
            carrier = self.normalizer.normalize_carrier(str(row[carrier_col]))
            origin = self.normalizer.normalize_airport(str(row[origin_col]))
            dest = self.normalizer.normalize_airport(str(row[dest_col]))
            
            seats = float(row[seats_col]) if seats_col and pd.notna(row[seats_col]) else 0.0
            pax = float(row[pax_col]) if pax_col and pd.notna(row[pax_col]) else 0.0
            dist = float(row[dist_col]) if dist_col and pd.notna(row[dist_col]) else 0.0

            quarter_val = str(row[quarter_col]).strip() if quarter_col and pd.notna(row[quarter_col]) else ""
            if "Q" in quarter_val.upper() and len(quarter_val) >= 5:
                quarter = quarter_val.upper()
            else:
                try:
                    year = int(row[year_col]) if year_col and pd.notna(row[year_col]) else 2024
                except Exception:
                    year = 2024
                
                try:
                    q = int(quarter_val.replace("Q", "")) if quarter_val else None
                except Exception:
                    q = None

                try:
                    m = int(row[month_col]) if month_col and pd.notna(row[month_col]) else None
                except Exception:
                    m = None
                quarter = self.normalizer.format_quarter(year=year, quarter=q, month=m)

            # ASM = Available Seat Miles = Seats * Distance
            # RPM = Revenue Passenger Miles = Passengers * Distance
            asm = seats * dist if dist > 0 else seats * 1000.0
            rpm = pax * dist if dist > 0 else pax * 1000.0

            # Load factor calculation
            if asm > 0:
                load_factor = min(1.0, max(0.0, rpm / asm))
            elif seats > 0:
                load_factor = min(1.0, max(0.0, pax / seats))
            else:
                load_factor = 0.80  # Default baseline

            records.append({
                "carrier": carrier,
                "origin": origin,
                "dest": dest,
                "quarter": quarter,
                "asm": asm,
                "rpm": rpm,
                "load_factor": round(load_factor, 4),
                "source": source_label
            })

        result_df = pd.DataFrame(records)
        # Aggregate any duplicate carrier-origin-dest-quarter rows (e.g. from multiple months in quarter)
        if not result_df.empty:
            agg = result_df.groupby(["carrier", "origin", "dest", "quarter", "source"], as_index=False).agg({
                "asm": "sum",
                "rpm": "sum"
            })
            agg["load_factor"] = (agg["rpm"] / agg["asm"]).fillna(0.80).clip(0.0, 1.0).round(4)
            return agg[["carrier", "origin", "dest", "quarter", "asm", "rpm", "load_factor", "source"]]

        return pd.DataFrame(columns=["carrier", "origin", "dest", "quarter", "asm", "rpm", "load_factor", "source"])

    def fetch_from_bts_api(self, url: str, params: Optional[Dict] = None) -> pd.DataFrame:
        """Fetches T-100 data from a BTS or TranStats REST endpoint if configured."""
        logger.info("Fetching T-100 data from BTS API: %s", url)
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                raw_df = pd.DataFrame(data)
            elif isinstance(data, dict) and "data" in data:
                raw_df = pd.DataFrame(data["data"])
            else:
                raw_df = pd.DataFrame([data])
            return self._transform_t100_dataframe(raw_df, source_label="BTS_API")
        except Exception as e:
            logger.warning("BTS API call failed (%s). Falling back to local data/files.", e)
            return pd.DataFrame(columns=["carrier", "origin", "dest", "quarter", "asm", "rpm", "load_factor", "source"])

    def generate_seed_data(self, output_path: Optional[Path] = None) -> pd.DataFrame:
        """Generates realistic baseline BTS T-100 segment data for configured routes and US carriers."""
        import random
        random.seed(42)

        us_carriers = ["AA", "DL", "UA", "B6", "WN"]
        carrier_bases = {
            "AA": 0.835,
            "DL": 0.845,
            "UA": 0.825,
            "B6": 0.810,
            "WN": 0.795
        }
        quarters = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]
        
        rows = []
        for route in self.settings.routes:
            orig, dest = route["origin"], route["dest"]
            dist = route.get("distance_miles", 1000)
            
            # Non-US internal routes aren't covered by US domestic T-100
            if route.get("sector") == "Intra-Europe":
                continue

            for carrier in us_carriers:
                base_lf = carrier_bases.get(carrier, 0.82)
                for q in quarters:
                    # Seasonal fluctuation
                    seasonality = 0.03 if "Q3" in q else (-0.02 if "Q1" in q else 0.01)
                    noise = random.uniform(-0.025, 0.025)
                    lf = round(min(0.96, max(0.65, base_lf + seasonality + noise)), 4)
                    
                    # Typical quarterly flight frequency: 300 to 1200 flights
                    flights_per_qtr = random.randint(360, 900)
                    seats_per_flight = 160 if route.get("aircraft_type") == "Narrowbody" else 280
                    total_seats = flights_per_qtr * seats_per_flight
                    asm = float(total_seats * dist)
                    rpm = float(asm * lf)

                    rows.append({
                        "carrier": carrier,
                        "origin": orig,
                        "dest": dest,
                        "quarter": q,
                        "asm": asm,
                        "rpm": rpm,
                        "load_factor": lf,
                        "source": "BTS_T100"
                    })

        df = pd.DataFrame(rows)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False)
            logger.info("Saved seed BTS T-100 data to %s", output_path)

        return df
