"""Analytical Query Service supporting Airline, Sector, and Origin-Destination granularities."""

import logging
from typing import List, Optional, Union
import numpy as np
import pandas as pd

from config.settings import get_settings
from database.db_manager import DatabaseManager
from analysis.metrics import EconomicsCalculator

logger = logging.getLogger(__name__)


class AnalysisQueryService:
    """Provides high-performance analytical queries joining load factors, delays, delay costs, and pricing."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.settings = get_settings()
        self.db = db or DatabaseManager()
        self.calc = EconomicsCalculator()

    def query_comprehensive_economics(
        self,
        carriers: Optional[List[str]] = None,
        sectors: Optional[List[str]] = None,
        routes: Optional[List[tuple]] = None,
        quarter: Optional[str] = None
    ) -> pd.DataFrame:
        """Core analytical query joining all four data models in DuckDB."""
        # 1. Aggregated load factors
        lf_where = []
        if quarter:
            lf_where.append(f"quarter = '{quarter}'")
        if carriers:
            c_str = "', '".join(carriers)
            lf_where.append(f"carrier IN ('{c_str}')")
        lf_clause = f"WHERE {' AND '.join(lf_where)}" if lf_where else ""

        lf_query = f"""
        SELECT 
            carrier, origin, dest,
            round(avg(load_factor), 4) as avg_load_factor,
            sum(asm) as total_asm,
            sum(rpm) as total_rpm
        FROM load_factors
        {lf_clause}
        GROUP BY carrier, origin, dest
        """
        lf_df = self.db.query_df(lf_query)

        # 2. Aggregated delays & costs
        delays_where = []
        if carriers:
            c_str = "', '".join(carriers)
            delays_where.append(f"carrier IN ('{c_str}')")
        delays_clause = f"WHERE {' AND '.join(delays_where)}" if delays_where else ""

        delays_query = f"""
        SELECT 
            d.carrier,
            d.origin,
            d.dest,
            count(*) as flight_count,
            round(avg(d.delay_min_arr), 1) as avg_arr_delay_min,
            round(median(d.delay_min_arr), 1) as median_arr_delay_min,
            round(avg(case when d.delay_min_arr <= 15.0 then 1.0 else 0.0 end) * 100.0, 1) as on_time_pct,
            round(avg(k.airline_delay_cost), 2) as avg_airline_delay_cost,
            round(avg(k.passenger_delay_cost), 2) as avg_passenger_delay_cost,
            round(avg(k.total_delay_cost), 2) as avg_total_delay_cost,
            round(avg(k.delay_cost_per_seat), 2) as avg_delay_cost_per_seat
        FROM delay_stats d
        LEFT JOIN delay_costs k 
            ON d.carrier = k.carrier 
            AND d.origin = k.origin 
            AND d.dest = k.dest 
            AND d.date = k.date 
            AND d.flight_no = k.flight_no
        {delays_clause}
        GROUP BY d.carrier, d.origin, d.dest
        """
        delays_df = self.db.query_df(delays_query)

        # 3. Aggregated pricing
        pricing_where = []
        if carriers:
            c_str = "', '".join(carriers)
            pricing_where.append(f"carrier IN ('{c_str}')")
        pricing_clause = f"WHERE {' AND '.join(pricing_where)}" if pricing_where else ""

        pricing_query = f"""
        SELECT 
            carrier, origin, dest,
            round(avg(price), 2) as avg_ticket_price,
            round(min(price), 2) as min_ticket_price,
            round(max(price), 2) as max_ticket_price
        FROM pricing
        {pricing_clause}
        GROUP BY carrier, origin, dest
        """
        pricing_df = self.db.query_df(pricing_query)

        # 4. Routes metadata
        routes_df = self.db.query_df("SELECT origin, dest, sector, distance_miles, aircraft_type FROM routes")
        carriers_df = self.db.query_df("SELECT code as carrier, name as carrier_name FROM carriers")

        # 5. Join in pandas
        merged = pd.merge(routes_df, delays_df, on=["origin", "dest"], how="inner")
        if not lf_df.empty:
            merged = pd.merge(merged, lf_df, on=["carrier", "origin", "dest"], how="left")
        else:
            merged["avg_load_factor"] = 0.80

        if not pricing_df.empty:
            merged = pd.merge(merged, pricing_df, on=["carrier", "origin", "dest"], how="left")
        else:
            merged["avg_ticket_price"] = 250.0

        if not carriers_df.empty:
            merged = pd.merge(merged, carriers_df, on=["carrier"], how="left")

        # Fallbacks for missing values
        merged["avg_load_factor"] = merged["avg_load_factor"].fillna(0.80)
        merged["avg_ticket_price"] = merged["avg_ticket_price"].fillna(
            merged["distance_miles"].apply(lambda d: round(max(99.0, d * 0.12), 2))
        )
        merged["avg_delay_cost_per_seat"] = merged["avg_delay_cost_per_seat"].fillna(12.50)

        # Compute Composite True Cost
        pvot = float(self.settings.delay_cost.get("passenger_value_of_time_per_min", 0.783))
        merged["passenger_delay_cost_per_seat"] = (merged["avg_arr_delay_min"].clip(lower=0.0) * pvot).round(2)
        merged["true_cost_per_seat"] = (merged["avg_ticket_price"] + merged["passenger_delay_cost_per_seat"]).round(2)

        # Filters
        if sectors:
            merged = merged[merged["sector"].isin(sectors)]
        if routes:
            merged = merged[merged.apply(lambda r: (r["origin"], r["dest"]) in routes or (r["dest"], r["origin"]) in routes, axis=1)]

        return merged

    def query_by_airline(
        self,
        carrier_code: Optional[str] = None,
        quarter: Optional[str] = None
    ) -> pd.DataFrame:
        """Granularity 1: Airline-level aggregation or comparison across multiple airlines."""
        carriers = [carrier_code] if carrier_code else None
        df = self.query_comprehensive_economics(carriers=carriers, quarter=quarter)
        if df.empty:
            return pd.DataFrame()

        agg = df.groupby(["carrier", "carrier_name"], as_index=False).agg({
            "flight_count": "sum",
            "avg_load_factor": "mean",
            "avg_arr_delay_min": "mean",
            "median_arr_delay_min": "mean",
            "on_time_pct": "mean",
            "avg_airline_delay_cost": "mean",
            "avg_delay_cost_per_seat": "mean",
            "avg_ticket_price": "mean",
            "passenger_delay_cost_per_seat": "mean",
            "true_cost_per_seat": "mean"
        })

        # Round values for display
        for col in ["avg_load_factor"]:
            agg[col] = agg[col].round(3)
        for col in ["avg_arr_delay_min", "median_arr_delay_min", "on_time_pct"]:
            agg[col] = agg[col].round(1)
        for col in ["avg_airline_delay_cost", "avg_delay_cost_per_seat", "avg_ticket_price", "passenger_delay_cost_per_seat", "true_cost_per_seat"]:
            agg[col] = agg[col].round(2)

        return agg.sort_values(by="true_cost_per_seat", ascending=True)

    def query_by_sector(
        self,
        sector_name: Optional[str] = None,
        quarter: Optional[str] = None
    ) -> pd.DataFrame:
        """Granularity 2: Sector-level aggregation (e.g. US Domestic Transcon, Transatlantic, etc.)."""
        sectors = [sector_name] if sector_name else None
        df = self.query_comprehensive_economics(sectors=sectors, quarter=quarter)
        if df.empty:
            return pd.DataFrame()

        agg = df.groupby(["sector", "carrier", "carrier_name"], as_index=False).agg({
            "flight_count": "sum",
            "avg_load_factor": "mean",
            "avg_arr_delay_min": "mean",
            "median_arr_delay_min": "mean",
            "on_time_pct": "mean",
            "avg_airline_delay_cost": "mean",
            "avg_ticket_price": "mean",
            "passenger_delay_cost_per_seat": "mean",
            "true_cost_per_seat": "mean"
        })

        for col in ["avg_load_factor"]:
            agg[col] = agg[col].round(3)
        for col in ["avg_arr_delay_min", "median_arr_delay_min", "on_time_pct"]:
            agg[col] = agg[col].round(1)
        for col in ["avg_airline_delay_cost", "avg_ticket_price", "passenger_delay_cost_per_seat", "true_cost_per_seat"]:
            agg[col] = agg[col].round(2)

        return agg.sort_values(by=["sector", "true_cost_per_seat"], ascending=[True, True])

    def query_by_od_pair(
        self,
        origin: str,
        dest: str,
        quarter: Optional[str] = None
    ) -> pd.DataFrame:
        """Granularity 3: Individual origin-destination pair comparison across carriers."""
        routes = [(origin.upper(), dest.upper())]
        df = self.query_comprehensive_economics(routes=routes, quarter=quarter)
        if df.empty:
            return pd.DataFrame()

        cols = [
            "origin", "dest", "sector", "carrier", "carrier_name",
            "avg_load_factor", "avg_arr_delay_min", "median_arr_delay_min", "on_time_pct",
            "avg_airline_delay_cost", "avg_ticket_price", "passenger_delay_cost_per_seat", "true_cost_per_seat"
        ]
        return df[cols].sort_values(by="true_cost_per_seat", ascending=True)
