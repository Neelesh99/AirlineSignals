"""Unit tests for Delay Cost Estimation and A4A Benchmarks."""

import pytest
from estimate_delay_cost.cost_model import DelayCostModel
from estimate_delay_cost.delay_cost_service import DelayCostService
from database.db_manager import DatabaseManager


def test_delay_cost_calculation():
    model = DelayCostModel(
        direct_operating_cost_per_min=85.50,
        passenger_value_of_time_per_min=0.783
    )

    # 30 minute delay for Narrowbody (162 seats, 80% LF = 129.6 pax)
    res = model.calculate_flight_cost(delay_min_arr=30.0, aircraft_type="Narrowbody", load_factor=0.80)
    
    expected_airline_cost = 30.0 * 85.50 * 1.00 # $2565.00
    expected_pax_cost = 30.0 * 0.783 * (162 * 0.80) # $3044.30

    assert abs(res["airline_delay_cost"] - expected_airline_cost) < 1.0
    assert abs(res["passenger_delay_cost"] - expected_pax_cost) < 5.0
    assert res["total_delay_cost"] > res["airline_delay_cost"]
    assert res["delay_cost_per_seat"] > 0


def test_zero_or_negative_delay():
    model = DelayCostModel()
    res = model.calculate_flight_cost(delay_min_arr=-10.0)
    assert res["total_delay_cost"] == 0.0
    assert res["airline_delay_cost"] == 0.0


def test_aircraft_category_multipliers():
    model = DelayCostModel()
    res_reg = model.calculate_flight_cost(delay_min_arr=20.0, aircraft_type="Regional")
    res_wide = model.calculate_flight_cost(delay_min_arr=20.0, aircraft_type="Widebody")

    assert res_wide["airline_delay_cost"] > res_reg["airline_delay_cost"]
