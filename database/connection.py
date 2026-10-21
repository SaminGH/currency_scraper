import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

import logs.logger as logger

BASE_DIR = Path(__file__).resolve().parent.parent

# Check root .env first (standard for Docker / 12-factor apps), fallback to environment/.env
ROOT_ENV = BASE_DIR / ".env"
ENV_FILE = ROOT_ENV if ROOT_ENV.exists() else (BASE_DIR / "environment" / ".env")

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

# Shared PostgreSQL connection reused across database operations.
_connection = None
CONNECTION_REUSE = True


def get_connection():
    """
    Create and return a PostgreSQL connection.

    Reuses the existing connection when it is still open.
    Creates a new connection only when no reusable connection exists.
    """

    global _connection

    # Fetch dynamically from environment
    database_url = os.getenv("DATABASE_URL")

    try:

        if not database_url:
            raise ValueError(
                "DATABASE_URL is not set"
            )

        if _connection is not None:

            try:

                if _connection.closed == 0:

                    logger.log_event(
                        level="INFO",
                        event="database_connection_success",
                        component="database"
                    )

                    return _connection

            except Exception:

                _connection = None

        _connection = psycopg2.connect(
            database_url
        )

        logger.log_event(
            level="INFO",
            event="database_connection_success",
            component="database"
        )

        return _connection

    except Exception as error:

        logger.log_event(
            level="ERROR",
            event="database_connection_failed",
            component="database",
            reason=str(error)
        )

        raise


def close_connection():
    """
    Close the shared PostgreSQL connection.
    """

    global _connection

    if _connection:

        try:

            _connection.close()

        except Exception as error:

            logger.log_event(
                level="WARNING",
                event="database_connection_close_failed",
                component="database",
                reason=str(error)
            )

        finally:

            _connection = None
