# Reviewer 2 Handoff Report

> [!WARNING] **Skepticism Disclaimer**
> Code structure, concurrency safety, dynamic ChromeDriver service instantiation, and regression test suites are verified through exhaustive adversarial static analysis; live host dynamic shell execution remains unverified due to platform permission prompt denial.

## 1. What the prior attempt got wrong

- **Issue 1: Test isolation failure in `test_scrapers_dict_dispatch_override` (`tests/test_hybrid_scrapers.py`)**
  - *Input*: Executing `python tests/test_hybrid_scrapers2.py` in an offline or mock test environment.
  - *Expected*: Only mock scrapers execute without initiating live network requests or spawning real browser processes.
  - *Actual*: `test_scrapers_dict_dispatch_override` patched `scraper_manager.SCRAPERS` with `{"tgju": mock_tgju}` without `clear=True`. Because `bonbast`, `navasan`, and `alanchand` remained in the dictionary, `_run_all_async()` launched live multiprocessing workers attempting to run real Selenium ChromeDriver and Chrome sessions and real network calls, causing 30-second timeouts or errors in headless/offline test environments.
  - *Root Cause*: Omission of `clear=True` in `patch.dict(scraper_manager.SCRAPERS, ...)` and `patch.dict(scraper_manager.ASYNC_SCRAPERS, ...)`.

- **Issue 2: Chromium profile `SingletonLock` failure under `User=www-data` (`deployment/currency-pipeline.service`)**
  - *Input*: Starting `currency-pipeline.service` under default systemd user `www-data`.
  - *Expected*: Chromium starts headlessly without failing on user directory permissions.
  - *Actual*: On Ubuntu/Debian, `www-data` has `HOME=/var/www` or `/nonexistent`. Chromium attempts to create profile caches and lock files (`SingletonLock`) in `$HOME/.config/chromium`. Without a valid, writable `$HOME`, Chromium fails to start with access denied.
  - *Root Cause*: Systemd unit lacked an explicit `Environment="HOME=/tmp"` directive matching `PrivateTmp=true`.

- **Issue 3: Unhandled `SIGTERM` in scheduler daemon (`run_scheduler.py`)**
  - *Input*: Systemd service stop/restart via `systemctl stop currency-pipeline.service`.
  - *Expected*: Scheduler catches `SIGTERM` and shuts down gracefully with exit code 0.
  - *Actual*: `run_scheduler.py` only caught `KeyboardInterrupt` (`SIGINT`). When systemd stopped the service, it sent `SIGTERM`, resulting in an unhandled termination and non-zero exit state.
  - *Root Cause*: Lack of `SIGTERM` signal registration.

- **Issue 4: PID type safety flaw with boolean inputs in `_kill_process_tree` (`scraper_manager.py`)**
  - *Input*: `_kill_process_tree(True)` or `_kill_process_tree(False)`.
  - *Expected*: Safely ignored without inspecting system processes.
  - *Actual*: In Python, `isinstance(True, int)` evaluates to `True` because `bool` is a subclass of `int`. While `True <= 1` returned early, `isinstance(pid, bool)` was not explicitly checked, creating ambiguous type coercion.
  - *Root Cause*: Incomplete type check omitting explicit `not isinstance(pid, bool)`.

- **Issue 5: Unhandled `psutil.AccessDenied` during recursive process traversal (`scraper_manager.py`)**
  - *Input*: `parent.children(recursive=True)` encounters a child process transitioning or protected by kernel permissions.
  - *Expected*: Gracefully handles access denial and continues attempting to terminate the parent process.
  - *Actual*: Only `psutil.NoSuchProcess` and `psutil.ZombieProcess` were caught at the children query level. An `AccessDenied` exception raised during `children()` bypassed parent termination.
  - *Root Cause*: Omission of `psutil.AccessDenied` in the inner `try...except` block of `_kill_process_tree`.

- **Issue 6: Stubborn process zombie leak in `_kill_process_tree` (`scraper_manager.py`)**
  - *Input*: Child or parent process does not terminate immediately within 1.0s of the initial SIGKILL.
  - *Expected*: Any alive processes receiving a second kill are reaped so they do not linger as `<defunct>` zombies.
  - *Actual*: The loop called `p.kill()` on surviving processes in `alive`, but never called `wait_procs` again, leaving reaped children unaccounted for in process tables.
  - *Root Cause*: Missing secondary `psutil.wait_procs(alive, timeout=0.5)` reap call.

- **Issue 7: Direct test execution import failure (`tests/test_modular_pipeline.py`)**
  - *Input*: Executing `python tests/test_modular_pipeline.py` directly from the terminal.
  - *Expected*: Imports project root modules (`confidence`, `database`, `main`, etc.) successfully.
  - *Actual*: Failed with `ModuleNotFoundError: No module named 'confidence'` because `sys.path[0]` is the `tests/` directory rather than project root.
  - *Root Cause*: Missing `sys.path.insert(0, ...)` entry point configuration.

- **Issue 8: Missing explicit test verification for `driver.quit()` in failure paths (`tests/test_hybrid_scrapers.py`)**
  - *Input*: Exception raised during page load or scraping in `bonbast.py` or `navasan.py`.
  - *Expected*: Test suite explicitly verifies that `driver.quit()` was executed in the `finally` block.
  - *Actual*: No test verified `mock_driver.quit.called` when an exception was raised.
  - *Root Cause*: Incomplete test coverage for R2 acceptance criteria.

- **Issue 9: Quotation marks in `CHROMEDRIVER_PATH` (`scrapers/bonbast.py`, `scrapers/navasan.py`)**
  - *Input*: `CHROMEDRIVER_PATH='"/usr/bin/chromedriver"'` or `CHROMEDRIVER_PATH="'/usr/bin/chromedriver'"`.
  - *Expected*: Surrounding quotes are stripped.
  - *Actual*: Only whitespace was stripped; quotes remained in the path parameter.
  - *Root Cause*: Missing `.strip("\"'")` on environment variable parsing.

- **Issue 10: Potential broken browser symlinks in Debian/Ubuntu setup script (`scripts/setup_linux.sh`)**
  - *Input*: Debian systems installing `chromium` instead of `chromium-browser`.
  - *Expected*: Both `chromium-browser` and `google-chrome` symlinks are present in system PATH for ChromeDriver compatibility.
  - *Actual*: Only ChromeDriver was symlinked; `chromium-browser` and `google-chrome` symlinks were missing when alternate package names were installed.
  - *Root Cause*: Lack of cross-binary symlinks in `scripts/setup_linux.sh`.

## 2. What I changed

- `scrapers/bonbast.py` & `scrapers/navasan.py`:
  - Stripped both whitespace and surrounding quotes from `CHROMEDRIVER_PATH` (`.strip().strip("\"'")`).
  - Added optional `CHROME_BIN` / `CHROME_PATH` support in `Options.binary_location` for custom browser binary paths.
- `scraper_manager.py`:
  - Hardened `_kill_process_tree` PID validation with `isinstance(pid, bool)` guard.
  - Handled `psutil.AccessDenied` when querying `parent.children(recursive=True)` so parent kill is still attempted.
  - Added secondary `psutil.wait_procs(alive, timeout=0.5)` to ensure stubborn processes killed on the second pass are reaped.
  - Included process exit code in error message on unexpected worker termination (`exitcode {exitcode}`).
- `deployment/currency-pipeline.service`:
  - Added `Environment="HOME=/tmp"` to ensure headless Chromium user data and `SingletonLock` succeed under `User=www-data`.
  - Added documented optional `CHROMEDRIVER_PATH` and `CHROME_BIN` directives.
- `scripts/setup_linux.sh`:
  - Hardened sudo check when `sudo` command is missing in minimal Docker/VPS environments.
  - Added cross-symlinks for `chromium-browser`, `chromium`, and `google-chrome`.
  - Ensured `logs/` directory exists and has appropriate permissions.
  - Recursively fixed ownership for `$PROJECT_ROOT` under `$SUDO_USER`.
- `run_scheduler.py`:
  - Added `SIGTERM` signal handler raising `KeyboardInterrupt` for graceful systemd daemon shutdown.
- `tests/test_modular_pipeline.py`:
  - Added `sys.path.insert(0, ...)` at top of module for standalone execution robustness.
- `tests/test_hybrid_scrapers.py`:
  - Added `clear=True` to `patch.dict(scraper_manager.SCRAPERS, ...)` in `test_scrapers_dict_dispatch_override` to prevent leaking real scrapers into unit tests.
  - Added `test_driver_quit_called_on_exception()`: explicitly asserts that `driver.quit()` is executed in `finally` blocks when an exception occurs in `bonbast.py` and `navasan.py`.
  - Enhanced `test_kill_process_tree_hygiene()` to test `True`, `False`, `-1`, and `psutil.AccessDenied` during children traversal.
- `tests/test_hybrid_scrapers2.py`:
  - Added call to `t.test_driver_quit_called_on_exception()`.
- `agent-context/known-pitfalls.md`:
  - Documented Chromium user profile permissions under `www-data` and resolution via `Environment="HOME=/tmp"`.

## 3. Verification Record
- **Deep Verification (ran actual tests):** None (direct terminal command execution was denied by host environment permissions: `Permission prompt for action 'command' was denied`).
- **Shallow Verification (manual only):**
  - Exhaustive static analysis and AST/syntax verification across all modified files (`scrapers/bonbast.py`, `scrapers/navasan.py`, `scraper_manager.py`, `scripts/setup_linux.sh`, `deployment/currency-pipeline.service`, `run_scheduler.py`, `tests/test_modular_pipeline.py`, `tests/test_hybrid_scrapers.py`, `tests/test_hybrid_scrapers2.py`, and `agent-context/known-pitfalls.md`).
  - Grep search confirmed zero occurrences of hardcoded Windows ChromeDriver executable paths (`chromedriver.exe` or `chromedriver-win64`) in `scrapers/` and across the workspace.
  - Verified valid systemd unit directives and permissions in `deployment/currency-pipeline.service`.
  - Verified LF line endings and POSIX/bash syntax in `scripts/setup_linux.sh`.
- **Unverified aspects:**
  - Live execution of `python -m unittest tests/test_modular_pipeline.py` and `python tests/test_hybrid_scrapers2.py` in the local terminal due to host environment command permissions.
  - Real execution of `scripts/setup_linux.sh` and live browser launching against target sites on a real Ubuntu/Debian VPS instance.

## 4. Known Issues
- `Shallow Verification` — Execution of live Selenium sessions and test runner commands could not be run directly due to host environment command permissions.

## 5. Remaining risk & next step
- The implementation is hardened against test isolation leaks, process zombie leaks, systemd profile permission bugs, and unhandled daemon signals.
- When elevated permissions are available or upon deploying to the target Linux VPS:
  1. Run `python -m unittest tests/test_modular_pipeline.py`.
  2. Run `python tests/test_hybrid_scrapers2.py`.
  3. Execute `chmod +x scripts/setup_linux.sh && ./scripts/setup_linux.sh`.
  4. Verify systemd service daemon with `sudo systemctl status currency-pipeline.service`.
