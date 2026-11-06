"""PDF report assembly smoke tests (RPT-01..04)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from thermavisualizer.core.models import Quantity, Study
from thermavisualizer.core.results import AcceptanceCriteria, evaluate_dataset
from thermavisualizer.io.report import (
    ReportFigure,
    ReportOptions,
    ReportPayload,
    ReportSection,
    build_report_pdf,
    DEFAULT_SECTIONS,
    SpaceSummary, LayerInfo, ObstacleInfo, FileInfo, MappingSummary, AlignedSummary, ValidationRow, ProcessingSummary
)

def _payload() -> ReportPayload:
    times = np.datetime64("2024-03-01T08:00", "ns") + np.arange(4) * np.timedelta64(10, "m")
    values = np.array([[5.0], [6.0], [9.0], [5.5]])
    criteria = AcceptanceCriteria(name="2-8", temperature_min=2.0, temperature_max=8.0)
    results = evaluate_dataset(times, ("L1",), values, criteria, Quantity.TEMPERATURE)
    return ReportPayload(
        study=Study(title="Test study", protocol_id="P-1", performed_by="A. Person",
                    reviewer="B. Person"),
        criteria=criteria,
        results=results,
        quantity=Quantity.TEMPERATURE,
        space=SpaceSummary("WH-01", "warehouse", "box", "6.00 × 4.00 m", 3.0),
        layers=(LayerInfo("low", 0.5, 8, True), LayerInfo("high", 2.0, 8, False)),
        obstacles=(ObstacleInfo("rack", "rack", "box", "(1.00, 1.00, 1.00) m",
                                "1.00 × 1.00 × 2.00 m", True, True),),
        data_files=(FileInfo("data.csv", "Default", 288, 17),),
        mapping=MappingSummary(16, 16, 4, 0, 0),
        aligned=AlignedSummary("temperature", "2024-03-01T08:00:00",
                               "2024-03-02T08:00:00", 288, 600.0),
        validation_rows=(ValidationRow("warning", "VAL-03", "data.csv", "", "gap"),),
        validation_summary="0 error(s), 1 warning(s), 0 info finding(s).",
        processing=ProcessingSummary("idw", 2.0, "thin_plate_spline", "mask", 0.2, 0.0, "mean"),
        figures=(),
        audit_lines=("1\t2024-01-01T00:00:00Z\ttester\tproject_create\tproject\tcreate",),
        environment=("Python 3.11.9", "reportlab 4.0"),
        app_version="1.0.0-rc1",
        generated_utc="2024-03-01T12:00:00Z",
    )

def test_pdf_is_produced_with_metadata(tmp_path: Path) -> None:
    out = tmp_path / "report.pdf"
    result = build_report_pdf(out, ReportOptions(title="My report"), _payload())
    assert result == out
    assert out.exists() and out.stat().st_size > 0
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"My report" in data


def test_section_selection_respected(tmp_path: Path) -> None:  # RPT-02
    options = ReportOptions(sections=(ReportSection.COVER, ReportSection.VERSION))
    out = build_report_pdf(tmp_path / "short.pdf", options, _payload())
    assert out.exists()


def test_deterministic_output(tmp_path: Path) -> None:  # RPT-04
    payload = _payload()
    options = ReportOptions()
    a = build_report_pdf(tmp_path / "a.pdf", options, payload)
    b = build_report_pdf(tmp_path / "b.pdf", options, payload)
    assert a.read_bytes() == b.read_bytes()


def test_default_sections_end_with_signoff() -> None:

    assert DEFAULT_SECTIONS[-1] is ReportSection.SIGNOFF


def test_signoff_page_content(tmp_path: Path) -> None:
    out = build_report_pdf(
        tmp_path / "signoff.pdf",
        ReportOptions(sections=(ReportSection.COVER, ReportSection.SIGNOFF)),
        _payload(),
    )
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    for expected in (b"Approval", b"Prepared by", b"Reviewed by", b"Approved by"):
        assert expected in data


def test_landscape_sections_build(tmp_path: Path) -> None:  # wide tables + figures
    options = ReportOptions(sections=(
        ReportSection.COVER,
        ReportSection.PER_LOGGER,
        ReportSection.EXCURSIONS,
        ReportSection.FIGURES,
        ReportSection.AUDIT,
        ReportSection.SIGNOFF,
    ))
    out = build_report_pdf(tmp_path / "landscape.pdf", options, _payload())
    assert out.exists() and out.stat().st_size > 0
    assert b"Page 1 of" in out.read_bytes()


def test_single_landscape_first_section(tmp_path: Path) -> None:
    out = build_report_pdf(
        tmp_path / "only_figures.pdf",
        ReportOptions(sections=(ReportSection.FIGURES,)),
        _payload(),
    )
    assert out.exists() and out.stat().st_size > 0

def test_contents_pages_resolved(tmp_path: Path) -> None:
    data = build_report_pdf(
        tmp_path / "toc.pdf", ReportOptions(title="TOC check"), _payload()
    ).read_bytes()
    assert b"Contents" in data
    assert b"1. Study Parameters" in data


def test_structure_is_slim_and_scientific(tmp_path: Path) -> None:
    data = build_report_pdf(tmp_path / "full.pdf", ReportOptions(), _payload()).read_bytes()
    for expected in (
        b"Contents", b"1. Study Parameters", b"2. Acceptance Criteria",
        b"3. Results Summary", b"4. Per-Logger Results", b"5. Excursions",
        b"6. Figures", b"7. Data Quality", b"8. Methods", b"Approval",
    ):
        assert expected in data
    # software appendices are optional and must not appear by default
    assert b"Appendix" not in data


def test_cover_is_minimal_and_no_overall_verdict(tmp_path: Path) -> None:
    data = build_report_pdf(tmp_path / "cover.pdf", ReportOptions(), _payload()).read_bytes()
    assert b"Traceable.ThermaVisualizer" in data
    assert b"Overall study result" not in data  # decision left to the reviewer
    assert b"Document control" not in data      # no busywork tables on the cover


def test_audit_appendix_when_selected(tmp_path: Path) -> None:
    options = ReportOptions(sections=(ReportSection.COVER, ReportSection.AUDIT))
    data = build_report_pdf(tmp_path / "audit.pdf", options, _payload()).read_bytes()
    assert b"Appendix A" in data and b"project_create" in data