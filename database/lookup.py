import logger

from .connection import get_connection


def get_source_ids(connection=None):
    db = connection or get_connection()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT id, code FROM public.sources WHERE is_active = TRUE")
            rows = cursor.fetchall()
        result = {code: source_id for source_id, code in rows}
        logger.log_event(level="INFO", event="source_ids_loaded", component="database", sources=len(result))
        return result
    except Exception as error:
        logger.log_event(level="ERROR", event="source_ids_load_failed", component="database", reason=str(error))
        raise


def get_currency_ids(connection=None):
    db = connection or get_connection()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT id, code FROM public.currencies WHERE is_active = TRUE")
            rows = cursor.fetchall()
        result = {code: currency_id for currency_id, code in rows}
        logger.log_event(level="INFO", event="currency_ids_loaded", component="database", currencies=len(result))
        return result
    except Exception as error:
        logger.log_event(level="ERROR", event="currency_ids_load_failed", component="database", reason=str(error))
        raise
