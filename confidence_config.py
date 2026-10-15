"""
Confidence Engine Configuration.

Defines all thresholds and parameters used by the deterministic confidence engine.
No threshold parameters should be hard-coded directly in calculation functions.
"""

from dataclasses import dataclass


# ============================================================
# Source Count Criteria (Valid Sources Only)
# ============================================================
# Minimum count of valid sources required for HIGH rating potential (>= 3)
MIN_VALID_SOURCES_HIGH: int = 3

# Minimum count of valid sources required for MEDIUM rating potential (== 2)
# Valid source count < 2 yields a LOW confidence rating.
MIN_VALID_SOURCES_MEDIUM: int = 2


# ============================================================
# Dispersion (Relative Spread) Criteria
# Dispersion = (Max(P_valid) - Min(P_valid)) / Mean(P_valid)
# ============================================================
# Maximum relative dispersion threshold for HIGH rating (<= 0.2% / 0.002)
MAX_DISPERSION_HIGH: float = 0.05

# Maximum relative dispersion threshold for MEDIUM rating (<= 0.5% / 0.005)
# Dispersion exceeding this threshold degrades the rating to LOW.
MAX_DISPERSION_MEDIUM: float = 0.01


# ============================================================
# Freshness Criteria
# ============================================================
# Maximum allowable age/time-delta in seconds for input data before degrading confidence.
# e.g., 3600 seconds = 1 hour
MAX_AGE_SECONDS: float = 3600.0


@dataclass(frozen=True)
class ConfidenceConfig:
    """Centralized configuration for confidence score evaluation."""

    min_valid_sources_high: int = MIN_VALID_SOURCES_HIGH
    min_valid_sources_medium: int = MIN_VALID_SOURCES_MEDIUM
    max_dispersion_high: float = MAX_DISPERSION_HIGH
    max_dispersion_medium: float = MAX_DISPERSION_MEDIUM
    max_age_seconds: float = MAX_AGE_SECONDS


DEFAULT_CONFIG = ConfidenceConfig()
