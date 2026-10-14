# Architecture

## Overview
The system is an end-to-end currency scraping, processing, and publishing pipeline that collects live exchange rates from multiple Iranian financial market sources, validates and removes statistical outliers, computes aggregate prices and confidence scores, calculates 24-hour rate changes, and atomically persists results into a PostgreSQL database.

## Goal
The project goal is to run every minute in vps buy automation and fill the snapshots in the Postgresql every minute to refresh the website prices and changes every minute.

## High-Level Data Flow
1. **Phase 1: Pipeline Initiation (`main.py`)**:
   - `logger.start_run()` generates a unique run ID.
   - Checks `public.snapshots` for active `running` snapshots (skips if < 3m, auto-heals stale if >= 3m).
   - Initial snapshot entry is created in `public.snapshots` with status `running`.
   - Database connection is closed immediately so zero DB connection is open during scraping.
2. **Phase 2: Data Extraction & Processing (Connection-Free)**:
   - `scraper_manager.run_all()` launches individual scrapers in separate worker processes.
   - Scrapers extract rates and normalize numbers/currency codes.
   - Raw results are structured into a dictionary keyed by source.
   - `validator.py`: Outlier detection relative to median price.
   - `price_aggregator.py`: Computes averages and publishability flags.
   - `confidence.py`: Computes deterministic confidence ratings.
3. **Phase 3: Rate Change Calculation & Publishing (`main.py`)**:
   - Opens a fresh database connection.
   - `change.py`: Retrieves previous completed snapshot (24 hours prior) and computes changes and daily extremes.
   - Atomic Persistence (`database/publisher.py`):
     - Uses PostgreSQL savepoint (`publisher_write`) to atomically insert:
       - `public.snapshot_source_status`
       - `public.source_rates`
       - `public.aggregated_rates`
       - `public.published_rates`
       - `public.snapshot_summary`
     - Updates snapshot status (`completed`, `completed_with_warnings`, or `failed`).
     - Commits transaction or rolls back on critical error.
   - Closes database connection.

## Concurrency Model
* **Pipeline Level**: Table-based locking via `public.snapshots` (`status = 'running'`) with automatic self-healing for runs older than 180 seconds. No PostgreSQL session advisory locks are used.
* **Scraper Level**: Multiprocessing pool (`multiprocessing.Process` via `scraper_manager.py`) with `MAX_WORKERS = 4`.
* **Process Isolation**: Each scraper executes in its own OS process to insulate the main pipeline from memory leaks, unhandled driver crashes, or hung HTTP connections.
* **Timeout & Retry**: Per-source timeout (`SOURCE_TIMEOUT = 30s`) and retry logic (`MAX_RETRIES = 2`) for transient network/HTTP errors.

## External Systems & Integration Boundaries
* **Target Sources**:
  - `alanchand.com`: HTTP GET via `httpx` + `asyncio` parsing.
  - `tgju.org`: HTTP GET via `httpx` + `asyncio` parsing with Arabic/Persian numeral conversion.
  - `bonbast.com`: Dynamic page scraping via `selenium.webdriver.Chrome` (headless).
  - `navasan.net`: Dynamic page scraping via `selenium.webdriver.Chrome` (headless).
* **Storage**:
  - PostgreSQL database accessed through `psycopg2` using connection string in `DATABASE_URL`.
* **Telemetry**:
  - Append-only JSON Lines event logging in `logs/pipeline.jsonl`.
