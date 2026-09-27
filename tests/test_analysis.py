"""Unit and integration tests for Analysis Query Service across all 3 granularities."""

from pathlib import Path
import pytest
from database.db_manager import DatabaseManager
from pipeline import RouteEconomicsPipeline
from analysis.query_service import AnalysisQueryService
from analysis.metrics import EconomicsCalculator


@pytest.fixture(scope="module")
def populated_db(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("db") / "test_pipeline.duckdb"
    db = DatabaseManager(db_path=db_file)
    pipeline = RouteEconomicsPipeline(db=db)
    
    # Run full pipeline with sample generation
    pipeline.run_stage_load_factors()
    pipeline.run_stage_delays(provider="zenodo")
    pipeline.run_stage_delay_costs()
    pipeline.run_stage_pricing(days_ahead=7, window_days=2)

    return db


def test_composite_true_cost_formula():
    calc = EconomicsCalculator()
    ticket_price = 300.0
    avg_delay_min = 20.0
    # True Cost = 300 + (20 * 0.783) = 300 + 15.66 = 315.66
    true_cost = calc.compute_composite_true_cost(ticket_price, avg_delay_min)
    assert true_cost == 315.66


def test_granularity_1_airline_level(populated_db):
    service = AnalysisQueryService(db=populated_db)
    df = service.query_by_airline()

    assert not df.empty
    assert "carrier" in df.columns
    assert "avg_load_factor" in df.columns
    assert "avg_arr_delay_min" in df.columns
    assert "avg_ticket_price" in df.columns
    assert "true_cost_per_seat" in df.columns
    assert (df["true_cost_per_seat"] >= df["avg_ticket_price"]).all()


def test_granularity_2_sector_level(populated_db):
    service = AnalysisQueryService(db=populated_db)
    df = service.query_by_sector(sector_name="Transatlantic")

    assert not df.empty
    assert (df["sector"] == "Transatlantic").all()
    assert "carrier" in df.columns
    assert "true_cost_per_seat" in df.columns


def test_granularity_3_od_pair(populated_db):
    service = AnalysisQueryService(db=populated_db)
    df = service.query_by_od_pair(origin="JFK", dest="LAX")

    assert not df.empty
    assert (df["origin"] == "JFK").all()
    assert (df["dest"] == "LAX").all()
    assert "true_cost_per_seat" in df.columns
