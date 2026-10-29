# Project Map

Automated currency scraping, validation, aggregation, and publishing pipeline.

## Important Directories
* `scrapers/`: Individual web scrapers for each market source (`alanchand.py`, `bonbast.py`, `navasan.py`, `tgju.py`).
* `database/`: PostgreSQL persistence layer (connection, models, queries, savepoints, atomic publishing) guided in supabase.
* `environment/`: Environment configuration (`.env.example`), Python dependencies (`requirements.txt`), and bundled ChromeDriver binary.
* `logs/`: Structured event logging utilities (`logger.py`, `log_config.py`) and log output (`pipeline.jsonl`, `public.pipeline_logs`).
* `scripts/`: Provisioning and deployment scripts (`setup_linux.sh` for Ubuntu/Debian).
* `deployment/`: Production systemd daemon units (`currency-pipeline.service`).
* `agent-context/`: Operational agent context and knowledge files.

## Important Files & Entry Points
* `main.py`: Top-level orchestrator; coordinates phases 1-3.
* `scraper_manager.py`: Runs all registered scrapers via multiprocessing and asyncio with retry and timeout logic.
* `scraper_output.py`: Formats scraper results into standard `{source: {prices, errors}}` and `{source: {status, failure_reason, currencies_received}}`.
* `validator.py`: Identifies statistical outliers using IQR/MAD and filters corrupted rates.
* `price_aggregator.py`: Computes average, min, max, spread, and publishability across valid rates.
* `confidence.py`: Deterministic confidence engine; computes HIGH/MEDIUM/LOW confidence scores and structured score breakdown per currency without machine learning or external API dependencies.
* `confidence_config.py`: Centralized configuration thresholds and rating criteria for the confidence engine.
* `change.py`: Computes 24-hour rate change and 24-hour highs/lows against the prior snapshot.
* `run_scheduler.py`: Continuous scheduler loop with jitter, health reporting, and self-healing.
* `server.py`: Unified web server and scheduler entry point for Docker/Render deployments (0.0.0.0:$PORT, GET /health).
* `database/connection.py`: Shared reusable connection manager with reconnect logic.
* `database/lookup.py`: In-memory caching for `source_id` and `currency_id` lookups.
* `database/snapshot.py`: Snapshot lifecycle management (`create_snapshot`, `complete_snapshot`).
* `database/publisher.py`: Atomic write orchestration; writes source status, rates, aggregate, and summary within a savepoint.
* `database/source_health.py`: Batch inserts into `snapshot_source_status`.
* `database/source_rates.py`: Batch inserts raw prices into `source_rates`.
* `database/aggregated_rates.py`: Batch inserts computed rates into `aggregated_rates`.
* `database/published_rates.py`: Batch inserts publishable rates into `published_rates`.
* `database/summary.py`: Inserts summary counters into `snapshot_summary`.
* `logs/logger.py`: JSONL structured logger and database event logger (`log_event`).
* `logs/log_config.py`: Centralized configuration for log targets (`json`, `db`, `both`) and file paths.

## Finding Specific Logic
* **Scraping logic per source**: `scrapers/<source_name>.py`.
* **Outlier detection logic**: `validator.py`.
* **Confidence scoring algorithm**: `confidence.py`.
* **Aggregation & publish criteria**: `price_aggregator.py` (`publishable` logic).
* **24h change calculation logic**: `change.py`.
* **Database schema & persistence logic**: `database/*.py`.
* **Logging & telemetry**: `logs/logger.py` and `logs/log_config.py`.
* **Docker container & health check**: `Dockerfile` and `server.py`.
