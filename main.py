import change
import confidence
import database
import logs.logger as logger
import price_aggregator
import scraper_output
import validator


from typing import Any, Dict, Optional


def run_pipeline(connection: Optional[Any] = None) -> Dict[str, Any]:
    """
    Execute the full currency scraping, validation, aggregation, and publishing pipeline.

    Parameters:
        connection: Optional database connection. If None, acquires one from database.get_connection().

    Returns:
        Publish result dictionary from database.publish_snapshot.
    """
    logger.start_run()
    run_id = logger.get_run_id()
    logger.log_event(level="INFO", event="pipeline_started", component="main", run_id=run_id)

    snapshot_id = None
    own_connection = connection is None

    try:
        if own_connection:
            connection = database.get_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(74839201);")
            acquired = cursor.fetchone()[0]
        if not acquired:
            logger.log_event(level="WARNING", event="pipeline_skipped", component="main", reason="previous_run_still_in_progress")
            if own_connection:
                database.close_connection()
            return {}

        snapshot_id = database.create_snapshot(run_id, connection=connection)
        logger.set_snapshot_id(snapshot_id)

        # 1. Scraper output
        raw_prices, source_status = scraper_output.get_scraper_output()

        # 2. Validation
        validated_prices = validator.validate_prices(raw_prices)

        # 3. Price aggregation
        final_prices = price_aggregator.aggregate_prices(validated_prices)

        # 3.1 Calculate deterministic confidence scores
        for currency, data in final_prices.items():
            if not isinstance(data, dict):
                continue
            currency_val_data = validated_prices.get(currency, {})
            val_prices = currency_val_data.get("prices", {}) if isinstance(currency_val_data, dict) else {}
            sources_total = data.get("sources_total", len(val_prices))
            conf_result = confidence.calculate_confidence(
                valid_prices=val_prices,
                total_sources=sources_total,
                snapshot_time=data.get("timestamp"),
            )
            data["confidence"] = conf_result["rating"]
            data["confidence_reason"] = conf_result["score_reason"]
            data["confidence_metrics"] = conf_result.get("metrics")

        removed_sources = {}
        for currency, data in validated_prices.items():
            if isinstance(data, dict) and isinstance(data.get("removed_sources"), dict):
                if data["removed_sources"]:
                    removed_sources[currency] = data["removed_sources"]

        # 4. 24h Change calculation
        # Change calculation reads the previous committed snapshot and uses the
        # current prepared aggregate, which has not been persisted yet.
        change_24h = change.calculate_change_24h(
            snapshot_id=snapshot_id,
            current_rates=final_prices,
            connection=connection,
        )

        published_rates = {}
        for currency, data in final_prices.items():
            if not isinstance(data, dict) or not data.get("publishable", False):
                continue
            published_data = dict(data)
            change_data = change_24h.get(currency)
            published_data["change_24h"] = change_data.get("change_24h") if isinstance(change_data, dict) else None
            published_data["high_24h"] = change_data.get("high_24h") if isinstance(change_data, dict) else None
            published_data["low_24h"] = change_data.get("low_24h") if isinstance(change_data, dict) else None
            published_rates[currency] = published_data

        sources_attempted = len(source_status)
        sources_successful = sum(
            1
            for data in source_status.values()
            if isinstance(data, dict) and data.get("status") == "success"
        )
        sources_failed = sum(
            1
            for data in source_status.values()
            if isinstance(data, dict) and data.get("status") == "failed"
        )
        sources_partial = sum(
            1
            for data in source_status.values()
            if isinstance(data, dict) and data.get("status") == "partial"
        )

        raw_rates = sum(
            len(data.get("prices", {}))
            for data in raw_prices.values()
            if isinstance(data, dict) and isinstance(data.get("prices", {}), dict)
        )
        valid_rates = sum(
            len(data.get("prices", {}))
            for data in validated_prices.values()
            if isinstance(data, dict) and isinstance(data.get("prices", {}), dict)
        )
        outliers = sum(
            len(data.get("removed_sources", {}))
            for data in validated_prices.values()
            if isinstance(data, dict) and isinstance(data.get("removed_sources", {}), dict)
        )

        if sources_attempted == 0 or sources_failed == sources_attempted:
            snapshot_status = "failed"
        elif sources_failed or sources_partial:
            snapshot_status = "completed_with_warnings"
        else:
            snapshot_status = "completed"

        summary = {
            "status": snapshot_status,
            "sources_attempted": sources_attempted,
            "sources_successful": sources_successful,
            "sources_failed": sources_failed,
            "raw_rates": raw_rates,
            "valid_rates": valid_rates,
            "outliers": outliers,
            "final_rates": len(final_prices),
            "publishable_rates": len(published_rates),
        }

        # 5. Database publish
        publish_result = database.publish_snapshot(
            snapshot_id=snapshot_id,
            run_id=run_id,
            source_status=source_status,
            raw_prices=raw_prices,
            removed_sources=removed_sources,
            aggregated_rates=final_prices,
            published_rates=published_rates,
            summary=summary,
            snapshot_status=snapshot_status,
            connection=connection,
        )

        logger.log_event(
            level="INFO",
            event="pipeline_completed",
            component="main",
            run_id=run_id,
            snapshot_id=snapshot_id,
            currencies=len(final_prices),
            published_rates=publish_result["published_rates"],
        )

        return publish_result

    except Exception as error:
        logger.log_event(
            level="ERROR",
            event="pipeline_failed",
            component="main",
            run_id=run_id,
            snapshot_id=snapshot_id,
            reason=str(error)
        )

        if snapshot_id and connection:
            try:
                database.fail_snapshot(
                    snapshot_id=snapshot_id,
                    run_id=run_id,
                    connection=connection
                )
            except Exception as failure_error:
                logger.log_event(
                    level="ERROR",
                    event="snapshot_failure_update_failed",
                    component="main",
                    run_id=run_id,
                    snapshot_id=snapshot_id,
                    reason=str(failure_error)
                )

        raise

    finally:
        if connection is not None:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(74839201);")
            except Exception:
                pass
        if own_connection:
            database.close_connection()


main = run_pipeline


if __name__ == "__main__":
    run_pipeline()