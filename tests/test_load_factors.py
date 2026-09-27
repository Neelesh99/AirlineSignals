"""Unit tests for Load Factor ingestion, normalizer, and system fallback."""

import pandas as pd
import pytest
from ingest_load_factors.normalizer import Normalizer
from ingest_load_factors.bts_t100_parser import BTST100Parser
from ingest_load_factors.investor_relations import InvestorRelationsParser
from ingest_load_factors.load_factor_service import LoadFactorService
from database.db_manager import DatabaseManager


@pytest.fixture
def normalizer():
    return Normalizer()


def test_carrier_normalization(normalizer):
    assert normalizer.normalize_carrier("AA", "ICAO") == "AAL"
    assert normalizer.normalize_carrier("AAL", "IATA") == "AA"
    assert normalizer.normalize_carrier("DL", "ICAO") == "DAL"
    assert normalizer.normalize_carrier("DAL", "IATA") == "DL"
    assert normalizer.normalize_carrier("BAW", "IATA") == "BA"


def test_airport_normalization(normalizer):
    assert normalizer.normalize_airport("JFK", "ICAO") == "KJFK"
    assert normalizer.normalize_airport("KJFK", "IATA") == "JFK"
    assert normalizer.normalize_airport("LHR", "ICAO") == "EGLL"
    assert normalizer.normalize_airport("EGLL", "IATA") == "LHR"


def test_format_quarter():
    assert Normalizer.format_quarter(2024, quarter=3) == "2024Q3"
    assert Normalizer.format_quarter(2024, month=5) == "2024Q2"
    assert Normalizer.format_quarter(2024, month=10) == "2024Q4"


def test_bts_parser_seed_generation(tmp_path):
    parser = BTST100Parser()
    out_file = tmp_path / "t100_test.csv"
    df = parser.generate_seed_data(output_path=out_file)

    assert not df.empty
    assert "carrier" in df.columns
    assert "load_factor" in df.columns
    assert (df["load_factor"] >= 0.0).all() and (df["load_factor"] <= 1.0).all()
    assert (df["asm"] >= df["rpm"]).all()


def test_ir_parser_seed_generation(tmp_path):
    parser = InvestorRelationsParser()
    out_file = tmp_path / "ir_test.csv"
    df = parser.generate_seed_ir_data(output_path=out_file)

    assert not df.empty
    assert "source" in df.columns
    assert "IR_REPORT_ROUTE" in df["source"].values or "IR_REPORT_SYSTEM" in df["source"].values


def test_load_factor_service_fallback(tmp_path):
    db_file = tmp_path / "test_lf.duckdb"
    db = DatabaseManager(db_path=db_file)
    service = LoadFactorService(db=db)

    # Empty input should trigger fallback creation
    empty_df = pd.DataFrame(columns=["carrier", "origin", "dest", "quarter", "asm", "rpm", "load_factor", "source"])
    final_df = service.apply_system_wide_fallbacks(empty_df)

    assert not final_df.empty
    fallback_sources = final_df["source"].unique()
    assert "BTS_SYSTEM_FALLBACK" in fallback_sources or "IR_SYSTEM_FALLBACK" in fallback_sources
    db.close()
