# parser/__init__.py
"""CI/CD log parser package."""
from .log_parser import parse_log_file, parse_log_text, LogRecord

__all__ = ["parse_log_file", "parse_log_text", "LogRecord"]
