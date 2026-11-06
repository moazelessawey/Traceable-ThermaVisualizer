"""M0 acceptance: window layout contract (PRD section 4, section 10 item 1)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QTabWidget, QToolBar, QFileDialog, QDialog

from thermavisualizer.core.models import Layer, Logger
from thermavisualizer.services.settings import AppSettings
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.ui.main_window import MAINTAINER_CREDIT, MainWindow
from thermavisualizer.ui.panels.configuration_panel import ConfigurationPanel
from thermavisualizer.ui.tabs.configuration import ConfigurationTab
from thermavisualizer.ui.widgets.range_slider import RangeSlider


def test_status_bar_credit(main_window: MainWindow) -> None:
    assert main_window.status_credit() == "Ready . " + MAINTAINER_CREDIT
    assert MAINTAINER_CREDIT == "Developed and maintained by Moaz El-Essawey"


def test_tabs_on_east_edge(main_window: MainWindow) -> None:
    tabs = main_window.tab_widget
    assert tabs.tabPosition() == QTabWidget.TabPosition.East
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Configuration",
        "3D View",
        "Plots",
        "Results",
        "Data",
    ]


def test_menu_bar_has_expected_menus(main_window: MainWindow) -> None:
    titles = [action.text() for action in main_window.menuBar().actions()]
    for expected in ("&File", "&Edit", "&View", "&Data", "&Tools", "&Help"):
        assert expected in titles


def test_toolbar_present(main_window: MainWindow) -> None:
    assert main_window.findChildren(QToolBar), "expected a toolbar below the menu bar"


def test_timeline_below_main_area(main_window: MainWindow) -> None:
    timeline = main_window.timeline
    assert isinstance(timeline.slider, RangeSlider)
    assert timeline.parent() is main_window.centralWidget()
    assert timeline.pos().y() > main_window.splitter.pos().y()


def test_window_title_contains_product_name(main_window: MainWindow) -> None:
    assert "ThermaVisualizer" in main_window.windowTitle()


def test_layout_persisted_on_close(main_window: MainWindow, app_settings: AppSettings) -> None:
    main_window.close()
    assert app_settings.window_geometry() is not None
    assert app_settings.splitter_state() is not None


def test_main_window_owns_project_model(main_window) -> None:
    model = main_window.model
    assert model.undo_stack.canUndo() is False
    model.apply(AddLayerCommand(model, Layer(name="window-test")))
    assert [layer.name for layer in model.space.layers] == ["window-test"]
    assert model.undo_stack.canUndo() is True


def test_configuration_tab_installed(main_window) -> None:
    assert isinstance(main_window.tab_widget.widget(0), ConfigurationTab)
    assert isinstance(main_window.control_panel.page_widget(0), ConfigurationPanel)
    assert main_window.control_panel.current_title() == "Configuration"


def test_load_progress_shown_in_status_bar(main_window) -> None:
    main_window.model.load_progress_changed.emit(42)
    assert "42%" in main_window.statusBar().currentMessage()


def test_timeline_wired_to_model(main_window) -> None:
    from thermavisualizer.services.timeline import TimelineController

    assert isinstance(main_window.timeline_controller, TimelineController)
    assert main_window.timeline.controller is main_window.timeline_controller


def test_project_actions_enabled(main_window) -> None:
    for action in (
        main_window._action_new,
        main_window._action_open,
        main_window._action_save,
        main_window._action_save_as,
        main_window._action_audit_viewer,
    ):
        assert action.isEnabled()


def test_window_title_reflects_study(main_window) -> None:  # STY-02
    from thermavisualizer.core.models import Study

    main_window.model.set_study(Study(title="My Study"))
    assert "My Study" in main_window.windowTitle()


def test_save_and_open_roundtrip(main_window, qtbot, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from thermavisualizer.core.models import Study
    from thermavisualizer.services.audit import AuditAction

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    main_window.model.set_study(Study(title="Roundtrip study"))
    target = tmp_path / "p.tmap"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "")),
    )
    main_window._on_save_project_as()
    qtbot.waitUntil(lambda: target.exists(), timeout=8000)
    qtbot.waitUntil(
        lambda: any(e.action is AuditAction.PROJECT_SAVE for e in main_window.model.audit.entries),
        timeout=8000,
    )
    main_window.model.set_study(Study(title="changed locally"))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "")),
    )
    main_window._on_open_project()
    qtbot.waitUntil(lambda: main_window.model.study().title == "Roundtrip study", timeout=8000)
    assert any(e.action is AuditAction.PROJECT_OPEN for e in main_window.model.audit.entries)

def test_all_tabs_are_real_widgets(main_window) -> None:
    from thermavisualizer.ui.tabs.placeholders import PlaceholderTab

    tabs = main_window.tab_widget
    assert tabs.count() == 5
    for index in range(tabs.count()):
        assert not isinstance(tabs.widget(index), PlaceholderTab)


def test_first_launch_prompts_for_user_name(
    qtbot, tmp_path, monkeypatch
) -> None:  # AUD-02
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QInputDialog

    from thermavisualizer.services.settings import AppSettings
    from thermavisualizer.ui.main_window import MainWindow

    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("Moaz E.", True))
    )
    window = MainWindow(settings=settings, recovery_path=tmp_path / "r.autosave")
    qtbot.addWidget(window)
    assert settings.user_name_asked() is True
    assert settings.user_name() == "Moaz E."
    assert window.model.audit.user_name == "Moaz E."


def test_status_bar_shows_selected_logger(main_window) -> None:  # PRD 4.1
    model = main_window.model
    layer = Layer(name="low", height=0.5)
    model.apply(AddLayerCommand(model, layer))
    model.apply(
        AddLoggersCommand(model, layer.layer_id, [Logger("L1", 0.1, 0.2, 0.5)])
    )
    model.select_logger("L1")
    assert "L1" in main_window.statusBar().currentMessage()


def test_autosave_writes_when_modified(main_window, qtbot) -> None:  # NFR reliability
    main_window.model.apply(AddLayerCommand(main_window.model, Layer(name="a")))
    assert main_window.model.is_modified()
    main_window._autosave()
    qtbot.waitUntil(lambda: main_window._recovery_path.exists(), timeout=8000)


def test_autosave_skips_clean_project(main_window) -> None:
    main_window._autosave()
    assert not main_window._recovery_path.exists()


def test_reset_camera_action_enabled(main_window) -> None:  # VIS-01
    assert main_window._action_reset_camera.isEnabled()
    main_window._action_reset_camera.trigger()  # no renderer offscreen: must not raise


def test_preferences_action_enabled_and_dialog_works(
    main_window, qtbot, tmp_path, monkeypatch
) -> None:  # AUD-02 / VIS-08
    from thermavisualizer.ui.dialogs import PreferencesDialog

    assert main_window._action_preferences.isEnabled()
    monkeypatch.setattr(
        PreferencesDialog, "exec",
        lambda self: self.accept() or QDialog.DialogCode.Accepted,
    )
    # defaults round-trip without changing state
    main_window._on_preferences()


def test_first_launch_starts_maximized(qtbot, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from thermavisualizer.services.settings import AppSettings
    from thermavisualizer.ui.main_window import MainWindow

    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    settings.set_user_name_asked()
    window = MainWindow(settings=settings, recovery_path=tmp_path / "r.autosave")
    qtbot.addWidget(window)
    assert window.should_start_maximized() is True