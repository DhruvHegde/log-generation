"""Scenario S08: Numerical calculations and descriptive statistics."""
import math
import pytest


def calculate_mean(values):
    if not values:
        raise ValueError("Cannot calculate mean of empty list.")
    return sum(values) / len(values)


def calculate_median(values):
    if not values:
        raise ValueError("Cannot calculate median of empty list.")
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_v[mid])
    return (sorted_v[mid - 1] + sorted_v[mid]) / 2.0


def calculate_variance(values):
    if len(values) < 2:
        raise ValueError("Variance requires at least two data points.")
    m = calculate_mean(values)
    return sum((x - m) ** 2 for x in values) / (len(values) - 1)


def calculate_std_dev(values):
    return math.sqrt(calculate_variance(values))


def test_statistics():
    data = [10, 20, 30, 40, 50]
    assert calculate_mean(data) == 30.0
    assert calculate_median(data) == 30.0
    assert calculate_variance(data) == 250.0
    assert pytest.approx(calculate_std_dev(data), 0.01) == 15.81


def test_even_median():
    data = [1, 2, 3, 4]
    assert calculate_median(data) == 2.5


def test_empty_errors():
    with pytest.raises(ValueError):
        calculate_mean([])
    with pytest.raises(ValueError):
        calculate_median([])
    with pytest.raises(ValueError):
        calculate_variance([42])
