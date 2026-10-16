# Dispatch Log

## 2026-10-16T13:50:24Z
From: 4186e053-dc4f-4352-b2b3-c57bdb7aac47 (parent)
Role: teamwork_preview_swe_1 (SWE Light orchestrator)
Working directory: c:\Users\samin\Documents\VS\project\web project_v2\linux ready\.agents\teamwork\swe_1

Task:
Migrate the currency scraping pipeline (specifically Selenium scrapers bonbast.py and navasan.py, multiprocessing worker management, and system setup) from Windows local development to run on a headless Linux VPS environment.

Requirements:
- R1. Native Linux ChromeDriver Service Configuration: Remove hardcoded Windows paths (environment/chromedriver-win64/chromedriver.exe) from scrapers/bonbast.py and scrapers/navasan.py. Instantiate Service() without a hardcoded path parameter to rely on system-installed chromium-chromedriver from Linux system PATH, while supporting optional CHROMEDRIVER_PATH env var.
- R2. Headless Linux Chrome Options & Process Safety: Chrome options in both bonbast.py and navasan.py must include --headless=new, --no-sandbox, --disable-dev-shm-usage, --disable-gpu, --blink-settings=imagesEnabled=false. Guarantee driver.quit() in finally blocks. Do not alter BeautifulSoup parsing logic, currency targets, or data structures.
- R3. Multiprocessing & Process Tree Hygiene: Ensure multiprocessing worker isolation in scraper_manager.py terminates child process trees cleanly via psutil upon timeout or error.
- R4. Linux VPS Provisioning & Deployment Support: Provide scripts/setup_linux.sh for Ubuntu/Debian installing chromium-browser, chromium-chromedriver, python3-venv, libpq-dev. Provide deployment/currency-pipeline.service for systemd daemon execution.
- Verification: Tests tests/test_modular_pipeline.py and tests/test_hybrid_scrapers2.py must pass.
- Documentation: Update agent-context/project-map.md, agent-context/commands.md, and agent-context/known-pitfalls.md.
