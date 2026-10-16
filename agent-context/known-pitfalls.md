# Known Pitfalls & Constraints

## 1. Top-Level Execution on Module Import (Resolved)
* Previously, `scraper_output.py`, `validator.py`, `price_aggregator.py`, and `main.py` executed pipeline stages immediately upon module import or had no functional entry points.
* **Resolution**: Refactored in Phase 1 into modular functional entry points (`get_scraper_output`, `validate_prices`, `aggregate_prices`, and `main.run_pipeline`) with `if __name__ == '__main__':` guards. Importing these modules now produces zero side-effects.

## 2. Browser Automation & ChromeDriver Dependency (Migrated to Linux)
* `scrapers/bonbast.py` and `scrapers/navasan.py` dynamically resolve ChromeDriver via Linux system `PATH` (e.g., `/usr/bin/chromedriver` from `chromium-chromedriver`), or through optional `CHROMEDRIVER_PATH` environment variable override. Hardcoded Windows paths have been removed. Optional `CHROME_BIN` / `CHROME_PATH` environment variables can specify custom browser binary locations.
* Headless Linux VPS execution requires mandatory flags: `--headless=new`, `--no-sandbox`, `--disable-dev-shm-usage`, `--disable-gpu`, and `--blink-settings=imagesEnabled=false`.
* `driver.quit()` must always be guarded in `finally` blocks to guarantee browser processes close even on network errors or timeouts.
* **Systemd Service Environment & User Profile Permissions**: Under service users without standard home directories (e.g., `User=www-data`), Chromium attempts to create profile data in `/nonexistent` or `/var/www`, failing with `SingletonLock` errors. Systemd unit `currency-pipeline.service` specifies `Environment="HOME=/tmp"` and `PrivateTmp=true` to grant Chromium an isolated, writable profile directory.
* Cloudflare or anti-bot challenges on target sites (e.g., bonbast) can lead to timeouts or empty tables; handled via retry isolation.

## 3. Multiprocessing on Linux & Zombie Process Prevention
* Multiprocessing scrapers run in isolated processes with dedicated queues.
* On Linux, abnormal process termination, worker timeouts, or unhandled exceptions can leave orphaned Chrome or ChromeDriver processes reparented to init or lingering as zombie `<defunct>` entries.
* **Resolution**: `scraper_manager.py` implements recursive process-tree termination (`_kill_process_tree`) via `psutil`, killing child browser processes before parent workers, reaping them with a two-pass `psutil.wait_procs()`, and guarding against self-termination (`pid == os.getpid()`).
* **Worker Process Isolation & Cleanup Timing**: The worker process itself performs a two-pass child termination and reaping in its `finally` block before exiting. To avoid a race condition where the manager's `finally` block kills a cleanly completing worker that is waiting up to 1.0s to reap child processes, the manager allows a 2.0s join window upon receiving the result before considering the worker stuck.
* In systemd deployment, `KillMode=mixed` is configured to ensure any stray child processes in the control group receive SIGKILL upon service stop or restart.

## 4. 24-Hour Change & Daily Extremes (`change.py`)
* Compares daily midnight baseline snapshots (first valid snapshot >= 00:00:00 of today vs yesterday, with fallback to latest prior snapshot).
* Computes fixed daily percentage change once per day at the first snapshot and caches in-memory (`_DAILY_CHANGE_CACHE`) to avoid repeated comparison queries and warning logs every minute.
* Mid-day restarts seamlessly fall back to fetching today's fixed daily change from today's first completed snapshot in `public.published_rates`.
* Tracks calendar-day extremes (`high_24h` and `low_24h`) dynamically per snapshot using `public.published_rates` (`s.started_at >= today_midnight and s.started_at <= current_snapshot_time`) merged with current prepared rates.
* In fresh databases or missing baseline snapshots, emits warnings once and gracefully yields `None` rather than failing.
* Formatted strings (`+0.01%`) are accepted by `save_published_rates` and converted to float before inserting into the Postgres `numeric` column.

## 5. PostgreSQL Connection Separation & Table-Based Locking
* `database/connection.py` maintains a shared global connection (`CONNECTION_REUSE = True`).
* In PostgreSQL, any failed query within a transaction puts the entire transaction in an aborted state (`current transaction is aborted, commands ignored until end of transaction block`).
* Always wrap query executions in proper exception handling with `ROLLBACK` or use savepoints as implemented in `database/publisher.py`.
* **Connection Separation**: Never hold an open database connection during the 30-60 second scraping window. Connections are closed after Phase 1 (`create_snapshot`) and reopened in Phase 3 (`calculate_change_24h` / `publish_snapshot`).
* **Table-Based State Locking**: Pipeline concurrency is governed by `public.snapshots (status = 'running')` rather than session advisory locks. Stale runs (>= 180 seconds old) auto-recover to `status = 'failed'` automatically, preventing zombie lock deadlocks across pooler dropouts.

## 6. Numeral Formatting & Localization
* Sites like `tgju.org` and `alanchand.com` render Persian numbers (`۰-۹`), Arabic numbers, Persian commas (`،`), or Latin commas in prices.
* String cleaning functions must strip currency words, replace both Persian and Arabic numerals with ASCII digits, and remove commas prior to converting to `float`.
