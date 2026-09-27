"""Unit tests for OpenSky Delay Ingestion (Trino 2a and Zenodo 2b)."""

from datetime import date
from pathlib import Path
import pytest
from ingest_delays.schedule_reference import FlightScheduleReference
from ingest_delays.opensky_trino import OpenSkyTrinoClient
from ingest_delays.opensky_zenodo import OpenSkyZenodoParser
from ingest_delays.delay_service import DelayService
from database.db_manager import DatabaseManager


def test_schedule_reference():
    ref = FlightScheduleReference()
    sched = ref.get_scheduled_flight("AA", "JFK", "LAX", date(2024, 6, 1))
    assert sched is not None
    assert sched["scheduled_dep"] < sched["scheduled_arr"]
    assert sched["scheduled_duration_min"] > 0


def test_opensky_trino_query_builder():
    trino_client = OpenSkyTrinoClient()
    from datetime import datetime
    q = trino_client.build_query("AAL", "KJFK", "KLAX", datetime(2024, 6, 1), datetime(2024, 6, 2))
    assert "flights_data4" in q
    assert "AAL%" in q
    assert "KJFK" in q
    assert "KLAX" in q


def test_opensky_zenodo_seed_and_parse(tmp_path):
    parser = OpenSkyZenodoParser()
    sample_file = tmp_path / "zenodo_test.csv"
    seed_df = parser.generate_seed_zenodo_data(output_path=sample_file, days=2)

    assert not seed_df.empty
    assert "callsign" in seed_df.columns
    assert "firstseen" in seed_df.columns
    assert "lastseen" in seed_df.columns

    # Parse it back
    parsed = parser.parse_csv(sample_file)
    assert not parsed.empty
    assert "data_source" in parsed.columns
    assert (parsed["data_source"] == "OPENSKY_ZENODO_CSV").all()
    assert "delay_min_arr" in parsed.columns


def test_delay_service_schema(tmp_path):
    db_file = tmp_path / "delays_test.duckdb"
    db = DatabaseManager(db_path=db_file)
    service = DelayService(db=db)

    # Ingest with Zenodo provider
    df = service.run_ingestion(provider="zenodo", generate_if_missing=True)
    assert not df.empty
    required_cols = [
        "carrier", "origin", "dest", "date", "flight_no",
        "scheduled_dep", "actual_dep", "delay_min",
        "scheduled_arr", "actual_arr", "delay_min_arr", "data_source"
    ]
    for col in required_cols:
        assert col in df.columns

    db.close()
