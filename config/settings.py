"""Settings and configuration loader for Airline Route Economics Analyzer."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

CONFIG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFIG_DIR.parent
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.yaml"


class Settings:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.data: Dict[str, Any] = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @property
    def database_engine(self) -> str:
        return self.data.get("database", {}).get("engine", "duckdb")

    @property
    def database_path(self) -> Path:
        rel_path = self.data.get("database", {}).get("db_path", "data/airline_economics.duckdb")
        path = PROJECT_ROOT / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def carriers(self) -> List[Dict[str, Any]]:
        return self.data.get("carriers", [])

    @property
    def airports(self) -> Dict[str, Dict[str, Any]]:
        return self.data.get("airports", {})

    @property
    def routes(self) -> List[Dict[str, Any]]:
        return self.data.get("routes", [])

    @property
    def sectors(self) -> List[Dict[str, Any]]:
        return self.data.get("sectors", [])

    @property
    def delay_cost(self) -> Dict[str, Any]:
        return self.data.get("delay_cost", {})

    @property
    def scrape_pricing_config(self) -> Dict[str, Any]:
        return self.data.get("scrape_pricing", {})

    @property
    def opensky_config(self) -> Dict[str, Any]:
        return self.data.get("opensky", {})

    def get_route_sector(self, origin: str, dest: str) -> Optional[str]:
        for r in self.routes:
            if (r["origin"] == origin and r["dest"] == dest) or (r["origin"] == dest and r["dest"] == origin):
                return r.get("sector")
        return "Other"

    def get_route_aircraft_type(self, origin: str, dest: str) -> str:
        for r in self.routes:
            if (r["origin"] == origin and r["dest"] == dest) or (r["origin"] == dest and r["dest"] == origin):
                return r.get("aircraft_type", "Narrowbody")
        return "Narrowbody"


_settings_instance: Optional[Settings] = None


def get_settings(config_path: Optional[Path] = None) -> Settings:
    global _settings_instance
    if _settings_instance is None or config_path is not None:
        _settings_instance = Settings(config_path)
    return _settings_instance
