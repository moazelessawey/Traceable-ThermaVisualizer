"""Color map and color-scale tests (VIS-04)."""

from __future__ import annotations

import numpy as np

from thermavisualizer.rendering.colormaps import (
    ColorMapName,
    ColorScale,
    color_limits,
    colormap_for,
)


def test_named_maps_resolve_to_backend_names() -> None:
    assert colormap_for(ColorScale(colormap=ColorMapName.VIRIDIS)) == "viridis"
    assert colormap_for(ColorScale(colormap=ColorMapName.THERMAL)) == "jet"
    assert colormap_for(ColorScale(colormap=ColorMapName.COOLWARM)) == "coolwarm"
    assert colormap_for(ColorScale(colormap=ColorMapName.CIVIDIS)) == "cividis"


def test_custom_ramp_overrides_name() -> None:
    scale = ColorScale(custom_colors=("#000000", "#ff0000"))
    assert colormap_for(scale) == ["#000000", "#ff0000"]


def test_color_limits_fixed_and_auto() -> None:
    data = np.array([1.0, np.nan, 5.0])
    fixed = ColorScale(auto_range=False, vmin=-2.0, vmax=8.0)
    assert color_limits(fixed, data) == (-2.0, 8.0)
    auto = ColorScale()
    assert color_limits(auto, data) == (1.0, 5.0)
    assert color_limits(auto, np.array([np.nan, np.nan])) is None


def test_color_scale_dict_roundtrip() -> None:
    from thermavisualizer.rendering.colormaps import (
        ColorScale,
        color_scale_from_dict,
        color_scale_to_dict,
    )

    scale = ColorScale(auto_range=False, vmin=2.0, vmax=8.0, custom_colors=("#000000", "#ffffff"))
    assert color_scale_from_dict(color_scale_to_dict(scale)) == scale
