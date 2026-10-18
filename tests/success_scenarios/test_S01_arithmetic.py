"""Scenario S01: Basic arithmetic and utility functions."""
import math
import pytest


def add(a, b):
    return a + b


def multiply(a, b):
    return a * b


def power(base, exp):
    return base ** exp


def is_prime(n):
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def gcd(a, b):
    return math.gcd(a, b)


def test_basic_arithmetic():
    assert add(10, 20) == 30
    assert add(-5, 5) == 0
    assert multiply(7, 8) == 56
    assert power(2, 10) == 1024


def test_primes():
    primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
    for p in primes:
        assert is_prime(p) is True
    non_primes = [-1, 0, 1, 4, 6, 8, 9, 15, 25]
    for np in non_primes:
        assert is_prime(np) is False


def test_gcd():
    assert gcd(48, 18) == 6
    assert gcd(101, 10) == 1
    assert gcd(0, 5) == 5
