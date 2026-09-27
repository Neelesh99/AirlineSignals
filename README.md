# Airline Route Economics Analyzer

A modular data pipeline, cost modeling engine, and analytical tool that combines historical passenger load factors, real-world ADS-B delay telemetry, and current market airfare pricing to calculate the **"True Cost" of flying specific airline and route combinations**.

---

## Key Features

1. **Multi-Source Data Ingestion**:
   - **Load Factors**: US DOT BTS Form 41 T-100 segment data supplemented with international quarterly Investor Relations (10-Q) disclosures.
   - **Flight Delays**: Dual-path OpenSky Network telemetry — primary high-precision Trino/Impala interface and CC-BY Zenodo crowdsourced air traffic CSV dumps.
   - **Current Pricing**: Playwright-based Skyscanner search scraper with randomized jitter, user-agent rotation, stealth headers, and retry backoff.
2. **Standardized Database Schema**:
   - High-performance analytical storage in **DuckDB** (or SQLite) with indexed relational tables and joined views.
3. **A4A / DOT Delay Cost Engine**:
   - Configurable direct aircraft operating cost per minute benchmarks (Airlines for America / A4A: fuel, crew, maintenance, equipment) and US DOT / FAA Passenger Value of Time (PVOT).
4. **Three Query Granularities**:
   - **Airline-level**: Fleet-wide and carrier network comparisons.
   - **Sector-level**: Configurable corridors (e.g. US Domestic Transcon, Transatlantic, Intra-Europe).
   - **Origin-Destination (O-D) pair**: Head-to-head route competitions (e.g. JFK-LAX).
5. **Composite "True Cost Per Seat" Metric**:
   $$\text{True Cost Per Seat} = \text{Average Ticket Price} + \left(\max(0, \text{Arrival Delay Minutes}) \times \text{PVOT}\right)$$

---

## Data Source Caveats & Considerations

### 1. Historical Load Factors (BTS Form 41 / T-100 & Investor Relations)
- **Reporting Lag**: US DOT Bureau of Transportation Statistics (BTS) Form 41 T-100 segment data is subject to a statutory **90 to 120-day reporting lag**. Q1 data is generally released in June/July; Q4 data is released in late March/April of the following year. Real-time operations must extrapolate using recent historical quarters or seasonal trends.
- **Granularity & Reporting Gaps**: Non-US carriers (e.g. British Airways, Lufthansa, Singapore Airlines) do not report US domestic segments to the BTS. For international carriers, the pipeline supplements route data with quarterly investor filings (10-Q/annual decks).
- **Graceful Fallback Mechanism**: When an airline does not disclose route-specific load factors, the system flags the row with `source='BTS_SYSTEM_FALLBACK'` or `source='IR_SYSTEM_FALLBACK'` and applies the carrier's verified system-wide network average.

### 2. Delay Telemetry (OpenSky Network)
- **Primary Path (2a — Historical Trino/Impala Database)**:
  - Requires approved OpenSky Network research data access. Access requests must be submitted with an academic/institutional email (`.edu` or accredited university) under non-profit research/educational terms.
  - Grants minute-level precision state vectors across global ADS-B transponder messages. Rows are tagged with `data_source='OPENSKY_TRINO'`.
- **Fallback Path (2b — Zenodo Monthly Crowdsourced CSVs)**:
  - CC-BY licensed monthly dumps published by OpenSky on Zenodo, requiring no approval.
  - Rows are tagged with `data_source='OPENSKY_ZENODO_CSV'`.
- **Dataset Limitations & Approximations**:
  - *Timestamp Approximation*: First-seen (`firstseen`) and last-seen (`lastseen`) timestamps are used as proxies for departure and arrival. This is an explicit approximation: first/last-seen reflects when the aircraft enters or leaves the radio line-of-sight range of crowdsourced ground sensors (often climbing through 3,000+ feet or miles away), not exact gate departure/arrival or wheels-off/wheels-on (OOOI) times.
  - *Airport Matching Gaps*: Origin and destination fields are inferred from 4D flight trajectories; rows where no airport perimeter was matched have empty origin/destination fields and are skipped.
  - *Geographical Coverage Imbalance*: Sensor density is highest in Western Europe and North America. Coverage across transoceanic corridors, Africa, and parts of Asia and Latin America is sparser.

### 3. Pricing Scraper & Legal Considerations (Skyscanner)
- **Terms of Service (ToS)**:
  - Automated scraping of Skyscanner search results may breach Skyscanner's Terms of Service (specifically Section 5 regarding unauthorized automated queries).
  - *Compliant Alternative*: For commercial or production environments, register for the official **Skyscanner Travel API** (available via Skyscanner Partners portal or RapidAPI), which provides authenticated, rate-guaranteed JSON feeds.
- **Scraper Anti-Detection Controls**:
  - Headless Chromium execution with `navigator.webdriver` concealment.
  - Randomized request delays / jitter (1.5s – 4.0s).
  - Rotating User-Agent pool across modern desktop browsers.
  - Exponential backoff retry logic and gap logging (`failed_lookups`).
  - Calibrated market-yield price generator fallback when bot challenges or offline test environments occur.

---

## Delay Cost Model Assumptions

Calculations follow published aviation economic benchmarks:
- **Airlines for America (A4A)**:
  - Base Direct Aircraft Operating Cost: **\$85.50 / minute** (Narrowbody baseline)
  - Direct cost components: Fuel (\$35.20/min), Crew (\$26.80/min), Maintenance (\$15.10/min), Aircraft Ownership (\$8.40/min).
- **US DOT / FAA Guidance**:
  - Passenger Value of Time (PVOT): **\$0.783 / minute** (~**\$47.00 / hour** per passenger).
- **Aircraft Category Multipliers**:
  - **Regional** (e.g. CRJ, E175, ~76 seats): `0.70x` multiplier
  - **Narrowbody** (e.g. A320, B737, ~162 seats): `1.00x` multiplier
  - **Widebody** (e.g. A350, B777, B787, ~285 seats): `1.65x` multiplier

---

## Database Architecture

Data is stored locally in DuckDB (`data/airline_economics.duckdb`):

| Table | Primary Key | Description |
|---|---|---|
| `routes` | `(origin, dest)` | Origin, destination, sector, distance, aircraft type |
| `carriers` | `(code)` | Carrier code, ICAO, full name, country, baseline LF |
| `load_factors` | `(carrier, origin, dest, quarter)` | Carrier, route, quarter, ASM, RPM, load factor, source |
| `delay_stats` | `(carrier, origin, dest, date, flight_no)` | Flight times, departure & arrival delays, data source |
| `delay_costs` | `(carrier, origin, dest, date, flight_no)` | Airline operating delay cost, passenger delay cost, total cost |
| `pricing` | `(carrier, origin, dest, travel_date, cabin_class, stops)` | Price, cabin class, stops, search date |

---

## Installation & Setup

1. **Activate Environment & Install Requirements**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Verify Configuration**:
   Inspect or customize parameters in `config/config.yaml` (routes, carrier list, cost multipliers, delay providers).

---

## Usage Guide

### 1. Run Complete Pipeline or Individual Stages
```bash
# Run full pipeline (Load factors, Zenodo delays, Cost model, Pricing)
python cli.py ingest --stage all --provider zenodo

# Run individual stages
python cli.py ingest --stage load_factors
python cli.py ingest --stage delays --provider zenodo
python cli.py ingest --stage delay_costs
python cli.py ingest --stage pricing
```

### 2. Query Analysis Interface

#### Granularity 1: Airline-Level Comparison
```bash
# Compare all carriers
python cli.py analyze-airline --plot

# Filter to a specific carrier
python cli.py analyze-airline --carrier DL --quarter 2024Q3
```

#### Granularity 2: Sector-Level Analysis
```bash
# Compare carriers across all sectors
python cli.py analyze-sector

# Filter to a specific sector
python cli.py analyze-sector --sector "US Domestic Transcon" --plot
python cli.py analyze-sector --sector "Transatlantic"
```

#### Granularity 3: Individual Origin-Destination Route
```bash
# Evaluate head-to-head carrier economics on JFK -> LAX
python cli.py analyze-route JFK LAX --plot --csv reports/jfk_lax.csv
```

### 3. Run End-to-End Demo
```bash
python cli.py demo
```

### 4. Run Test Suite
```bash
pytest -v
```

---

## Project Structure

```
AirlineSignals/
├── config/
│   ├── config.yaml               # Carriers, routes, sectors, cost parameters
│   └── settings.py               # YAML configuration loader
├── database/
│   └── db_manager.py             # DuckDB connection manager & DDL migrations
├── ingest_load_factors/
│   ├── normalizer.py             # IATA/ICAO and airport normalizer
│   ├── bts_t100_parser.py        # BTS Form 41 T-100 parser
│   ├── investor_relations.py     # International carrier quarterly disclosures
│   └── load_factor_service.py    # Fallback to system-wide averages
├── ingest_delays/
│   ├── schedule_reference.py     # Timetable reference matcher
│   ├── opensky_trino.py          # 2a Primary Trino historical client
│   ├── opensky_zenodo.py         # 2b Fallback Zenodo monthly CSV parser
│   └── delay_service.py          # Unified schema delay orchestrator
├── estimate_delay_cost/
│   ├── cost_model.py             # A4A & DOT delay cost calculation engine
│   └── delay_cost_service.py     # Flight, route, and carrier aggregations
├── scrape_pricing/
│   ├── user_agents.py            # User-agent pool and stealth headers
│   ├── skyscanner_scraper.py     # Playwright scraper with retry and jitter
│   └── pricing_service.py        # Route price collection & fallback
├── analysis/
│   ├── metrics.py                # Composite true cost calculations
│   ├── query_service.py          # Airline, sector, and route queries
│   └── visualizer.py             # Matplotlib charts & terminal tables
├── tests/                        # 20 comprehensive unit and integration tests
├── pipeline.py                   # Top-level orchestrator
├── cli.py                        # Click-based command-line interface
├── requirements.txt              # Dependency specifications
└── README.md                     # Comprehensive documentation
```
