
```` markdown
# Task: Dedicated Deterministic Confidence Score Engine Implementation

## Objective
Decouple and extract Confidence Score calculation into a dedicated, deterministic module (`confidence.py`) with a centralized configuration file (`confidence_config.py`). Confidence ratings (`"HIGH"`, `"MEDIUM"`, `"LOW"`) must be calculated based strictly on valid sources remaining after validation, price dispersion (relative spread), and data freshness.

---

## Architecture & Module Structure

### 1. Configuration Module (`confidence_config.py` or `config/confidence_config.py`)
Create a central configuration file for all confidence evaluation rules and thresholds. **Do NOT hard-code any threshold parameters within calculation functions.**

Include configurable settings for:
- **Source Count Criteria (Valid Sources Only):**
  - Minimum count of valid sources for `HIGH` rating potential (e.g., `>= 3`).
  - Minimum count of valid sources for `MEDIUM` rating potential (e.g., `== 2`).
  - Valid source count `< 2` yields a `LOW` confidence rating.
- **Dispersion (Relative Spread) Criteria:**
  - Maximum relative dispersion threshold for `HIGH` rating (e.g., relative spread `<= 0.2%` / `0.002`).
  - Maximum relative dispersion threshold for `MEDIUM` rating (e.g., relative spread `<= 0.5%` / `0.005`).
  - Excessive dispersion degrades the rating tier accordingly.
- **Freshness Criteria:**
  - Maximum allowable age/time-delta in seconds for input data before degrading confidence rating.

---

### 2. Core Confidence Engine (`confidence.py`)

#### Input Data Requirements & Origin:
The `calculate_confidence` function accepts:
1. `valid_prices`: Dictionary of healthy prices `{source_name: price}` extracted from `validator.py` (outliers from `removed_sources` are excluded).
2. `total_sources`: Total count of attempted sources for this currency before validation.
3. `snapshot_time` or `source_timestamps` (Optional): The timestamp of the current pipeline execution run to verify data freshness.

#### Dispersion Logic & Math Explanation:
Compute the relative spread across valid prices to measure market convergence:
$$\text{Dispersion} = \frac{\text{Max}(P_{\text{valid}}) - \text{Min}(P_{\text{valid}})}{\text{Mean}(P_{\text{valid}})}$$
- **Purpose:** Measures the percentage deviation between the highest and lowest reported rates among valid sources. Lower dispersion indicates higher agreement between sources.
- **Guards:**
  - If `len(valid_prices) < 2`, skip dispersion evaluation and assign `LOW` rating based on source count.
  - Guard against division by zero if `Mean(P_valid) == 0`.

#### Deterministic Rating Output:
- Return an explicit, deterministic string rating: `"HIGH"`, `"MEDIUM"`, or `"LOW"`.
- Identical inputs MUST always produce the exact same rating output.

#### Function Signature:
```python
def calculate_confidence(
    valid_prices: dict[str, float],
    total_sources: int,
    snapshot_time: datetime | str | None = None,
    source_timestamps: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Evaluates quality confidence rating for a single currency rate.

    Returns:
        dict: {
            "rating": "HIGH", # "HIGH" | "MEDIUM" | "LOW"
            "score_reason": "valid_sources_above_threshold_low_dispersion",
            "metrics": {
                "valid_sources_count": 3,
                "total_sources_count": 4,
                "dispersion_pct": 0.0033
            }
        }
    """

````

-----

### 3\. Cleanup & Pipeline Integration (`validator.py`, `price_aggregator.py`, `main.py`)

  - **`validator.py` Cleanup:** Remove legacy confidence formatting logic from `validator.py`. `validator.py` must focus exclusively on outlier detection and returning `valid_prices` & `removed_sources`.
  - **Pipeline Integration:** Invoke `confidence.calculate_confidence()` during/after aggregation in `main.py`.
  - **Database Compatibility:** Populate the calculated rating string (`"HIGH"`, `"MEDIUM"`, `"LOW"`) directly into the `confidence` key of `final_prices` / `published_rates`.
  - **Zero Schema Changes:** Ensure existing database insertion logic in `database/aggregated_rates.py` and `database/published_rates.py` receives this string seamlessly without requiring any SQL or schema modifications.

-----

### Constraints & Error Handling

  - **Anti-Crash:** Wrap evaluation in `try...except` blocks. In case of unexpected data anomalies, log the error using `logger.log_event` and safely fall back to `"LOW"`.
  - **Preserve Independent Modules:** Do not modify scrapers, `scraper_output.py`, `source_health.py`, or database table definitions.

<!-- end list -->

``` 
 
```
