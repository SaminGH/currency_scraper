# ==============================================================================
# Dockerfile — Production Container for Currency Scraping & Aggregation Pipeline
# Standard: DOCKER_DEPLOYMENT_STANDARDS-V1.0.0
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered standard I/O
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=10000 \
    PIPELINE_INTERVAL_SECONDS=60 \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    CHROME_BIN=/usr/bin/chromium

# Set working directory
WORKDIR /app

# Install system dependencies:
# - chromium & chromium-driver: Headless browser automation for Selenium scrapers
# - libpq-dev & ca-certificates: PostgreSQL client libraries and trusted TLS certs
# - curl: Container health monitoring
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    libpq-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency requirements first to leverage Docker layer caching
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure persistent log directory exists
RUN mkdir -p logs

# Expose the mandatory application port (Render standard: 10000)
EXPOSE 10000

# Container healthcheck testing the GET /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-10000}/health || exit 1

# Start unified web server and scheduler entrypoint
CMD ["python", "server.py"]
