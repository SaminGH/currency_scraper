if __name__ == "__main__":
    import tests.test_hybrid_scrapers as t
    t.test_function_signatures()
    t.test_tgju_exception_mapping()
    t.test_alanchand_exception_mapping()
    t.test_async_scraper_timeout_and_cancellation()
    t.test_async_scraper_retry_behavior()
    t.test_client_cleanup_on_completion()
    t.test_outer_cancellation_cancels_inner_task()
    t.test_client_follow_redirects_configured()
    t.test_scrapers_dict_dispatch_override()
    t.test_run_all_in_running_event_loop()
    t.test_mp_source_process_spawn_failure()
    print("ALL TESTS PASSED SUCCESSFULLY!")

