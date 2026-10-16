## 2026-10-16T14:36:51Z
You are teamwork_preview_victory_auditor, conducting the post-victory audit for this project.
Your working directory is: c:\Users\samin\Documents\VS\project\web project_v2\linux ready\.agents\teamwork\auditor_1
The project workspace root is: c:\Users\samin\Documents\VS\project\web project_v2\linux ready
Your parent orchestrator is: 44447f96-e382-4448-9cc2-3510f333b53f

Conduct your 3-phase independent audit against the user's original task and acceptance criteria.
You MUST use send_message to report your audit verdict (CONFIRMED or REJECTED) and your structured audit report back to your parent orchestrator (44447f96-e382-4448-9cc2-3510f333b53f).
Maintain progress.md and handoff.md in your working directory.

<original_task>
This is a single self-contained fix; keep it small and focused. Migrate the currency scraping pipeline (specifically Selenium scrapers `bonbast.py` and `navasan.py`, multiprocessing worker management, and system setup) from Windows local development to run on a headless Linux VPS environment.

Working directory: c:\Users\samin\Documents\VS\project\web project_v2\linux ready
Integrity mode: demo

## Requirements

### R1. Native Linux ChromeDriver Service Configuration
Remove all hardcoded Windows ChromeDriver executable paths (`environment/chromedriver-win64/chromedriver.exe`) from `scrapers/bonbast.py` and `scrapers/navasan.py`. Instantiate `Service()` without a hardcoded path parameter to rely on the system-installed `chromium-chromedriver` from Linux system `PATH`, while supporting an optional `CHROMEDRIVER_PATH` environment variable override if specified.

### R2. Headless Linux Chrome Options & Process Safety
Ensure Chrome options in both `bonbast.py` and `navasan.py` include all required flags for a GUI-less Linux VPS environment (`--headless=new`, `--no-sandbox`, `--disable-dev-shm-usage`, `--disable-gpu`, `--blink-settings=imagesEnabled=false`). Guarantee `driver.quit()` is safely called in `finally` blocks to prevent orphaned browser processes on Linux. Do not alter BeautifulSoup parsing logic, currency targets, or data structures.

### R3. Multiprocessing & Process Tree Hygiene
Ensure multiprocessing worker isolation in `scraper_manager.py` terminates child process trees cleanly via `psutil` upon timeout or error, ensuring no zombie Chrome or ChromeDriver processes linger in Linux process tables.

### R4. Linux VPS Provisioning & Deployment Support
Provide an automated setup script (`scripts/setup_linux.sh`) for Ubuntu/Debian installing required system packages (`chromium-browser`, `chromium-chromedriver`, `python3-venv`, `libpq-dev`), and provide a production `systemd` service unit configuration (`deployment/currency-pipeline.service`) for automated daemon execution.

## Verification Resources
- Modular pipeline unit tests: `tests/test_modular_pipeline.py`
- Scraper manager hybrid execution tests: `tests/test_hybrid_scrapers2.py`

## Acceptance Criteria

### Driver & Options Configuration
- [ ] No hardcoded Windows paths (`chromedriver.exe` or `chromedriver-win64`) remain in `scrapers/bonbast.py` or `scrapers/navasan.py`.
- [ ] `Service()` is initialized dynamically without hardcoded executable path.
- [ ] Chrome options in both `bonbast.py` and `navasan.py` include `--headless=new`, `--no-sandbox`, `--disable-dev-shm-usage`, `--disable-gpu`, and `--blink-settings=imagesEnabled=false`.
- [ ] `driver.quit()` is guaranteed to execute in `finally` blocks.

### Test Suite Execution
- [ ] `python -m unittest tests/test_modular_pipeline.py` passes completely with zero errors.
- [ ] `python tests/test_hybrid_scrapers2.py` passes completely with zero regressions.

### Linux Deployment Assets
- [ ] `scripts/setup_linux.sh` exists and is formatted for Linux shell execution.
- [ ] `deployment/currency-pipeline.service` exists and contains valid systemd service directives.
- [ ] `agent-context/project-map.md`, `agent-context/commands.md`, and `agent-context/known-pitfalls.md` are updated to reflect the Linux VPS environment.
</original_task>
