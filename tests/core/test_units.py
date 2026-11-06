"""Unit conversion tests (DAT-08)."""

from __future__ import annotations

import numpy as np

from thermavisualizer.core.models import TemperatureUnit
from thermavisualizer.core.units import to_celsius


def test_celsius_identity_copies() -> None:
    values = np.array([20.0, 25.0])
    result = to_celsius(values, TemperatureUnit.CELSIUS)
    assert np.array_equal(result, values)
    result[0] = 99.0
    assert values[0] == 20.0  # input untouched


def test_fahrenheit_conversion() -> None:
    result = to_celsius(np.array([32.0, 212.0, -40.0]), TemperatureUnit.FAHRENHEIT)
    assert np.allclose(result, [0.0, 100.0, -40.0])


def test_kelvin_conversion() -> None:
    result = to_celsius(np.array([273.15, 293.15]), TemperatureUnit.KELVIN)
    assert np.allclose(result, [0.0, 20.0])
