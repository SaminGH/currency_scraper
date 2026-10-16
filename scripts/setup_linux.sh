#!/usr/bin/env bash
# ==============================================================================
# scripts/setup_linux.sh
# Automated provisioning script for Ubuntu/Debian Linux VPS
# Installs Chromium, ChromeDriver, Python venv, libpq-dev, and dependencies.
# ==============================================================================

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "===================================================================="
echo "🚀 Starting Linux VPS Environment Setup for Currency Scraping Pipeline"
echo "===================================================================="

# Ensure script is executed with root/sudo privileges for package installation
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo &> /dev/null; then
        echo "⚠️  This script requires administrative privileges for package installation."
        echo "   Attempting to elevate with sudo..."
        SUDO="sudo"
    else
        echo "⚠️  Running as non-root and sudo is not installed; attempting direct execution..."
        SUDO=""
    fi
else
    SUDO=""
fi

# Determine project directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "📂 Project root detected at: ${PROJECT_ROOT}"

# 1. Update package lists
echo "📦 Updating apt package repositories..."
$SUDO apt-get update -y

# 2. Install required system packages
echo "📦 Installing required system packages (chromium-browser, chromium-chromedriver, python3-venv, libpq-dev)..."
$SUDO apt-get install -y --no-install-recommends \
    chromium-browser \
    chromium-chromedriver \
    python3 \
    python3-venv \
    python3-pip \
    libpq-dev \
    curl \
    ca-certificates || {
        echo "ℹ️  Testing alternate chromium package names for Debian/newer Ubuntu distros..."
        $SUDO apt-get install -y --no-install-recommends \
            chromium \
            chromium-driver \
            python3 \
            python3-venv \
            python3-pip \
            libpq-dev \
            curl \
            ca-certificates || true
    }

# 3. Verify ChromeDriver & Chromium availability
echo "🔍 Verifying ChromeDriver installation..."
$SUDO mkdir -p /usr/local/bin

if ! command -v chromedriver &> /dev/null; then
    for cand in /usr/lib/chromium-browser/chromedriver /usr/lib/chromium/chromedriver /snap/bin/chromium.chromedriver; do
        if [ -f "$cand" ] || [ -x "$cand" ]; then
            echo "🔗 Linking ${cand} -> /usr/local/bin/chromedriver..."
            $SUDO ln -sf "$cand" /usr/local/bin/chromedriver
            break
        fi
    done
fi

if command -v chromedriver &> /dev/null; then
    CHROMEDRIVER_BIN="$(command -v chromedriver)"
    echo "  ✅ ChromeDriver found at: ${CHROMEDRIVER_BIN}"
    "${CHROMEDRIVER_BIN}" --version || true
else
    echo "  ⚠️ Warning: chromedriver not found in default PATH. You may need to set CHROMEDRIVER_PATH."
fi

if ! command -v chromium-browser &> /dev/null && command -v chromium &> /dev/null; then
    echo "🔗 Linking $(command -v chromium) -> /usr/local/bin/chromium-browser..."
    $SUDO ln -sf "$(command -v chromium)" /usr/local/bin/chromium-browser || true
fi

if ! command -v chromium &> /dev/null && command -v chromium-browser &> /dev/null; then
    echo "🔗 Linking $(command -v chromium-browser) -> /usr/local/bin/chromium..."
    $SUDO ln -sf "$(command -v chromium-browser)" /usr/local/bin/chromium || true
fi

if ! command -v google-chrome &> /dev/null; then
    TARGET_CHROME="$(command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null || true)"
    if [ -n "$TARGET_CHROME" ]; then
        echo "🔗 Linking ${TARGET_CHROME} -> /usr/local/bin/google-chrome..."
        $SUDO ln -sf "$TARGET_CHROME" /usr/local/bin/google-chrome || true
    fi
fi

if command -v chromium-browser &> /dev/null; then
    echo "  ✅ Chromium found at: $(command -v chromium-browser)"
elif command -v chromium &> /dev/null; then
    echo "  ✅ Chromium found at: $(command -v chromium)"
fi

# 4. Set up Python virtual environment
cd "${PROJECT_ROOT}"

VENV_DIR="${PROJECT_ROOT}/.venv"
if [ ! -d "${VENV_DIR}" ]; then
    echo "🐍 Creating Python virtual environment at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
else
    echo "🐍 Existing virtual environment detected at ${VENV_DIR}."
fi

echo "🔄 Installing dependencies in virtual environment..."
"${VENV_DIR}/bin/python" -m pip install --upgrade pip

if [ -f "environment/requirements.txt" ]; then
    echo "📦 Installing Python requirements from environment/requirements.txt..."
    "${VENV_DIR}/bin/python" -m pip install -r environment/requirements.txt
else
    echo "⚠️  environment/requirements.txt not found!"
fi

# 5. Environment configuration (.env)
if [ ! -f "environment/.env" ] && [ -f "environment/.env.example" ]; then
    echo "⚙️ Creating environment/.env from environment/.env.example..."
    cp environment/.env.example environment/.env
    echo "   Remember to edit environment/.env with your production DATABASE_URL."
fi

# Ensure logs directory exists
mkdir -p "${PROJECT_ROOT}/logs"
chmod 777 "${PROJECT_ROOT}/logs" 2>/dev/null || true

# Fix ownership if script was run under sudo
if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    chown -R "${SUDO_USER}:${SUDO_USER}" "${PROJECT_ROOT}" 2>/dev/null || true
fi

# 6. Verify pipeline imports
echo "🧪 Testing module imports inside virtual environment..."
"${VENV_DIR}/bin/python" -c "import scrapers.bonbast, scrapers.navasan, scraper_manager; print('✅ Modules imported successfully!')"

echo "===================================================================="
echo "✅ Linux VPS environment setup completed successfully!"
echo "   Virtualenv: ${VENV_DIR}"
echo "   Note: Verify WorkingDirectory in deployment/currency-pipeline.service matches ${PROJECT_ROOT}"
echo "   To start the pipeline daemon: systemctl start currency-pipeline.service"
echo "===================================================================="
