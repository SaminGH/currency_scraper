# Known Pitfalls & Constraints

## 1. Top-Level Execution on Module Import (Resolved)
* Previously, `scraper_output.py`, `validator.py`, `price_aggregator.py`, and `main.py` executed pipeline stages immediately upon module import or had no functional entry points.
* **Resolution**: Refactored in Phase 1 into modular functional entry points (`get_scraper_output`, `validate_prices`, `aggregate_prices`, and `main.run_pipeline`) with `if __name__ == '__main__':` guards. Importing these modules now produces zero side-effects.

## 2. Browser Automation & ChromeDriver Dependency
* `scrapers/bonbast.py` and `scrapers/navasan.py` depend on the bundled binary at `environment/chromedriver-win64/chromedriver.exe`.
* The ChromeDriver version must remain compatible with the installed host Google Chrome browser.
* Headless mode and anti-bot/Cloudflare challenges on target sites (e.g., bonbast) can lead to timeouts or empty tables.

## 3. Multiprocessing on Windows
* Python on Windows uses the `spawn` start method rather than `fork`.
* Any sub-processes spawned by `multiprocessing` must import top-level code cleanly. Guard conditions (`if __name__ == '__main__':`) or isolated worker functions are essential to avoid infinite recursion or unexpected side-effects.

## 4. 24-Hour Change & Daily Extremes (`change.py`)
* Compares daily midnight baseline snapshots (first valid snapshot >= 00:00:00 of today vs yesterday, with fallback to latest prior snapshot).
* Computes fixed daily percentage change once per day at the first snapshot and caches in-memory (`_DAILY_CHANGE_CACHE`) to avoid repeated comparison queries and warning logs every minute.
* Mid-day restarts seamlessly fall back to fetching today's fixed daily change from today's first completed snapshot in `public.published_rates`.
* Tracks calendar-day extremes (`high_24h` and `low_24h`) dynamically per snapshot using `public.published_rates` (`s.started_at >= today_midnight and s.started_at <= current_snapshot_time`) merged with current prepared rates.
* In fresh databases or missing baseline snapshots, emits warnings once and gracefully yields `None` rather than failing.
* Formatted strings (`+0.01%`) are accepted by `save_published_rates` and converted to float before inserting into the Postgres `numeric` column.

## 5. PostgreSQL Global Connection & Transaction States
* `database/connection.py` maintains a shared global connection (`CONNECTION_REUSE = True`).
* In PostgreSQL, any failed query within a transaction puts the entire transaction in an aborted state (`current transaction is aborted, commands ignored until end of transaction block`).
* Always wrap query executions in proper exception handling with `ROLLBACK` or use savepoints as implemented in `database/publisher.py`.

## 6. Numeral Formatting & Localization
* Sites like `tgju.org` and `alanchand.com` render Persian numbers (`۰-۹`), Arabic numbers, Persian commas (`،`), or Latin commas in prices.
* String cleaning functions must strip currency words, replace both Persian and Arabic numerals with ASCII digits, and remove commas prior to converting to `float`.
