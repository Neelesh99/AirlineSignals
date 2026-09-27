"""OpenSky Network 2b Fallback Path: Public Zenodo Monthly Crowdsourced CSV Ingestion.

DATASET CAVEATS & LIMITATIONS (Zenodo Crowdsourced Air Traffic Data, CC-BY):
1. Timestamp Approximation:
   `firstseen` and `lastseen` UTC timestamps are used as proxies for actual departure
   and arrival. This is an explicit approximation: first/last-seen timestamps reflect the
   spatial line-of-sight coverage of crowdsourced ADS-B receivers (often tens of nautical
   miles from the airport or climbing through 3,000+ feet), NOT actual gate pushback/arrival
   or wheels-off/touchdown times (OOOI - Out, Off, On, In).
2. Airport Matching Gaps:
   The `origin` and `destination` fields in the Zenodo dataset are inferred from flight
   trajectories and can be empty/NULL when no airport perimeter match is detected.
3. Geographical Density Imbalance:
   Receiver density is heavily concentrated in North America and Western Europe.
   Coverage across transoceanic, African, and certain Asian/South American corridors
   can be sparse or intermittent.
"""

from datetime import date, datetime, timedelta
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd

from config.settings import get_settings
from ingest_delays.schedule_reference import FlightScheduleReference
from ingest_load_factors.normalizer import Normalizer

logger = logging.getLogger(__name__)


class OpenSkyZenodoParser:
    """Parses OpenSky crowdsourced air traffic monthly CSV files from Zenodo."""

    def __init__(self):
        self.settings = get_settings()
        self.normalizer = Normalizer()
        self.schedule_ref = FlightScheduleReference()

    def parse_csv(
        self,
        file_path: Union[str, Path],
        target_carriers: Optional[List[str]] = None,
        target_routes: Optional[List[tuple]] = None
    ) -> pd.DataFrame:
        """Parses Zenodo CSV dump and transforms into common delay_stats schema.
        
        Expected Zenodo columns:
        - callsign: e.g. 'AAL100', 'DAL300'
        - origin: ICAO code (e.g. 'KJFK', 'EGLL') or empty
        - destination: ICAO code (e.g. 'KLAX', 'EGLL') or empty
        - firstseen: UTC timestamp integer or ISO string
        - lastseen: UTC timestamp integer or ISO string
        - day: timestamp or date string
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Zenodo file not found: {path}")

        logger.info(
            "Parsing OpenSky Zenodo CSV from %s (Note: using first-seen/last-seen as departure/arrival approximation).",
            path
        )
        df = pd.read_csv(path)
        return self._transform_zenodo_dataframe(df, target_carriers=target_carriers, target_routes=target_routes)

    def _transform_zenodo_dataframe(
        self,
        df: pd.DataFrame,
        target_carriers: Optional[List[str]] = None,
        target_routes: Optional[List[tuple]] = None
    ) -> pd.DataFrame:
        """Standardizes Zenodo columns, cleans missing values, and estimates delay."""
        df.columns = [str(c).strip().lower() for c in df.columns]

        callsign_col = next((c for c in ["callsign", "flight_no"] if c in df.columns), None)
        origin_col = next((c for c in ["origin", "estdepartureairport"] if c in df.columns), None)
        dest_col = next((c for c in ["destination", "dest", "estarrivalairport"] if c in df.columns), None)
        firstseen_col = next((c for c in ["firstseen", "actual_dep"] if c in df.columns), None)
        lastseen_col = next((c for c in ["lastseen", "actual_arr"] if c in df.columns), None)
        day_col = next((c for c in ["day", "date"] if c in df.columns), None)

        if not all([callsign_col, origin_col, dest_col, firstseen_col, lastseen_col]):
            raise ValueError(f"Zenodo CSV missing required columns. Available: {df.columns.tolist()}")

        records = []
        for _, row in df.iterrows():
            orig_raw = str(row[origin_col]).strip() if pd.notna(row[origin_col]) else ""
            dest_raw = str(row[dest_col]).strip() if pd.notna(row[dest_col]) else ""

            # Check limitation: skip rows where origin or destination is missing/unmatched
            if not orig_raw or not dest_raw or orig_raw == "nan" or dest_raw == "nan":
                continue

            orig_iata = self.normalizer.normalize_airport(orig_raw, target_format="IATA")
            dest_iata = self.normalizer.normalize_airport(dest_raw, target_format="IATA")

            if target_routes and (orig_iata, dest_iata) not in target_routes and (dest_iata, orig_iata) not in target_routes:
                continue

            callsign = str(row[callsign_col]).strip() if pd.notna(row[callsign_col]) else ""
            # Extract carrier code from callsign (e.g. 'AAL' -> 'AA', 'BAW' -> 'BA')
            carrier_prefix = callsign[:3].upper() if len(callsign) >= 3 else callsign[:2].upper()
            carrier_iata = self.normalizer.normalize_carrier(carrier_prefix, target_format="IATA")

            if target_carriers and carrier_iata not in target_carriers:
                continue

            # Parse timestamps
            try:
                firstseen_val = row[firstseen_col]
                lastseen_val = row[lastseen_col]

                if isinstance(firstseen_val, (int, float)) or (isinstance(firstseen_val, str) and firstseen_val.isdigit()):
                    act_dep_dt = datetime.utcfromtimestamp(float(firstseen_val))
                else:
                    act_dep_dt = pd.to_datetime(firstseen_val).to_pydatetime()

                if isinstance(lastseen_val, (int, float)) or (isinstance(lastseen_val, str) and lastseen_val.isdigit()):
                    act_arr_dt = datetime.utcfromtimestamp(float(lastseen_val))
                else:
                    act_arr_dt = pd.to_datetime(lastseen_val).to_pydatetime()
            except Exception:
                continue

            fl_date = act_dep_dt.date()

            # Match against published reference schedule
            sched = self.schedule_ref.get_scheduled_flight(carrier_iata, orig_iata, dest_iata, fl_date, callsign)
            sched_dep = sched["scheduled_dep"]
            sched_arr = sched["scheduled_arr"]

            dep_delay_min = round((act_dep_dt - sched_dep).total_seconds() / 60.0, 1)
            arr_delay_min = round((act_arr_dt - sched_arr).total_seconds() / 60.0, 1)

            records.append({
                "carrier": carrier_iata,
                "origin": orig_iata,
                "dest": dest_iata,
                "date": fl_date,
                "flight_no": callsign,
                "scheduled_dep": sched_dep,
                "actual_dep": act_dep_dt,
                "delay_min": dep_delay_min,
                "scheduled_arr": sched_arr,
                "actual_arr": act_arr_dt,
                "delay_min_arr": arr_delay_min,
                "data_source": "OPENSKY_ZENODO_CSV"
            })

        return pd.DataFrame(records)

    def generate_seed_zenodo_data(
        self,
        output_path: Optional[Path] = None,
        days: int = 14
    ) -> pd.DataFrame:
        """Generates realistic Zenodo crowdsourced air traffic records across routes and carriers."""
        import random
        random.seed(101)

        start_date = date(2024, 6, 1)
        records = []

        # Carrier typical performance baseline (mean arr delay minutes, std)
        carrier_perf = {
            "AA": (12.0, 22.0),
            "DL": (6.5, 16.0),
            "UA": (11.0, 20.0),
            "B6": (17.5, 26.0),
            "WN": (14.0, 21.0),
            "BA": (15.0, 24.0),
            "LH": (16.0, 25.0),
            "AF": (13.5, 21.0),
            "SQ": (4.5, 12.0),
        }

        for day_offset in range(days):
            current_date = start_date + timedelta(days=day_offset)
            
            for route in self.settings.routes:
                orig, dest = route["origin"], route["dest"]
                orig_icao = self.normalizer.normalize_airport(orig, target_format="ICAO")
                dest_icao = self.normalizer.normalize_airport(dest, target_format="ICAO")

                for carrier_info in self.settings.carriers:
                    carrier = carrier_info["code"]
                    carrier_icao = carrier_info.get("icao", self.normalizer.normalize_carrier(carrier, "ICAO"))
                    
                    # Check if carrier flies route
                    slots = self.schedule_ref.schedules.get((carrier, orig, dest))
                    if not slots:
                        continue

                    mean_d, std_d = carrier_perf.get(carrier, (10.0, 20.0))

                    for slot in slots:
                        # Emulate occasional missing airport coverage gap (~5% rate in crowdsourced feeds)
                        if random.random() < 0.04:
                            continue

                        sched_dep = datetime.combine(current_date, slot["dep_time"])
                        sched_arr = sched_dep + timedelta(minutes=slot["duration_min"])

                        # Realistic delay distribution (skewed lognormal / gaussian blend)
                        is_disrupted = random.random() < 0.18
                        delay_arr = random.expovariate(1.0 / 35.0) if is_disrupted else random.gauss(mean_d, std_d)
                        delay_dep = delay_arr + random.gauss(2.0, 6.0)

                        act_dep = sched_dep + timedelta(minutes=delay_dep)
                        act_arr = sched_arr + timedelta(minutes=delay_arr)

                        records.append({
                            "callsign": f"{carrier_icao}{slot['flight_no'].replace(carrier, '')}",
                            "number": slot["flight_no"],
                            "icao24": f"{carrier.lower()}{random.randint(1000, 9999):x}",
                            "registration": f"N{random.randint(100, 999)}{carrier}",
                            "typecode": "B738" if route.get("aircraft_type") == "Narrowbody" else "B77W",
                            "origin": orig_icao,
                            "destination": dest_icao,
                            "firstseen": int(act_dep.timestamp()),
                            "lastseen": int(act_arr.timestamp()),
                            "day": int(datetime.combine(current_date, datetime.min.time()).timestamp())
                        })

        df = pd.DataFrame(records)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False)
            logger.info("Saved seed Zenodo crowdsourced data (%d rows) to %s", len(df), output_path)

        return df
