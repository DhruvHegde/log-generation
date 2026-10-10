"""rca/engine.py

RCA Engine and analyzer registry dispatcher.
"""

from __future__ import annotations

from typing import Any, Optional

from rca.base import BaseCategoryAnalyzer
from rca.schema import RCAReport


class RCAEngine:
    """Orchestrator that dispatches parsed log records to appropriate category analyzers."""

    def __init__(self, analyzers: Optional[list[BaseCategoryAnalyzer]] = None):
        self._analyzers: list[BaseCategoryAnalyzer] = list(analyzers) if analyzers else []

    @property
    def analyzers(self) -> list[BaseCategoryAnalyzer]:
        """List of currently registered analyzers in evaluation order."""
        return list(self._analyzers)

    def register_analyzer(self, analyzer: BaseCategoryAnalyzer, priority: int = -1) -> None:
        """
        Register an analyzer in the dispatch chain.

        Parameters
        ----------
        analyzer:
            Instance of BaseCategoryAnalyzer to register.
        priority:
            Index position in the list. Default -1 appends before any final fallback.
        """
        if priority == -1:
            self._analyzers.append(analyzer)
        else:
            self._analyzers.insert(priority, analyzer)

    def analyze_record(self, record: Any) -> RCAReport:
        """
        Dispatch a single LogRecord or dict to the matching analyzer.

        Parameters
        ----------
        record:
            LogRecord instance or dict matching LogRecord.to_dict().

        Returns
        -------
        RCAReport
            Evidence-grounded RCA report.
        """
        for analyzer in self._analyzers:
            if analyzer.can_analyze(record):
                return analyzer.analyze(record)

        # Safety fallback if no registered analyzer accepted the record
        from rca.analyzers.fallback import FallbackAnalyzer
        return FallbackAnalyzer().analyze(record)

    def analyze_batch(self, records: list[Any]) -> list[RCAReport]:
        """Analyze a collection of records and return a list of RCAReports."""
        return [self.analyze_record(rec) for rec in records]


_DEFAULT_ENGINE: Optional[RCAEngine] = None


def get_default_engine() -> RCAEngine:
    """Return the global default RCAEngine with standard F1-F4 and fallback analyzers registered."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        from rca.analyzers.syntax import SyntaxAnalyzer
        from rca.analyzers.dependency import DependencyAnalyzer
        from rca.analyzers.test_failure import TestFailureAnalyzer
        from rca.analyzers.timeout import TimeoutAnalyzer
        from rca.analyzers.fallback import FallbackAnalyzer

        engine = RCAEngine()
        engine.register_analyzer(SyntaxAnalyzer())
        engine.register_analyzer(DependencyAnalyzer())
        engine.register_analyzer(TestFailureAnalyzer())
        engine.register_analyzer(TimeoutAnalyzer())
        engine.register_analyzer(FallbackAnalyzer())
        _DEFAULT_ENGINE = engine

    return _DEFAULT_ENGINE


def analyze_record(record: Any) -> RCAReport:
    """Convenience function to analyze a single record using the default RCA engine."""
    return get_default_engine().analyze_record(record)


def analyze_batch(records: list[Any]) -> list[RCAReport]:
    """Convenience function to analyze a batch of records using the default RCA engine."""
    return get_default_engine().analyze_batch(records)
