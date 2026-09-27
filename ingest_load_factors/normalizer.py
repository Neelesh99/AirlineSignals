"""Code normalization utilities for carriers (IATA/ICAO) and airports."""

from typing import Dict, Optional
from config.settings import get_settings


class Normalizer:
    """Normalizes carrier and airport codes across different airline data feeds."""

    def __init__(self):
        settings = get_settings()
        self._iata_to_icao_carrier: Dict[str, str] = {}
        self._icao_to_iata_carrier: Dict[str, str] = {}
        
        for c in settings.carriers:
            code = c["code"].strip().upper()
            icao = c.get("icao", "").strip().upper()
            if code and icao:
                self._iata_to_icao_carrier[code] = icao
                self._icao_to_iata_carrier[icao] = code

        # Extra common carrier mappings
        extras = {
            "AA": "AAL", "DL": "DAL", "UA": "UAL", "WN": "SWA", "B6": "JBU",
            "AS": "ASA", "NK": "NKS", "F9": "FFT", "BA": "BAW", "LH": "DLH",
            "AF": "AFR", "KL": "KLM", "SQ": "SIA", "EK": "UAE", "QR": "QTR"
        }
        for iata, icao in extras.items():
            self._iata_to_icao_carrier.setdefault(iata, icao)
            self._icao_to_iata_carrier.setdefault(icao, iata)

        self._iata_to_icao_airport: Dict[str, str] = {}
        self._icao_to_iata_airport: Dict[str, str] = {}

        for iata, info in settings.airports.items():
            iata_code = iata.strip().upper()
            icao_code = info.get("icao", "").strip().upper()
            if iata_code and icao_code:
                self._iata_to_icao_airport[iata_code] = icao_code
                self._icao_to_iata_airport[icao_code] = iata_code

    def normalize_carrier(self, code: Optional[str], target_format: str = "IATA") -> str:
        """Normalizes carrier code to IATA (2-letter) or ICAO (3-letter)."""
        if not code:
            return "UNKNOWN"
        cleaned = code.strip().upper()
        if target_format == "IATA":
            if len(cleaned) == 2:
                return cleaned
            return self._icao_to_iata_carrier.get(cleaned, cleaned[:2])
        elif target_format == "ICAO":
            if len(cleaned) == 3:
                return cleaned
            return self._iata_to_icao_carrier.get(cleaned, cleaned)
        return cleaned

    def normalize_airport(self, code: Optional[str], target_format: str = "IATA") -> str:
        """Normalizes airport code to IATA (3-letter) or ICAO (4-letter)."""
        if not code:
            return "UNKNOWN"
        cleaned = code.strip().upper()
        if target_format == "IATA":
            if len(cleaned) == 3:
                return cleaned
            if len(cleaned) == 4 and cleaned in self._icao_to_iata_airport:
                return self._icao_to_iata_airport[cleaned]
            # US airports often have 'K' prefix in ICAO (e.g. KJFK -> JFK)
            if len(cleaned) == 4 and cleaned.startswith("K"):
                return cleaned[1:]
            return cleaned[:3]
        elif target_format == "ICAO":
            if len(cleaned) == 4:
                return cleaned
            if len(cleaned) == 3 and cleaned in self._iata_to_icao_airport:
                return self._iata_to_icao_airport[cleaned]
            if len(cleaned) == 3:
                return f"K{cleaned}"  # Common US fallback
            return cleaned
        return cleaned

    @staticmethod
    def format_quarter(year: int, quarter: Optional[int] = None, month: Optional[int] = None) -> str:
        """Formats year and quarter/month into standard 'YYYYQn'."""
        if quarter is not None:
            return f"{year}Q{quarter}"
        if month is not None:
            q = (month - 1) // 3 + 1
            return f"{year}Q{q}"
        return f"{year}Q1"
