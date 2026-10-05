# Architecture

## Overview
The system is an end-to-end currency scraping, processing, and publishing pipeline that collects live exchange rates from multiple Iranian financial market sources, validates and removes statistical outliers, computes aggregate prices and confidence scores, calculates 24-hour rate changes, and atomically persists results into a PostgreSQL database.

## High-Level Data Flow
1. **Pipeline Initiation (`main.py`)**:
   - `logger.start_run()` generates a unique run ID.
   - Initial snapshot entry is created in `public.snapshots` with status `running`.
2. **Data Extraction (`scraper_output.py` & `scraper_manager.py`)**:
   - `scraper_manager.run_all()` launches individual scrapers in separate worker processes.
   - Scrapers extract rates and normalize numbers/currency codes.
   - Raw results are structured into a dictionary keyed by source.
3. **Data Validation (`validator.py`)**:
   - Compares prices across sources for each currency.
   - Identifies outliers exceeding `OUTLIER_THRESHOLD` (1% deviation relative to median).
   - Flags removed outlier sources and records confidence.
4. **Price Aggregation (`price_aggregator.py`)**:
   - Computes arithmetic mean of valid source rates.
   - Assigns confidence rating (`sources_used / sources_total`).
   - Determines publishability (`sources_used >= 2`).
5. **Rate Change Calculation (`change.py`)**:
   - Retrieves the most recent prior completed snapshot (>= 24 hours prior).
   - Computes percentage change: `((current - previous) / previous) * 100`.
6. **Atomic Persistence (`database/publisher.py`)**:
   - Uses a PostgreSQL savepoint (`publisher_write`) to atomically insert:
     - `public.snapshot_source_status`
     - `public.source_rates`
     - `public.aggregated_rates`
     - `public.published_rates`
     - `public.snapshot_summary`
   - Updates snapshot status (`completed`, `completed_with_warnings`, or `failed`).
   - Commits transaction or rolls back on critical error.

## Concurrency Model
* **Scraper Level**: Multiprocessing pool (`multiprocessing.Process` via `scraper_manager.py`) with `MAX_WORKERS = 4`.
* **Process Isolation**: Each scraper executes in its own OS process to insulate the main pipeline from memory leaks, unhandled driver crashes, or hung HTTP connections.
* **Timeout & Retry**: Per-source timeout (`SOURCE_TIMEOUT = 30s`) and retry logic (`MAX_RETRIES = 2`) for transient network/HTTP errors.

## External Systems & Integration Boundaries
* **Target Sources**:
  - `alanchand.com`: HTTP GET via `requests` + `BeautifulSoup` parsing.
  - `tgju.org`: HTTP GET via `requests` + `BeautifulSoup` parsing with Arabic/Persian numeral conversion.
  - `bonbast.com`: Dynamic page scraping via `selenium.webdriver.Chrome` (headless).
  - `navasan.net`: Dynamic page scraping via `selenium.webdriver.Chrome` (headless).
* **Storage**:
  - PostgreSQL database accessed through `psycopg2` using connection string in `DATABASE_URL`.
* **Telemetry**:
  - Append-only JSON Lines event logging in `logs/pipeline.jsonl`.
