"""View3DWidget behavior with a fake renderer (VIS-01..04/06, SLC-01/02)."""

from __future__ import annotations

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

import thermavisualizer.rendering.view3d as view3d_module
from thermavisualizer.core.interpolation import InterpolationSettings, build_voxel_grid
from thermavisualizer.core.models import BoxFootprint, Quantity, Space
from thermavisualizer.core.slicing import SliceAxis
from thermavisualizer.core.statistics import AggregationMethod
from thermavisualizer.rendering.colormaps import ColorScale
from thermavisualizer.rendering.scene import PresetView
from thermavisualizer.rendering.view3d import SliceSpec, View3DWidget
from thermavisualizer.services.workers import InterpolationResult

from conftest import FakeSceneRenderer


def _space() -> Space:
    return Space(footprint=BoxFootprint(0.0, 0.0, 1.0, 1.0), height=1.0)


def _result(space: Space, quantity: Quantity = Quantity.TEMPERATURE) -> InterpolationResult:
    settings = InterpolationSettings(resolution=0.5)
    grid = build_voxel_grid(space, settings.resolution)
    xs, ys, zs = grid.meshgrid()
    volume = xs + 2.0 * ys + 3.0 * zs
    positions = np.array([[0.2, 0.2, 0.5], [0.8, 0.8, 0.5]])
    return InterpolationResult(
        volume=volume,
        quantity=quantity,
        settings=settings,
        aggregation=AggregationMethod.MEAN,
        time_label="mean window",
        cache_key=("test",),
        from_cache=False,
        positions=positions,
        logger_ids=("L1", "L2"),
    )


@pytest.fixture
def view(qtbot: QtBot, fake_renderer: FakeSceneRenderer) -> View3DWidget:
    widget = View3DWidget(renderer=fake_renderer)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_update_volume_renders_space_and_markers(
    view: View3DWidget, fake_renderer: FakeSceneRenderer
) -> None:
    space = _space()
    view.update_volume(_result(space), space, [])
    assert fake_renderer.space_calls[-1] is space
    assert fake_renderer.marker_calls[-1] == (2, -1)  # no values yet
    assert fake_renderer.marker_titles[-1] == "Temperature (°C)"


def test_quantity_title_follows_result(
    view: View3DWidget, fake_renderer: FakeSceneRenderer
) -> None:  # VIS-06
    space = _space()
    view.update_volume(_result(space, Quantity.HUMIDITY), space, [])
    assert fake_renderer.marker_titles[-1] == "Humidity (%RH)"


def test_slices_are_extracted_and_shown(
    view: View3DWidget, fake_renderer: FakeSceneRenderer
) -> None:  # SLC-01/02
    space = _space()
    view.update_volume(_result(space), space, [])
    view.set_slices(
        [
            SliceSpec(spec_id="z1", axis=SliceAxis.Z, position=0.5, opacity=0.7),
            SliceSpec(spec_id="off", axis=SliceAxis.X, position=0.5, visible=False),
        ]
    )
    keys = [call[0] for call in fake_renderer.slice_calls]
    assert "z1" in keys
    assert "off" not in keys
    assert fake_renderer.slice_calls[-1][1] == 0.7
    assert fake_renderer.removed_slices.count("off") >= 1


def test_fixed_color_scale_passes_limits(
    view: View3DWidget, fake_renderer: FakeSceneRenderer
) -> None:  # VIS-04
    space = _space()
    view.update_volume(_result(space), space, [])
    view.set_color_scale(ColorScale(auto_range=False, vmin=1.0, vmax=9.0))
    view.set_slices([SliceSpec(spec_id="z1", axis=SliceAxis.Z, position=0.5)])
    assert fake_renderer.slice_calls[-1][2] == (1.0, 9.0)


def test_auto_color_scale_uses_volume_range(
    view: View3DWidget, fake_renderer: FakeSceneRenderer
) -> None:
    space = _space()
    result = _result(space)
    view.update_volume(result, space, [])
    view.set_slices([SliceSpec(spec_id="z1", axis=SliceAxis.Z, position=0.5)])
    finite = result.volume[np.isfinite(result.volume)]
    assert fake_renderer.slice_calls[-1][2] == (float(finite.min()), float(finite.max()))


def test_logger_values_reach_markers(
    view: View3DWidget, fake_renderer: FakeSceneRenderer
) -> None:  # VIS-03
    space = _space()
    view.update_volume(_result(space), space, [])
    view.set_logger_values(np.array([20.1, 21.4]))
    assert fake_renderer.marker_calls[-1] == (2, 2)


def test_camera_and_toggle_delegation(
    view: View3DWidget, fake_renderer: FakeSceneRenderer
) -> None:  # VIS-01/02
    view.preset_view(PresetView.TOP)
    view.set_axes_visible(False)
    view.set_labels_visible(True)
    view.reset_camera()
    assert fake_renderer.preset_calls == [PresetView.TOP]
    assert fake_renderer.axes_calls[-1] is False
    assert fake_renderer.labels_calls[-1] is True
    assert fake_renderer.reset_calls == 1


def test_fallback_when_backend_unavailable(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(view3d_module, "try_create_scene", lambda parent=None: (None, "no GL here"))
    widget = View3DWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    assert widget.is_active() is False
    assert widget.fallback_label is not None
    assert "no GL here" in widget.fallback_label.text()


def test_markers_and_slices_toggles(view: View3DWidget, fake_renderer: FakeSceneRenderer) -> None:
    space = _space()
    view.update_volume(_result(space), space, [])
    view.set_slices([SliceSpec(spec_id="z1", axis=SliceAxis.Z, position=0.5)])
    shown = [call[0] for call in fake_renderer.slice_calls]
    assert "z1" in shown
    view.set_slices_visible(False)
    assert not view.slices_visible()
    view.set_markers_visible(False)
    assert view.markers_visible() is False
    assert fake_renderer.marker_calls[-1] == (0, -1)


def test_limits_add_highlight_surface(
    view: View3DWidget, fake_renderer: FakeSceneRenderer
) -> None:  # SLC-07
    space = _space()
    view.update_volume(_result(space), space, [])
    view.set_slices([SliceSpec(spec_id="z1", axis=SliceAxis.Z, position=0.5)])
    view.set_limits((0.0, 2.0))
    keys = [call[0] for call in fake_renderer.slice_calls]
    assert "z1:limits" in keys


def test_outline_toggle_and_screenshot(
    view: View3DWidget, fake_renderer: FakeSceneRenderer, tmp_path
) -> None:
    view.set_outline_visible(False)
    assert fake_renderer.space_visible_calls[-1] is False
    target = tmp_path / "shot.png"
    assert view.save_screenshot(target) is True
    assert target.exists()
    assert fake_renderer.screenshot_calls == [str(target)]
