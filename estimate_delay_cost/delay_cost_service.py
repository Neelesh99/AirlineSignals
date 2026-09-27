"""Delay Cost Estimation Service: computes flight, route, and carrier level delay expenses."""

import logging
from typing import Any, Dict, List, Optional
import pandas as pd

from config.settings import get_settings
from database.db_manager import DatabaseManager
from estimate_delay_cost.cost_model import DelayCostModel

logger = logging.getLogger(__name__)


class DelayCostService:
    """Computes delay costs and persists aggregated estimates into the database."""

    def __init__(self, db: Optional[DatabaseManager] = None, model: Optional[DelayCostModel] = None):
        self.settings = get_settings()
        self.db = db or DatabaseManager()
        self.model = model or DelayCostModel.from_config()

    def update_cost_assumptions(
        self,
        direct_operating_cost_per_min: Optional[float] = None,
        pvot_per_min: Optional[float] = None,
        threshold_minutes: Optional[float] = None
    ) -> None:
        """Allows dynamic overrides of cost benchmarks."""
        if direct_operating_cost_per_min is not None:
            self.model.direct_operating_cost_per_min = direct_operating_cost_per_min
        if pvot_per_min is not None:
            self.model.passenger_value_of_time_per_min = pvot_per_min
        if threshold_minutes is not None:
            self.model.cost_threshold_minutes = threshold_minutes
        logger.info(
            "Updated delay cost model parameters: Direct=$%.2f/min, PVOT=$%.3f/min, Threshold=%.1fm",
            self.model.direct_operating_cost_per_min,
            self.model.passenger_value_of_time_per_min,
            self.model.cost_threshold_minutes
        )

    def run_estimation(self) -> pd.DataFrame:
        """Processes all delay_stats records and calculates economic delay cost per flight."""
        # Query delay_stats alongside load factors and routes
        query = """
        SELECT 
            d.carrier,
            d.origin,
            d.dest,
            d.date,
            d.flight_no,
            d.delay_min_arr,
            COALESCE(r.aircraft_type, 'Narrowbody') AS aircraft_type,
            COALESCE(lf.load_factor, c.default_load_factor, 0.80) AS load_factor
        FROM delay_stats d
        LEFT JOIN routes r ON (d.origin = r.origin AND d.dest = r.dest)
        LEFT JOIN carriers c ON d.carrier = c.code
        LEFT JOIN load_factors lf 
            ON d.carrier = lf.carrier 
            AND d.origin = lf.origin 
            AND d.dest = lf.dest
            AND strftime(d.date, '%Y') || 'Q' || cast(ceiling(month(d.date) / 3.0) as int) = lf.quarter;
        """
        delays_df = self.db.query_df(query)
        if delays_df.empty:
            logger.warning("No delay_stats available for cost calculation.")
            return pd.DataFrame()

        records = []
        for _, row in delays_df.iterrows():
            arr_delay = float(row["delay_min_arr"]) if pd.notna(row["delay_min_arr"]) else 0.0
            ac_type = str(row["aircraft_type"]) if pd.notna(row["aircraft_type"]) else "Narrowbody"
            lf = float(row["load_factor"]) if pd.notna(row["load_factor"]) else 0.80

            costs = self.model.calculate_flight_cost(
                delay_min_arr=arr_delay,
                aircraft_type=ac_type,
                load_factor=lf
            )

            records.append({
                "carrier": row["carrier"],
                "origin": row["origin"],
                "dest": row["dest"],
                "date": row["date"],
                "flight_no": row["flight_no"],
                "delay_min_arr": arr_delay,
                "airline_delay_cost": costs["airline_delay_cost"],
                "passenger_delay_cost": costs["passenger_delay_cost"],
                "total_delay_cost": costs["total_delay_cost"],
                "delay_cost_per_seat": costs["delay_cost_per_seat"],
                "cost_model": self.model.model_name
            })

        cost_df = pd.DataFrame(records)
        rows_inserted = self.db.insert_delay_costs(cost_df)
        logger.info("Calculated and inserted %d delay cost records.", rows_inserted)
        return cost_df

    def get_route_expected_delay_cost(self) -> pd.DataFrame:
        """Aggregates expected delay cost per route."""
        query = """
        SELECT 
            origin,
            dest,
            count(*) as flight_count,
            round(avg(delay_min_arr), 1) as avg_delay_min,
            round(avg(airline_delay_cost), 2) as avg_airline_delay_cost,
            round(avg(passenger_delay_cost), 2) as avg_passenger_delay_cost,
            round(avg(total_delay_cost), 2) as avg_total_delay_cost,
            round(sum(total_delay_cost), 2) as total_network_delay_cost
        FROM delay_costs
        GROUP BY origin, dest
        ORDER BY avg_total_delay_cost DESC;
        """
        return self.db.query_df(query)

    def get_carrier_expected_delay_cost(self) -> pd.DataFrame:
        """Aggregates expected delay cost per carrier."""
        query = """
        SELECT 
            carrier,
            count(*) as flight_count,
            round(avg(delay_min_arr), 1) as avg_delay_min,
            round(avg(airline_delay_cost), 2) as avg_airline_delay_cost,
            round(avg(passenger_delay_cost), 2) as avg_passenger_delay_cost,
            round(avg(total_delay_cost), 2) as avg_total_delay_cost,
            round(sum(total_delay_cost), 2) as total_carrier_delay_cost
        FROM delay_costs
        GROUP BY carrier
        ORDER BY avg_total_delay_cost DESC;
        """
        return self.db.query_df(query)
