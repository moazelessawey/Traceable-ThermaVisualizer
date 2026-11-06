"""Color maps and color scaling for heat displays (VIS-04).

Color-blind-safe maps (viridis, cividis) are available per the accessibility
NFR; viridis is the default. Values are °C or %RH depending on quantity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

_BACKEND_NAMES = {
    "viridis": "viridis",
    "cividis": "cividis",
    "thermal": "jet",  # jet-like "thermal" map (VIS-04)
    "coolwarm": "coolwarm",
}


class ColorMapName(StrEnum):
    """Named color maps (VIS-04)."""

    VIRIDIS = "viridis"
    CIVIDIS = "cividis"
    THERMAL = "thermal"
    COOLWARM = "coolwarm"


@dataclass(frozen=True)
class ColorScale:
    """Color map plus range policy (VIS-04 fixed or auto range, user min/max)."""

    colormap: ColorMapName = ColorMapName.VIRIDIS
    auto_range: bool = True
    vmin: float = 0.0
    vmax: float = 1.0
    custom_colors: tuple[str, ...] | None = None  # user ramp overrides colormap


def colormap_for(scale: ColorScale) -> str | list[str]:
    """Return the backend color map for a scale (name or custom color ramp).

    Custom ramps are returned as a list: PyVista accepts str/list/Colormap
    but not tuples. Units: n/a.
    """
    if scale.custom_colors:
        return list(scale.custom_colors)
    return _BACKEND_NAMES[scale.colormap.value]


def color_limits(scale: ColorScale, data: np.ndarray) -> tuple[float, float] | None:
    """Color limits for rendering: fixed user range, or auto from finite data."""
    if not scale.auto_range:
        return (float(scale.vmin), float(scale.vmax))
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return None
    return (float(finite.min()), float(finite.max()))


def color_scale_to_dict(scale: ColorScale) -> dict:
    """JSON-safe representation of a color scale (view state)."""
    return {
        "colormap": scale.colormap.value,
        "auto_range": scale.auto_range,
        "vmin": scale.vmin,
        "vmax": scale.vmax,
        "custom_colors": list(scale.custom_colors) if scale.custom_colors else None,
    }


def color_scale_from_dict(data: dict) -> ColorScale:
    """Build a color scale from stored view state."""
    custom = data.get("custom_colors")
    return ColorScale(
        colormap=ColorMapName(str(data.get("colormap", "viridis"))),
        auto_range=bool(data.get("auto_range", True)),
        vmin=float(data.get("vmin", 0.0)),
        vmax=float(data.get("vmax", 1.0)),
        custom_colors=tuple(custom) if custom else None,
    )
