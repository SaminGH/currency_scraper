import logs.logger as logger
import database


if __name__ == "__main__":

    logger.start_run()
    run_id = logger.get_run_id()
    logger.log_event(level="INFO", event="pipeline_started", component="main", run_id=run_id)

    snapshot_id = None
    connection = None

    try:
        connection = database.get_connection()
        snapshot_id = database.create_snapshot(run_id, connection=connection)
        logger.set_snapshot_id(snapshot_id)
    
        import scraper_output as scraper_output
        import validator as validator
        import price_aggregator as price_aggregator
        import change as change

        raw_prices = scraper_output.prices
        source_status = getattr(scraper_output, "source_status", {})
        validated_prices = validator.prices
        final_prices = price_aggregator.final_prices

        removed_sources = {}
        for currency, data in validated_prices.items():
            if isinstance(data, dict) and isinstance(data.get("removed_sources"), dict):
                if data["removed_sources"]:
                    removed_sources[currency] = data["removed_sources"]

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
        database.close_connection()