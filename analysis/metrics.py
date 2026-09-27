"""Core Economic Metrics and True Cost Calculation."""

from dataclasses import dataclass
from typing import Dict, Optional
import numpy as np
import pandas as pd

from config.settings import get_settings


@dataclass
class RouteEconomicsMetric:
    """Summary metrics container for an airline/route/sector combination."""
    carrier: str
    entity_name: str
    avg_load_factor: float
    avg_delay_min: float
    median_delay_min: float
    on_time_pct: float
    avg_delay_cost_flight: float
    avg_delay_cost_seat: float
    avg_ticket_price: float
    composite_true_cost: float


class EconomicsCalculator:
    """Calculates composite airline route economics metrics."""

    def __init__(self):
        self.settings = get_settings()
        self.pvot_per_min = float(self.settings.delay_cost.get("passenger_value_of_time_per_min", 0.783))

    def compute_composite_true_cost(
        self,
        avg_price: float,
        avg_delay_min: float,
        airline_delay_cost_per_seat: Optional[float] = None
    ) -> float:
        """Computes the composite 'true cost per seat' metric.
        
        True Cost = Average Ticket Price + (Allocated Passenger Delay Cost)
        Where Passenger Delay Cost = max(0, avg_delay_min) * PVOT ($/minute)
        """
        effective_delay = max(0.0, avg_delay_min)
        passenger_delay_cost = effective_delay * self.pvot_per_min
        
        # Total true cost borne by passenger
        true_cost = avg_price + passenger_delay_cost
        return round(true_cost, 2)
