"""Scenario S04: Input validation and edge cases."""
import re
import pytest


def validate_email(email: str) -> bool:
    if not isinstance(email, str):
        raise TypeError("Email must be a string.")
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


def validate_port_number(port: int) -> int:
    if not isinstance(port, int) or isinstance(port, bool):
        raise TypeError("Port must be an integer.")
    if not (1 <= port <= 65535):
        raise ValueError(f"Port {port} is out of valid range (1-65535).")
    return port


def clamp(val: float, low: float, high: float) -> float:
    if low > high:
        raise ValueError("Lower bound cannot be greater than upper bound.")
    return max(low, min(val, high))


def test_validate_email():
    assert validate_email("user@example.com") is True
    assert validate_email("admin.name+tag@sub.domain.org") is True
    assert validate_email("invalid-email") is False
    assert validate_email("@no-user.com") is False

    with pytest.raises(TypeError):
        validate_email(12345)


def test_validate_port():
    assert validate_port_number(80) == 80
    assert validate_port_number(443) == 443
    assert validate_port_number(65535) == 65535

    with pytest.raises(ValueError):
        validate_port_number(0)

    with pytest.raises(ValueError):
        validate_port_number(70000)

    with pytest.raises(TypeError):
        validate_port_number("8080")


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-5, 0, 10) == 0
    assert clamp(15, 0, 10) == 10
    with pytest.raises(ValueError):
        clamp(5, 10, 0)
