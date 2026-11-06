"""Unit conversions. Canonical storage: °C, %RH, metres (AGENTS domain rule)."""

from __future__ import annotations

import numpy as np

from thermavisualizer.core.models import TemperatureUnit


def _coerce_unit(unit) -> TemperatureUnit:
    """Accept a TemperatureUnit or its string value (QVariant round-trips)."""
    if isinstance(unit, TemperatureUnit):
        return unit
    return TemperatureUnit(str(unit))


def to_celsius(values: np.ndarray, unit) -> np.ndarray:
    """Convert temperature values to °C. Returns a new array; input untouched.

    ``unit`` may be a TemperatureUnit or its string value. Units: input °F/K/°C,
    output always °C.
    """
    unit = _coerce_unit(unit)
    if unit is TemperatureUnit.CELSIUS:
        return values.astype(float, copy=True)
    if unit is TemperatureUnit.FAHRENHEIT:
        return (values - 32.0) * 5.0 / 9.0
    return values - 273.15  # Kelvin
