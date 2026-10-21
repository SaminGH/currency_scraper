# Commands Reference

## Docker & Containerization (DOCKER_DEPLOYMENT_STANDARDS-V1.0.0)

### Build Docker Image
```bash
docker build -t app .
```

### Run Container Locally
```bash
docker run --rm -p 10000:10000 --env-file .env -e PORT=10000 app
```

### Verify Container Health Check
```bash
curl http://localhost:10000/health
```

### Run Server Locally without Docker
```bash
python server.py
```

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
# Install dependencies
pip install -r requirements.txt

# Copy example environment configuration
cp .env.example .env
# On Windows PowerShell:
Copy-Item .env.example .env
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
# Server health and endpoint unit tests:
python -m unittest tests/test_server.py

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
