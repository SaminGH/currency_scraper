import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

import logs.logger as logger

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / "environment" / ".env"


load_dotenv(ENV_FILE)

DATABASE_URL = os.getenv("DATABASE_URL")

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

    try:

        if not DATABASE_URL:
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
            DATABASE_URL
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

