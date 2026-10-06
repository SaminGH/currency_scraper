# Project Map

## Overview
Automated currency scraping, validation, aggregation, and publishing pipeline for Iranian/foreign exchange rates against IRR/Toman.

## Important Directories
* `scrapers/`: Individual web scrapers for each market source (`alanchand.py`, `bonbast.py`, `navasan.py`, `tgju.py`).
* `database/`: PostgreSQL persistence layer (connection, models, queries, savepoints, atomic publishing) guided in supabase.
* `environment/`: Environment configuration (`.env.example`), Python dependencies (`requirements.txt`), and bundled ChromeDriver binary.
* `logs/`: Structured event logging utilities (`logger.py`) and log output (`pipeline.jsonl`).
* `agent-context/`: Operational agent context and knowledge files.

## Important Files & Entry Points
* `main.py`: Primary pipeline orchestrator and CLI entry point.
* `scraper_manager.py`: Hybrid asyncio + multiprocessing execution manager with timeouts, retries, and worker isolation for scrapers (asyncio for HTTP scrapers, multiprocessing for Selenium scrapers).
* `scraper_output.py`: Aggregates outputs from `scraper_manager` across all sources by currency.
* `validator.py`: Outlier detection (1% threshold) and data consistency checking.
* `price_aggregator.py`: Computes average prices, confidence metrics, and publishability flags (>= 2 valid sources).
* `change.py`: Calculates daily 24h price change percentage, delta, and 24h high/low price extremes relative to daily midnight baseline snapshots.
* `database/__init__.py`: Public API interface for database operations.
* `database/connection.py`: Reusable PostgreSQL connection provider using `psycopg2`.
* `database/publisher.py`: Atomic transaction publisher managing savepoints and final snapshot completion.
* `problem.txt`: Project backlog note stating `change.py bayad kamel eslah beshe`.

## Major Components & Relationships
```
main.py
  ├── database.get_connection() & database.create_snapshot()
  ├── scraper_output.py  ──> scraper_manager.py ──> scrapers/ (alanchand, bonbast, navasan, tgju)
  ├── validator.py       ──> filters outliers from scraper_output
  ├── price_aggregator.py──> averages validated rates & assesses confidence
  ├── change.py          ──> calculates 24h change & extremes against midnight baselines
  └── database.publish_snapshot()
        ├── save_source_health
        ├── save_source_rates
        ├── save_aggregated_rates
        ├── save_published_rates
        └── save_snapshot_summary
```

## Common Task Locations
* **Adding or updating a scraper**: `scrapers/<source_name>.py` and register in `scraper_manager.py` (`SCRAPERS` dict).
* **Validation & outlier thresholds**: `validator.py` (`OUTLIER_THRESHOLD`).
* **Aggregation & publish criteria**: `price_aggregator.py` (`publishable` logic).
* **24h change calculation logic**: `change.py`.
* **Database schema & persistence logic**: `database/*.py`.
* **Logging & telemetry**: `logs/logger.py`.
