"""Database connection, schema migration, and repository layer for DuckDB/SQLite."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import duckdb
import pandas as pd

from config.settings import get_settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages analytical database connections, schema setup, and querying."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        settings = get_settings()
        self.db_path = Path(db_path) if db_path else settings.database_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self.initialize_schema()

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        return self.conn

    def initialize_schema(self) -> None:
        """Creates tables, indices, and analytical views if they do not already exist."""
        with self.conn.cursor() as cur:
            # 1. Routes metadata table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS routes (
                origin VARCHAR(4),
                dest VARCHAR(4),
                sector VARCHAR(64),
                distance_miles INTEGER,
                aircraft_type VARCHAR(32),
                PRIMARY KEY (origin, dest)
            );
            """)

            # 2. Carriers metadata table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS carriers (
                code VARCHAR(3) PRIMARY KEY,
                icao VARCHAR(4),
                name VARCHAR(128),
                country VARCHAR(4),
                default_load_factor DOUBLE
            );
            """)

            # 3. Load factors table
            # Schema requirement: load_factors(carrier, origin, dest, quarter, asm, rpm, load_factor, source)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS load_factors (
                carrier VARCHAR(4),
                origin VARCHAR(4),
                dest VARCHAR(4),
                quarter VARCHAR(10), -- e.g. 2024Q1
                asm DOUBLE,          -- Available Seat Miles
                rpm DOUBLE,          -- Revenue Passenger Miles
                load_factor DOUBLE,  -- rpm / asm
                source VARCHAR(32),  -- 'BTS_T100', 'BTS_SYSTEM_FALLBACK', 'IR_REPORT'
                PRIMARY KEY (carrier, origin, dest, quarter)
            );
            """)

            # 4. Delay stats table
            # Schema requirement: delay_stats(carrier, origin, dest, date, flight_no, scheduled_dep, actual_dep, delay_min, scheduled_arr, actual_arr, delay_min_arr, data_source)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS delay_stats (
                carrier VARCHAR(4),
                origin VARCHAR(4),
                dest VARCHAR(4),
                date DATE,
                flight_no VARCHAR(16),
                scheduled_dep TIMESTAMP,
                actual_dep TIMESTAMP,
                delay_min DOUBLE,        -- Departure delay minutes
                scheduled_arr TIMESTAMP,
                actual_arr TIMESTAMP,
                delay_min_arr DOUBLE,    -- Arrival delay minutes
                data_source VARCHAR(32), -- 'OPENSKY_TRINO' or 'OPENSKY_ZENODO_CSV'
                PRIMARY KEY (carrier, origin, dest, date, flight_no)
            );
            """)

            # 5. Delay costs table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS delay_costs (
                carrier VARCHAR(4),
                origin VARCHAR(4),
                dest VARCHAR(4),
                date DATE,
                flight_no VARCHAR(16),
                delay_min_arr DOUBLE,
                airline_delay_cost DOUBLE,
                passenger_delay_cost DOUBLE,
                total_delay_cost DOUBLE,
                delay_cost_per_seat DOUBLE,
                cost_model VARCHAR(32),
                PRIMARY KEY (carrier, origin, dest, date, flight_no)
            );
            """)

            # 6. Pricing table
            # Schema requirement: pricing(carrier, origin, dest, travel_date, search_date, price, cabin_class, stops)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS pricing (
                carrier VARCHAR(4),
                origin VARCHAR(4),
                dest VARCHAR(4),
                travel_date DATE,
                search_date DATE,
                price DOUBLE,
                cabin_class VARCHAR(32),
                stops INTEGER,
                PRIMARY KEY (carrier, origin, dest, travel_date, cabin_class, stops)
            );
            """)

            # 7. Create analytical joined view
            cur.execute("""
            CREATE OR REPLACE VIEW v_flight_delays_with_costs AS
            SELECT 
                d.carrier,
                c.name AS carrier_name,
                d.origin,
                d.dest,
                r.sector,
                r.distance_miles,
                r.aircraft_type,
                d.date,
                d.flight_no,
                d.delay_min AS dep_delay_min,
                d.delay_min_arr AS arr_delay_min,
                d.data_source,
                COALESCE(k.airline_delay_cost, 0.0) AS airline_delay_cost,
                COALESCE(k.passenger_delay_cost, 0.0) AS passenger_delay_cost,
                COALESCE(k.total_delay_cost, 0.0) AS total_delay_cost,
                COALESCE(k.delay_cost_per_seat, 0.0) AS delay_cost_per_seat
            FROM delay_stats d
            LEFT JOIN delay_costs k 
                ON d.carrier = k.carrier 
                AND d.origin = k.origin 
                AND d.dest = k.dest 
                AND d.date = k.date 
                AND d.flight_no = k.flight_no
            LEFT JOIN carriers c ON d.carrier = c.code
            LEFT JOIN routes r ON (d.origin = r.origin AND d.dest = r.dest);
            """)

            # Seed metadata from configuration
            self._seed_reference_data(cur)

    def _seed_reference_data(self, cur: duckdb.DuckDBPyConnection) -> None:
        """Seed routes and carriers metadata from YAML config."""
        settings = get_settings()

        for carrier in settings.carriers:
            cur.execute("""
            INSERT OR REPLACE INTO carriers (code, icao, name, country, default_load_factor)
            VALUES (?, ?, ?, ?, ?)
            """, [
                carrier["code"],
                carrier.get("icao", ""),
                carrier.get("name", ""),
                carrier.get("country", ""),
                carrier.get("default_load_factor", 0.80)
            ])

        for route in settings.routes:
            cur.execute("""
            INSERT OR REPLACE INTO routes (origin, dest, sector, distance_miles, aircraft_type)
            VALUES (?, ?, ?, ?, ?)
            """, [
                route["origin"],
                route["dest"],
                route.get("sector", "Other"),
                route.get("distance_miles", 0),
                route.get("aircraft_type", "Narrowbody")
            ])

    def insert_load_factors(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        cols = ["carrier", "origin", "dest", "quarter", "asm", "rpm", "load_factor", "source"]
        df_clean = df[cols].copy()
        self.conn.register("tmp_lf", df_clean)
        self.conn.execute("""
        INSERT OR REPLACE INTO load_factors 
        SELECT * FROM tmp_lf
        """)
        self.conn.unregister("tmp_lf")
        return len(df_clean)

    def insert_delay_stats(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        cols = [
            "carrier", "origin", "dest", "date", "flight_no",
            "scheduled_dep", "actual_dep", "delay_min",
            "scheduled_arr", "actual_arr", "delay_min_arr", "data_source"
        ]
        df_clean = df[cols].copy()
        self.conn.register("tmp_delays", df_clean)
        self.conn.execute("""
        INSERT OR REPLACE INTO delay_stats 
        SELECT * FROM tmp_delays
        """)
        self.conn.unregister("tmp_delays")
        return len(df_clean)

    def insert_delay_costs(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        cols = [
            "carrier", "origin", "dest", "date", "flight_no",
            "delay_min_arr", "airline_delay_cost", "passenger_delay_cost",
            "total_delay_cost", "delay_cost_per_seat", "cost_model"
        ]
        df_clean = df[cols].copy()
        self.conn.register("tmp_costs", df_clean)
        self.conn.execute("""
        INSERT OR REPLACE INTO delay_costs 
        SELECT * FROM tmp_costs
        """)
        self.conn.unregister("tmp_costs")
        return len(df_clean)

    def insert_pricing(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        cols = ["carrier", "origin", "dest", "travel_date", "search_date", "price", "cabin_class", "stops"]
        df_clean = df[cols].copy()
        self.conn.register("tmp_pricing", df_clean)
        self.conn.execute("""
        INSERT OR REPLACE INTO pricing 
        SELECT * FROM tmp_pricing
        """)
        self.conn.unregister("tmp_pricing")
        return len(df_clean)

    def query_df(self, query: str, params: Optional[List[Any]] = None) -> pd.DataFrame:
        if params:
            return self.conn.execute(query, params).df()
        return self.conn.execute(query).df()

    def close(self) -> None:
        self.conn.close()
