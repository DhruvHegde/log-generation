"""Scenario S06: 2D Matrix mathematics and operations."""
import pytest


def transpose(matrix):
    if not matrix or not matrix[0]:
        return []
    return [[matrix[r][c] for r in range(len(matrix))] for c in range(len(matrix[0]))]


def matrix_add(m1, m2):
    if len(m1) != len(m2) or len(m1[0]) != len(m2[0]):
        raise ValueError("Matrices must have identical dimensions for addition.")
    return [
        [m1[r][c] + m2[r][c] for c in range(len(m1[0]))]
        for r in range(len(m1))
    ]


def matrix_multiply(m1, m2):
    rows_m1 = len(m1)
    cols_m1 = len(m1[0])
    rows_m2 = len(m2)
    cols_m2 = len(m2[0])

    if cols_m1 != rows_m2:
        raise ValueError("Incompatible dimensions for matrix multiplication.")

    result = [[0] * cols_m2 for _ in range(rows_m1)]
    for i in range(rows_m1):
        for j in range(cols_m2):
            for k in range(cols_m1):
                result[i][j] += m1[i][k] * m2[k][j]
    return result


def test_transpose():
    m = [
        [1, 2, 3],
        [4, 5, 6]
    ]
    assert transpose(m) == [
        [1, 4],
        [2, 5],
        [3, 6]
    ]


def test_matrix_add():
    m1 = [[1, 2], [3, 4]]
    m2 = [[5, 6], [7, 8]]
    assert matrix_add(m1, m2) == [[6, 8], [10, 12]]

    with pytest.raises(ValueError):
        matrix_add([[1, 2]], [[1], [2]])


def test_matrix_multiply():
    m1 = [[1, 2], [3, 4]]
    m2 = [[2, 0], [1, 2]]
    # [[1*2 + 2*1, 1*0 + 2*2], [3*2 + 4*1, 3*0 + 4*2]] = [[4, 4], [10, 8]]
    assert matrix_multiply(m1, m2) == [[4, 4], [10, 8]]
