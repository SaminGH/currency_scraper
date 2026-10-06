# Known Pitfalls & Constraints

## 1. Top-Level Execution on Module Import
* `scraper_output.py`, `validator.py`, and `price_aggregator.py` execute pipeline stages immediately upon module import.
* **Impact**: Simply importing `scraper_output` triggers `scraper_manager.run_all()` and launches live browser/network scrapers.
* **Caution**: Unit tests or ad-hoc scripts should be careful when importing these modules directly.

## 2. Browser Automation & ChromeDriver Dependency
* `scrapers/bonbast.py` and `scrapers/navasan.py` depend on the bundled binary at `environment/chromedriver-win64/chromedriver.exe`.
* The ChromeDriver version must remain compatible with the installed host Google Chrome browser.
* Headless mode and anti-bot/Cloudflare challenges on target sites (e.g., bonbast) can lead to timeouts or empty tables.

## 3. Multiprocessing on Windows
* Python on Windows uses the `spawn` start method rather than `fork`.
* Any sub-processes spawned by `multiprocessing` must import top-level code cleanly. Guard conditions (`if __name__ == '__main__':`) or isolated worker functions are essential to avoid infinite recursion or unexpected side-effects.

## 4. 24-Hour Change Calculation (`change.py`)
* Refactored to compare daily midnight baseline snapshots (first valid snapshot >= 00:00:00 of today vs yesterday) rather than rigid rolling 24h timestamps.
* Tracks 24-hour extremes (`high_24h` and `low_24h`) using `public.published_rates` across the baseline window.
* In fresh databases or missing baseline snapshots, emits warnings and gracefully yields `None` rather than failing.
* Formatted strings (`+0.01%`) are accepted by `save_published_rates` and converted to float before inserting into the Postgres `numeric` column.

## 5. PostgreSQL Global Connection & Transaction States
* `database/connection.py` maintains a shared global connection (`CONNECTION_REUSE = True`).
* In PostgreSQL, any failed query within a transaction puts the entire transaction in an aborted state (`current transaction is aborted, commands ignored until end of transaction block`).
* Always wrap query executions in proper exception handling with `ROLLBACK` or use savepoints as implemented in `database/publisher.py`.

## 6. Numeral Formatting & Localization
* Sites like `tgju.org` and `alanchand.com` render Persian numbers (`۰-۹`), Arabic numbers, Persian commas (`،`), or Latin commas in prices.
* String cleaning functions must strip currency words, replace both Persian and Arabic numerals with ASCII digits, and remove commas prior to converting to `float`.
