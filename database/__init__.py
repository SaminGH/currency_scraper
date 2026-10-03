"""Database package public API."""

from .connection import get_connection, close_connection
from .lookup import get_source_ids, get_currency_ids
from .snapshot import create_snapshot, complete_snapshot
from .publisher import publish_snapshot, fail_snapshot
from .source_health import save_source_health
from .source_rates import save_source_rates
from .aggregated_rates import save_aggregated_rates
from .summary import save_snapshot_summary
from .published_rates import save_published_rates

save_source_status = save_source_health

__all__ = [
    "get_connection", "close_connection",
    "get_source_ids", "get_currency_ids",
    "create_snapshot", "complete_snapshot",
    "publish_snapshot", "fail_snapshot",
    "save_source_health", "save_source_status",
    "save_source_rates", "save_aggregated_rates",
    "save_snapshot_summary", "save_published_rates",
]
