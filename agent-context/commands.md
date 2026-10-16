# Commands Reference

## Setup & Environment

### Linux VPS Automated Setup
```bash
# Provision Ubuntu/Debian packages (Chromium, ChromeDriver, Python venv, libpq-dev)
chmod +x scripts/setup_linux.sh
./scripts/setup_linux.sh

# Activate virtual environment
source .venv/bin/activate
```

### Manual Installation
```bash
# Install dependencies from environment/requirements.txt
pip install -r environment/requirements.txt

# Copy example environment configuration
cp environment/.env.example environment/.env
# On Windows PowerShell:
Copy-Item environment\.env.example environment\.env
```

## Systemd Service Management (Linux VPS Daemon)
```bash
# Copy and enable systemd service unit
sudo cp deployment/currency-pipeline.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable currency-pipeline.service
sudo systemctl start currency-pipeline.service

# Inspect service status and logs
sudo systemctl status currency-pipeline.service
journalctl -u currency-pipeline.service -f -n 100
```

## Running the Pipeline
```bash
# Execute main pipeline (scrapes sources, aggregates, and saves to database)
python main.py
```

## Scraper Testing & Isolation
```bash
# Test individual scrapers directly:
python -c "import scrapers.alanchand as s; print(s.scrape())"
python -c "import scrapers.tgju as s; print(s.scrape())"
python -c "import scrapers.bonbast as s; print(s.scrape())"
python -c "import scrapers.navasan as s; print(s.scrape())"

# Test scraper manager execution:
python -c "import scraper_manager; print(scraper_manager.run_all())"
```

## Database Operations
```bash
# Verify database connection
python -c "import database; conn = database.get_connection(); print('Connected:', conn.status); database.close_connection()"

# Inspect active currencies and sources
python -c "import database; print('Sources:', database.get_source_ids()); print('Currencies:', database.get_currency_ids()); database.close_connection()"
```

## Test Suite Execution
```bash
# Modular pipeline unit tests (all stages, mocks, and failure isolation):
python -m unittest tests/test_modular_pipeline.py

# Scraper manager hybrid execution tests (asyncio, multiprocessing, process trees):
python tests/test_hybrid_scrapers2.py
```

## RTK Usage
When running commands that output large volume, prefer using RTK if applicable:
```bash
rtk <command>
```
