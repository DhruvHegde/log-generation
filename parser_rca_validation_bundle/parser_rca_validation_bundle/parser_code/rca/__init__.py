"""rca/__init__.py

RCA V1: Root Cause Analysis package for CI/CD failure logs.
"""

from rca.schema import (
    RCAReport,
    CAUSAL_CODE_DEFECT,
    CAUSAL_DEPENDENCY,
    CAUSAL_TEST,
    CAUSAL_TIMEOUT,
    CAUSAL_ENVIRONMENT,
    CAUSAL_UNKNOWN,
    VALID_CAUSAL_CATEGORIES,
)
from rca.base import BaseCategoryAnalyzer
from rca.engine import RCAEngine, get_default_engine, analyze_record, analyze_batch

__all__ = [
    "RCAReport",
    "BaseCategoryAnalyzer",
    "RCAEngine",
    "get_default_engine",
    "analyze_record",
    "analyze_batch",
    "CAUSAL_CODE_DEFECT",
    "CAUSAL_DEPENDENCY",
    "CAUSAL_TEST",
    "CAUSAL_TIMEOUT",
    "CAUSAL_ENVIRONMENT",
    "CAUSAL_UNKNOWN",
    "VALID_CAUSAL_CATEGORIES",
]
