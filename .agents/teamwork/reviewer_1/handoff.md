# Reviewer 1 Handoff Report

> [!WARNING] **Skepticism Disclaimer**
> Static code structure, boundary safety, and regression tests are verified via exhaustive static inspection; host command permissions prevented dynamic shell execution.

## 1. What the prior attempt got wrong
- **Issue 1: Premature `driver = None` on early quit exception in `scrapers/bonbast.py` & `scrapers/navasan.py`**
  - *Input*: `driver.quit()` throws an exception (e.g. `WebDriverException` or network timeout during quit) during the early browser cleanup phase.
  - *Expected*: `driver` reference remains valid so that the `finally` block can re-attempt cleanup, or process hygiene can handle the driver.
  - *Actual*: `driver = None` was executed outside the `try` block, setting `driver` to `None` even when `driver.quit()` crashed. The `finally` block saw `driver is None` and completely bypassed cleanup, leaking the Chrome/ChromeDriver process.
  - *Root Cause*: `driver = None` was positioned after the `except Exception:` block instead of inside the `try:` block.

- **Issue 2: Worker processes leaked child processes to PID 1 (`scraper_manager.py`)**
  - *Input*: Multiprocessing worker process completes or fails while ChromeDriver/Chrome child processes are still running.
  - *Expected*: Worker cleans up any spawned child processes before terminating so that no orphaned browser processes linger on Linux.
  - *Actual*: `_scraper_worker` had no `finally` cleanup block. When the worker process exited, all child processes (ChromeDriver, Chrome) were immediately reparented to init (PID 1). Because they were reparented to PID 1, the manager's `_kill_process_tree(worker_pid)` could no longer locate them via `psutil.Process(worker_pid).children()`.
  - *Root Cause*: Lack of in-worker recursive process cleanup in `_scraper_worker`.

- **Issue 3: Potential asyncio deadlock via `multiprocessing.Queue.join_thread()` in `scraper_manager.py`**
  - *Input*: A worker process times out or is forcibly terminated by `_kill_process_tree`.
  - *Expected*: The manager cleanly closes the queue without blocking the asyncio event loop.
  - *Actual*: `_run_mp_source` called `result_queue.join_thread()`. In Python's `multiprocessing.Queue`, `join_thread()` blocks until the background feeder thread flushes buffered data; if the other end of the pipe was killed, `join_thread()` can deadlock indefinitely, freezing the scheduler.
  - *Root Cause*: Calling `join_thread()` instead of `cancel_join_thread()` during error/forced termination cleanup.

- **Issue 4: Unchecked PID bounds in `_kill_process_tree` (`scraper_manager.py`)**
  - *Input*: `pid` passed as 0, 1, or non-int.
  - *Expected*: Function returns safely without emitting signals to the process group or init.
  - *Actual*: Only checked `if pid is None: return`. On Linux, signals to PID 0 or PID 1 can disrupt the entire system or cause permission faults.
  - *Root Cause*: Missing type and bounds validation (`pid <= 1`).

- **Issue 5: `CHROMEDRIVER_PATH` whitespace vulnerability in `scrapers/bonbast.py` & `scrapers/navasan.py`**
  - *Input*: `CHROMEDRIVER_PATH="   "` (spaces or tabs).
  - *Expected*: Stripped and treated as empty, falling back to dynamic `Service()` default.
  - *Actual*: Evaluated as truthy and passed as `Service(executable_path="   ")`, causing initialization failure.
  - *Root Cause*: Missing `.strip()` on environment variable retrieval.

- **Issue 6: Linux setup script lacked noninteractive apt flag, symlink fallback, and sudo permission fixing**
  - *Input*: Running `scripts/setup_linux.sh` on headless VPS or with `sudo`.
  - *Expected*: Non-interactive execution, automatic fallback symlinking for Ubuntu apt/snap ChromeDriver paths, and preserved non-root user permissions on `.venv` and `.env`.
  - *Actual*: Apt could prompt interactively; `.venv` became root-owned if run with `sudo`, breaking `User=www-data` daemon execution; and missing symlink check for `/usr/lib/chromium-browser/chromedriver`.
  - *Root Cause*: Omission of `DEBIAN_FRONTEND=noninteractive`, symlink fallback loop, and `SUDO_USER` chown check.

- **Issue 7: Systemd service unit lacked explicit `PATH` directive**
  - *Input*: Daemon startup under systemd.
  - *Expected*: Both project virtualenv binaries and standard system binaries are present in `PATH`.
  - *Actual*: Systemd default PATH omitted project `.venv/bin`.
  - *Root Cause*: Missing `Environment="PATH=..."` directive in `currency-pipeline.service`.

- **Issue 8: Missing test coverage for R1, R2, and R3 acceptance criteria**
  - *Input*: Running `python tests/test_hybrid_scrapers2.py`.
  - *Expected*: Test suite rigorously asserts dynamic `get_service()` resolution, all 5 required headless Chrome flags, and process tree termination hygiene.
  - *Actual*: `test_hybrid_scrapers.py` and `test_hybrid_scrapers2.py` only tested legacy async error mapping and contained zero tests for ChromeDriver Service, Chrome options, or `_kill_process_tree`.
  - *Root Cause*: Incomplete test coverage in prior attempt.

## 2. What I changed
- `scrapers/bonbast.py`:
  - Added `.strip()` to `CHROMEDRIVER_PATH` in `get_service()`.
  - Moved `driver = None` inside `try` block in early quit; added `driver = None` reset in `finally` block.
- `scrapers/navasan.py`:
  - Applied identical whitespace stripping to `get_service()` and safe `driver = None` placement in early quit and `finally` blocks.
- `scraper_manager.py`:
  - Added PID type and bounds check (`if pid is None or not isinstance(pid, int) or pid <= 1: return`) in `_kill_process_tree`.
  - Added `finally` cleanup block in `_scraper_worker` to terminate any child process tree before the worker exits, preventing reparenting to init (PID 1).
  - Replaced `result_queue.join_thread()` with `result_queue.cancel_join_thread()` in `_run_mp_source` to prevent feeder thread deadlocks.
- `scripts/setup_linux.sh`:
  - Added `export DEBIAN_FRONTEND=noninteractive`.
  - Added symlink fallback loop for Ubuntu apt (`/usr/lib/chromium-browser/chromedriver`) and snap locations.
  - Used `"${VENV_DIR}/bin/python" -m pip` directly for deterministic virtualenv package installation.
  - Added ownership remediation for `$SUDO_USER` on `.venv` and `.env`.
- `deployment/currency-pipeline.service`:
  - Added `Environment="PATH=/opt/currency-pipeline/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"`.
- `tests/test_hybrid_scrapers.py` & `tests/test_hybrid_scrapers2.py`:
  - Added `test_bonbast_dynamic_service()`: verifies default, override, and whitespace handling.
  - Added `test_navasan_dynamic_service()`: verifies default, override, and whitespace handling.
  - Added `test_headless_chrome_options()`: verifies all 5 required flags (`--headless=new`, `--no-sandbox`, `--disable-dev-shm-usage`, `--disable-gpu`, `--blink-settings=imagesEnabled=false`).
  - Added `test_kill_process_tree_hygiene()`: verifies boundary PIDs (None, 0, 1, invalid) and mocked process tree termination via `psutil`.
  - Updated `test_hybrid_scrapers2.py` runner to execute all new tests.
- `agent-context/known-pitfalls.md`:
  - Documented worker process `finally` child cleanup and queue deadlock prevention via `cancel_join_thread()`.

## 3. Verification Record
- **Deep Verification (ran actual tests):** None (direct terminal execution denied by host environment permissions: `Permission prompt for action 'command' was denied`).
- **Shallow Verification (manual only):**
  - Static analysis of code, functions, imports, syntax, and logic across `scrapers/bonbast.py`, `scrapers/navasan.py`, `scraper_manager.py`, `scripts/setup_linux.sh`, `deployment/currency-pipeline.service`, `tests/test_hybrid_scrapers.py`, and `tests/test_hybrid_scrapers2.py`.
  - Grep search confirmed zero occurrences of hardcoded Windows ChromeDriver executable paths (`chromedriver.exe` or `chromedriver-win64`) in `scrapers/`.
  - Verified valid systemd unit directives in `deployment/currency-pipeline.service`.
  - Verified bash syntax and POSIX safety in `scripts/setup_linux.sh`.
- **Unverified aspects:**
  - Live execution of `python -m unittest tests/test_modular_pipeline.py` and `python tests/test_hybrid_scrapers2.py` in the local terminal due to environment permissions.
  - Real execution of `scripts/setup_linux.sh` and live browser launching against target sites on a real Ubuntu/Debian VPS instance.

## 4. Known Issues
- `Shallow Verification` — Execution of live Selenium sessions and test runner commands could not be run directly due to host environment command permissions.

## 5. Remaining risk & next step
- When elevated permissions are granted or on target Linux VPS, execute:
  1. `python -m unittest tests/test_modular_pipeline.py`
  2. `python tests/test_hybrid_scrapers2.py`
  3. `chmod +x scripts/setup_linux.sh && ./scripts/setup_linux.sh`
  4. Verify systemd service daemon with `sudo systemctl status currency-pipeline.service`.
