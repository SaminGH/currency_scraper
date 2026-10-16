# Project Map

## Overview
Automated currency scraping, validation, aggregation, and publishing pipeline for Iranian/foreign exchange rates against IRR/Toman.

## Important Directories
* `scrapers/`: Individual web scrapers for each market source (`alanchand.py`, `bonbast.py`, `navasan.py`, `tgju.py`).
* `database/`: PostgreSQL persistence layer (connection, models, queries, savepoints, atomic publishing) guided in supabase.
* `environment/`: Environment configuration (`.env.example`) and Python dependencies (`requirements.txt`).
* `logs/`: Structured event logging utilities (`logger.py`) and log output (`pipeline.jsonl`).
* `scripts/`: Provisioning and deployment scripts (`setup_linux.sh` for Ubuntu/Debian).
* `deployment/`: Production systemd daemon units (`currency-pipeline.service`).
* `agent-context/`: Operational agent context and knowledge files.

## Important Files & Entry Points
* `main.py`: Primary pipeline orchestrator and CLI entry point.
* `scraper_manager.py`: Hybrid asyncio + multiprocessing execution manager with timeouts, retries, and worker isolation for scrapers (asyncio for HTTP scrapers, multiprocessing for Selenium scrapers).
* `scraper_output.py`: Aggregates outputs from `scraper_manager` across all sources by currency.
* `validator.py`: Outlier detection (1% threshold) and data consistency checking.
* `confidence_config.py`: Centralized configuration for confidence score thresholds (source count, dispersion, freshness).
* `confidence.py`: Dedicated deterministic confidence score engine calculating quality ratings ("HIGH", "MEDIUM", "LOW").
* `price_aggregator.py`: Computes average prices, confidence metrics, and publishability flags (>= 2 valid sources).
* `change.py`: Modular daily change and range engine (`calculate_daily_change`, `calculate_daily_high_low`, and `calculate_daily_change_and_range` / `calculate_change_24h`) with in-memory carry-forward caching, mid-day DB recovery, and calendar-day high/low extremes.
* `database/__init__.py`: Public API interface for database operations.
* `database/connection.py`: Reusable PostgreSQL connection provider using `psycopg2`.
* `database/publisher.py`: Atomic transaction publisher managing savepoints and final snapshot completion.

## Major Components & Relationships
```
main.py
  ├── database.get_connection() & database.create_snapshot()
  ├── scraper_output.py  ──> scraper_manager.py ──> scrapers/ (alanchand, bonbast, navasan, tgju)
  ├── validator.py       ──> filters outliers from scraper_output
  ├── price_aggregator.py──> averages validated rates
  ├── confidence.py      ──> calculates deterministic confidence ("HIGH", "MEDIUM", "LOW")
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
* **Confidence scoring & dispersion thresholds**: `confidence_config.py` and `confidence.py`.
* **Aggregation & publish criteria**: `price_aggregator.py` (`publishable` logic).
* **24h change calculation logic**: `change.py`.
* **Database schema & persistence logic**: `database/*.py`.
* **Logging & telemetry**: `logs/logger.py`.
