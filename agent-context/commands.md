# Commands Reference

## Setup & Environment
```bash
# Install dependencies from environment/requirements.txt
pip install -r environment/requirements.txt

# Copy example environment configuration
cp environment/.env.example environment/.env
# On Windows PowerShell:
Copy-Item environment\.env.example environment\.env
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

## RTK Usage
When running commands that output large volume, prefer using RTK if applicable:
```bash
rtk <command>
```
