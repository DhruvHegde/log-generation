"""rca/base.py

Abstract base class and shared utilities for RCA category analyzers.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Optional, Union

from rca.schema import RCAReport


def get_field(record: Any, field_name: str, default: Any = None) -> Any:
    """Retrieve a field safely from a LogRecord dataclass or a dict."""
    if isinstance(record, dict):
        return record.get(field_name, default)
    return getattr(record, field_name, default)


def clean_line(line: str) -> str:
    """Strip tab prefixes and leading timestamps for cleaner human-readable evidence."""
    # Handle tab-separated: <job>\t<step>\t<ts> <msg>
    parts = line.split("\t")
    text = parts[-1] if len(parts) > 1 else line
    # Strip ISO timestamp if present: 2026-08-19T14:06:54.5495401Z ...
    m = re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s*(.*)$", text)
    if m:
        return m.group(1).strip()
    return text.strip()


class BaseCategoryAnalyzer(ABC):
    """Abstract base class for domain-specific RCA failure analyzers."""

    @property
    @abstractmethod
    def category_name(self) -> str:
        """Name of the failure category this analyzer targets."""
        pass

    @abstractmethod
    def can_analyze(self, record: Any) -> bool:
        """Determine whether this analyzer can handle the given record."""
        pass

    @abstractmethod
    def analyze(self, record: Any) -> RCAReport:
        """Perform root cause analysis and return an RCAReport."""
        pass
