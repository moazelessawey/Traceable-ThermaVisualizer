"""Background worker tests (AGENTS §4: off-thread work with progress/cancel)."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import ImportProfile
from thermavisualizer.services.workers import FunctionWorker, load_data_files

DATA = Path(__file__).resolve().parents[1] / "data"


def test_worker_reports_progress_and_result(qtbot: QtBot) -> None:
    def task(cancel_check, report_progress):
        report_progress(25)
        report_progress(100)
        return "done"

    worker = FunctionWorker(task)
    progress: list[int] = []
    worker.progress_changed.connect(progress.append)
    with qtbot.waitSignal(worker.result_ready, timeout=3000) as blocker:
        worker.start()
    assert blocker.args == ["done"]
    worker.wait()
    QApplication.processEvents()
    assert progress[-1] == 100


def test_worker_reports_errors(qtbot: QtBot) -> None:
    def task(cancel_check, report_progress):
        raise RuntimeError("boom")

    worker = FunctionWorker(task)
    with qtbot.waitSignal(worker.error_occurred, timeout=3000) as blocker:
        worker.start()
    assert "boom" in blocker.args[0]
    worker.wait()


def test_worker_cancel_is_cooperative(qtbot: QtBot) -> None:
    def task(cancel_check, report_progress):
        deadline = time.monotonic() + 2.0
        while not cancel_check() and time.monotonic() < deadline:
            time.sleep(0.01)
        return "late"

    worker = FunctionWorker(task)
    worker.start()
    worker.cancel()
    with qtbot.waitSignal(worker.work_cancelled, timeout=3000):
        worker.wait()


def test_load_data_files_reports_progress() -> None:
    jobs = [
        (DATA / "data_simple.csv", ImportProfile()),
        (
            DATA / "data_euro.csv",
            ImportProfile(
                delimiter=";",
                decimal=",",
                timestamp_column="Zeitstempel",
                timestamp_format="%d.%m.%Y %H:%M",
                timezone="Europe/Berlin",
            ),
        ),
    ]
    progress: list[int] = []
    results = load_data_files(jobs, lambda: False, progress.append)
    assert len(results) == 2
    assert all(result.parsed is not None for result in results)
    assert progress == [50, 100]


def test_load_data_files_cancels_between_files() -> None:
    jobs = [(DATA / "data_simple.csv", ImportProfile())]
    results = load_data_files(jobs, lambda: True, lambda percent: None)
    assert results == []
