"""Scenario S02: String and collection operations."""
import re
import pytest


def reverse_string(s: str) -> str:
    return s[::-1]


def is_palindrome(s: str) -> bool:
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", s).lower()
    return cleaned == cleaned[::-1]


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", cleaned)


def truncate(s: str, max_len: int, ellipsis: str = "...") -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len - len(ellipsis)] + ellipsis


def test_reverse():
    assert reverse_string("hello") == "olleh"
    assert reverse_string("") == ""
    assert reverse_string("a") == "a"


def test_palindrome():
    assert is_palindrome("A man, a plan, a canal: Panama") is True
    assert is_palindrome("race a car") is False
    assert is_palindrome("Was it a car or a cat I saw?") is True


def test_slugify():
    assert slugify("Hello World! 2026") == "hello-world-2026"
    assert slugify("   Multiple   Spaces   ") == "multiple-spaces"


def test_truncate():
    assert truncate("Short", 10) == "Short"
    assert truncate("This is a long sentence.", 10) == "This is..."
