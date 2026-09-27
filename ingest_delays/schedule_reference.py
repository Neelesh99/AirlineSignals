"""Flight Schedule Reference Timetable Provider."""

from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd

from config.settings import get_settings


class FlightScheduleReference:
    """Provides published timetable departure and arrival schedules for carrier routes."""

    def __init__(self):
        self.settings = get_settings()
        self.schedules = self._build_baseline_schedules()

    def _build_baseline_schedules(self) -> Dict[Tuple[str, str, str], List[Dict]]:
        """Builds timetable slots for carrier/route combinations.
        Key: (carrier, origin, dest) -> List of daily flight timetable templates.
        """
        # Common daily departure schedules by sector
        table: Dict[Tuple[str, str, str], List[Dict]] = {}
        
        # Helper to generate flight slots
        def add_slots(carrier: str, orig: str, dest: str, prefix_no: int, dep_times: List[str], duration_min: int):
            key = (carrier, orig, dest)
            slots = []
            for idx, dep_t_str in enumerate(dep_times, start=1):
                dep_h, dep_m = map(int, dep_t_str.split(":"))
                flight_no = f"{carrier}{prefix_no + idx * 10}"
                slots.append({
                    "flight_no": flight_no,
                    "dep_time": time(dep_h, dep_m),
                    "duration_min": duration_min
                })
            table[key] = slots

        # Populate realistic timetable slots
        # JFK - LAX (duration ~360m)
        add_slots("AA", "JFK", "LAX", 100, ["06:00", "09:30", "13:00", "17:15", "20:30"], 360)
        add_slots("DL", "JFK", "LAX", 300, ["07:00", "10:15", "14:30", "18:00", "21:15"], 355)
        add_slots("B6", "JFK", "LAX", 500, ["08:00", "11:45", "15:30", "19:45"], 365)

        # BOS - SFO (duration ~380m)
        add_slots("UA", "BOS", "SFO", 200, ["06:30", "10:00", "14:15", "17:45"], 380)
        add_slots("DL", "BOS", "SFO", 400, ["07:45", "11:30", "16:00"], 385)
        add_slots("B6", "BOS", "SFO", 600, ["08:15", "13:00", "18:30"], 380)

        # ORD - LGA (duration ~135m)
        add_slots("AA", "ORD", "LGA", 110, ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00", "18:00"], 135)
        add_slots("UA", "ORD", "LGA", 210, ["06:30", "08:30", "10:30", "12:30", "14:30", "16:30", "18:30"], 135)
        add_slots("DL", "ORD", "LGA", 310, ["07:00", "09:00", "11:00", "13:00", "15:00", "17:00"], 130)

        # MIA - ATL (duration ~115m)
        add_slots("DL", "MIA", "ATL", 320, ["06:00", "08:30", "11:00", "13:30", "16:00", "18:30"], 115)
        add_slots("AA", "MIA", "ATL", 120, ["07:15", "10:00", "12:45", "15:15", "17:45"], 115)

        # JFK - LHR (Transatlantic ~420m)
        add_slots("BA", "JFK", "LHR", 170, ["08:00", "18:30", "20:00", "22:15"], 420)
        add_slots("AA", "JFK", "LHR", 100, ["09:15", "19:00", "21:30"], 415)
        add_slots("DL", "JFK", "LHR", 300, ["19:30", "22:00"], 420)

        # BOS - LHR (duration ~400m)
        add_slots("BA", "BOS", "LHR", 210, ["18:15", "21:30"], 400)
        add_slots("DL", "BOS", "LHR", 340, ["19:00"], 405)

        # ORD - CDG (duration ~490m)
        add_slots("AF", "ORD", "CDG", 130, ["17:30"], 490)
        add_slots("UA", "ORD", "CDG", 250, ["18:45"], 495)

        # SFO - SIN (Transpacific ~1010m)
        add_slots("SQ", "SFO", "SIN", 30, ["10:30", "22:10"], 1010)
        add_slots("UA", "SFO", "SIN", 1, ["23:00"], 1020)

        # LHR - CDG (Intra-Europe ~75m)
        add_slots("BA", "LHR", "CDG", 300, ["07:15", "11:00", "15:20", "19:10"], 75)
        add_slots("AF", "LHR", "CDG", 1680, ["06:30", "10:15", "14:40", "18:00"], 75)

        # LHR - FRA (Intra-Europe ~95m)
        add_slots("BA", "LHR", "FRA", 900, ["07:00", "11:30", "15:45", "19:00"], 95)
        add_slots("LH", "LHR", "FRA", 900, ["06:30", "09:00", "13:30", "17:30"], 95)

        return table

    def get_scheduled_flight(
        self, carrier: str, origin: str, dest: str, date: datetime.date, flight_no: Optional[str] = None
    ) -> Optional[Dict]:
        """Looks up or synthesizes the scheduled departure and arrival datetime for a flight."""
        slots = self.schedules.get((carrier, origin, dest))
        if not slots:
            # Generic fallback timetable slot
            slots = [{
                "flight_no": flight_no or f"{carrier}101",
                "dep_time": time(10, 0),
                "duration_min": 180
            }]

        matched_slot = None
        if flight_no:
            for s in slots:
                if s["flight_no"] == flight_no:
                    matched_slot = s
                    break

        if not matched_slot:
            matched_slot = slots[0]

        dep_dt = datetime.combine(date, matched_slot["dep_time"])
        arr_dt = dep_dt + timedelta(minutes=matched_slot["duration_min"])

        return {
            "flight_no": matched_slot["flight_no"],
            "scheduled_dep": dep_dt,
            "scheduled_arr": arr_dt,
            "scheduled_duration_min": matched_slot["duration_min"]
        }
