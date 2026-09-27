"""Delay Cost Model based on Airlines for America (A4A) benchmarks and DOT PVOT."""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class AircraftCostParams:
    multiplier: float
    avg_seats: int


@dataclass
class DelayCostModel:
    """Configurable delay cost calculation engine.
    
    Default parameters reflect Airlines for America (A4A) empirical cost of delay benchmarks:
    - Direct aircraft operating cost per minute: ~$85.50 (fuel, crew, maintenance, equipment)
    - US DOT / FAA Passenger Value of Time (PVOT): ~$47.00/hour (~$0.783/minute per passenger)
    """
    model_name: str = "A4A_DOT_Benchmark"
    direct_operating_cost_per_min: float = 85.50
    passenger_value_of_time_per_min: float = 0.783
    cost_threshold_minutes: float = 0.0
    aircraft_categories: Dict[str, AircraftCostParams] = field(default_factory=lambda: {
        "Regional": AircraftCostParams(multiplier=0.70, avg_seats=76),
        "Narrowbody": AircraftCostParams(multiplier=1.00, avg_seats=162),
        "Widebody": AircraftCostParams(multiplier=1.65, avg_seats=285),
    })

    @classmethod
    def from_config(cls, custom_config: Optional[Dict[str, Any]] = None) -> "DelayCostModel":
        """Instantiates cost model from application config or custom overrides."""
        settings = get_settings()
        cfg = custom_config or settings.delay_cost

        base_direct = float(cfg.get("direct_operating_cost_per_min", 85.50))
        pvot = float(cfg.get("passenger_value_of_time_per_min", 0.783))
        threshold = float(cfg.get("apply_cost_threshold_minutes", 0.0))

        cats = {}
        for cat_name, val in cfg.get("aircraft_categories", {}).items():
            mult = float(val.get("direct_cost_multiplier", 1.0))
            seats = int(val.get("avg_seats", 160))
            cats[cat_name] = AircraftCostParams(multiplier=mult, avg_seats=seats)

        if not cats:
            cats = {
                "Regional": AircraftCostParams(multiplier=0.70, avg_seats=76),
                "Narrowbody": AircraftCostParams(multiplier=1.00, avg_seats=162),
                "Widebody": AircraftCostParams(multiplier=1.65, avg_seats=285),
            }

        return cls(
            model_name="Configurable_A4A_Model",
            direct_operating_cost_per_min=base_direct,
            passenger_value_of_time_per_min=pvot,
            cost_threshold_minutes=threshold,
            aircraft_categories=cats
        )

    def calculate_flight_cost(
        self,
        delay_min_arr: float,
        aircraft_type: str = "Narrowbody",
        load_factor: float = 0.80
    ) -> Dict[str, float]:
        """Calculates airline direct, passenger value of time, and total economic delay cost."""
        effective_delay = max(0.0, delay_min_arr - self.cost_threshold_minutes)
        if effective_delay <= 0:
            return {
                "delay_min_arr": delay_min_arr,
                "airline_delay_cost": 0.0,
                "passenger_delay_cost": 0.0,
                "total_delay_cost": 0.0,
                "delay_cost_per_seat": 0.0,
                "delay_cost_per_pax": 0.0
            }

        cat_params = self.aircraft_categories.get(aircraft_type, self.aircraft_categories["Narrowbody"])
        
        # 1. Direct airline operating cost = delay * $/min * aircraft multiplier
        airline_cost = effective_delay * self.direct_operating_cost_per_min * cat_params.multiplier
        
        # 2. Passenger delay cost = delay * PVOT * (seats * load_factor)
        passengers_onboard = cat_params.avg_seats * max(0.1, min(1.0, load_factor))
        passenger_cost = effective_delay * self.passenger_value_of_time_per_min * passengers_onboard
        
        total_cost = airline_cost + passenger_cost
        cost_per_seat = total_cost / cat_params.avg_seats
        cost_per_pax = total_cost / passengers_onboard

        return {
            "delay_min_arr": delay_min_arr,
            "airline_delay_cost": round(airline_cost, 2),
            "passenger_delay_cost": round(passenger_cost, 2),
            "total_delay_cost": round(total_cost, 2),
            "delay_cost_per_seat": round(cost_per_seat, 2),
            "delay_cost_per_pax": round(cost_per_pax, 2)
        }
