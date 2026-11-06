"""PDF study report (RPT-01..04): a slim, scientific, reviewer-friendly document.

Structure: minimal cover (logo + product title), contents, then numbered
chapters — study parameters, acceptance criteria, results summary, per-logger
results, excursions, figures, data quality, methods — ending with an approval
& sign-off page. Each chapter opens with a short plain-language note. Facts
are presented; the overall acceptance decision is intentionally left to the
reviewer. Figures render on landscape pages at near-full size. No Qt /
matplotlib / OpenGL imports (AGENTS §4); figures arrive as pre-rendered PNG
bytes. Deterministic output for a given payload (RPT-04). Units: °C/%RH/metres.
"""

from __future__ import annotations

import io as _io
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import reportlab.rl_config as _rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from thermavisualizer.core.models import Quantity, Study
from thermavisualizer.core.results import AcceptanceCriteria, StudyResults

_BRAND = colors.HexColor("#1f4e79")
_BRAND_LIGHT = colors.HexColor("#e8eef6")
_RULE = colors.HexColor("#c9d1d9")
_TEXT = colors.HexColor("#24292f")
_MUTED = colors.HexColor("#6a737d")
_WARN_ORANGE = colors.HexColor("#b06000")
_FAIL_RED = colors.HexColor("#c62828")
_ZEBRA = colors.HexColor("#f4f7fb")
_ACCENT_RAMP = ("#440154", "#3b528b", "#21918c", "#5ec962", "#fde725")
_CREDIT = "Developed and maintained by Moaz El-Essawey"
_MARGIN = 16 * mm
_HEADER_BAND = 26 * mm
_FOOTER_BAND = 21 * mm
_PORTRAIT = A4
_LANDSCAPE = (A4[1], A4[0])
_CONTENT_WIDTH = A4[0] - 2 * _MARGIN
_LANDSCAPE_CONTENT_WIDTH = A4[1] - 2 * _MARGIN


class ReportSection(StrEnum):
    """Selectable report sections in render order (RPT-01, RPT-02)."""

    COVER = "cover"
    TOC = "toc"
    SETUP = "setup"
    CRITERIA = "criteria"
    RESULTS = "results"
    PER_LOGGER = "per_logger"
    EXCURSIONS = "excursions"
    FIGURES = "figures"
    DATA_QUALITY = "data_quality"
    METHODS = "methods"
    GLOSSARY = "glossary"
    AUDIT = "audit"
    VERSION = "version"
    SIGNOFF = "signoff"


DEFAULT_SECTIONS: tuple[ReportSection, ...] = (
    ReportSection.COVER,
    ReportSection.TOC,
    ReportSection.SETUP,
    ReportSection.CRITERIA,
    ReportSection.RESULTS,
    ReportSection.PER_LOGGER,
    ReportSection.EXCURSIONS,
    ReportSection.FIGURES,
    ReportSection.DATA_QUALITY,
    ReportSection.METHODS,
    ReportSection.SIGNOFF,
)

_TITLES: dict[ReportSection, str] = {
    ReportSection.TOC: "Contents",
    ReportSection.SETUP: "Study Parameters",
    ReportSection.CRITERIA: "Acceptance Criteria",
    ReportSection.RESULTS: "Results Summary",
    ReportSection.PER_LOGGER: "Per-Logger Results",
    ReportSection.EXCURSIONS: "Excursions",
    ReportSection.FIGURES: "Figures",
    ReportSection.DATA_QUALITY: "Data Quality",
    ReportSection.METHODS: "Methods",
    ReportSection.GLOSSARY: "Abbreviations & Glossary",
    ReportSection.AUDIT: "Audit Trail",
    ReportSection.VERSION: "Software & Environment",
    ReportSection.SIGNOFF: "Approval & Sign-off",
}

# One plain-language sentence per chapter so readers know how to read it.
_INTROS: dict[ReportSection, str] = {
    ReportSection.SETUP: "The space, logger layout, and data evaluated in this study.",
    ReportSection.CRITERIA: (
        "The limits each logger reading is compared against. Samples outside these "
        "limits are counted as out-of-limits; excursions are continuous out-of-limit "
        "periods. The overall acceptance decision is left to the reviewer."
    ),
    ReportSection.RESULTS: "Key observations across all evaluated loggers for the study period.",
    ReportSection.PER_LOGGER: (
        "Statistics computed per logger over the evaluation period. MKT (mean kinetic "
        "temperature) summarises the thermal stress experienced over time."
    ),
    ReportSection.EXCURSIONS: "Continuous periods during which a logger was outside the limits.",
    ReportSection.FIGURES: (
        "Spatial distributions interpolated between the logger positions. Values away "
        "from a logger are estimates; the method is stated in the Methods chapter."
    ),
    ReportSection.DATA_QUALITY: "Findings raised while validating the loaded data files.",
    ReportSection.METHODS: "How values between logger positions were estimated.",
    ReportSection.GLOSSARY: "Definitions of the terms used in this report.",
    ReportSection.AUDIT: "Appendix: the recorded user actions for this project.",
    ReportSection.VERSION: "Appendix: software versions used to generate this report.",
    ReportSection.SIGNOFF: "Review and approval of this report.",
}

_ORIENTATION: dict[ReportSection, str] = {
    ReportSection.COVER: "portrait",
    ReportSection.TOC: "portrait",
    ReportSection.SETUP: "portrait",
    ReportSection.CRITERIA: "portrait",
    ReportSection.RESULTS: "portrait",
    ReportSection.PER_LOGGER: "portrait",
    ReportSection.EXCURSIONS: "portrait",
    ReportSection.FIGURES: "landscape",
    ReportSection.DATA_QUALITY: "landscape",
    ReportSection.METHODS: "portrait",
    ReportSection.GLOSSARY: "portrait",
    ReportSection.AUDIT: "landscape",
    ReportSection.VERSION: "portrait",
    ReportSection.SIGNOFF: "portrait",
}

_APPENDICES = frozenset({ReportSection.AUDIT, ReportSection.VERSION})
_KEEP_TOGETHER = frozenset({
    ReportSection.CRITERIA, ReportSection.RESULTS, ReportSection.METHODS,
    ReportSection.SIGNOFF,
})


# ------------------------------------------------------------------- payload


@dataclass(frozen=True)
class ReportFigure:
    """One embedded figure. ``estimated`` marks interpolated content (RPT-03)."""

    caption: str
    png_bytes: bytes
    estimated: bool = False
    method: str = ""


@dataclass(frozen=True)
class ReportOptions:
    """Report configuration (RPT-02): title, logo, author, section order."""

    title: str = "Thermal Mapping Study Report"
    author: str = ""
    logo_png: bytes | None = None
    sections: tuple[ReportSection, ...] = DEFAULT_SECTIONS


@dataclass(frozen=True)
class SpaceSummary:
    """Structured space facts for the study-parameters chapter. Units: metres."""

    name: str
    space_type: str
    footprint_kind: str
    footprint_bounds: str
    height: float


@dataclass(frozen=True)
class LayerInfo:
    """One configured layer. Units: metres."""

    name: str
    height: float
    logger_count: int
    completed: bool


@dataclass(frozen=True)
class ObstacleInfo:
    """One obstacle row (position/size pre-formatted in metres)."""

    name: str
    obstacle_type: str
    shape: str
    position: str
    size: str
    solid: bool
    visible: bool


@dataclass(frozen=True)
class FileInfo:
    """One loaded data file."""

    name: str
    profile: str
    rows: int
    columns: int


@dataclass(frozen=True)
class MappingSummary:
    """Logger-to-column mapping completeness counts."""

    loggers_total: int
    temperature_mapped: int
    humidity_mapped: int
    excluded: int
    unmapped: int


@dataclass(frozen=True)
class AlignedSummary:
    """Aligned dataset facts. Units: seconds for the interval; UTC timestamps."""

    quantity: str
    start_utc: str
    end_utc: str
    samples: int
    interval_seconds: float


@dataclass(frozen=True)
class ValidationRow:
    """One validation finding row."""

    severity: str
    code: str
    file: str
    column: str
    message: str


@dataclass(frozen=True)
class ProcessingSummary:
    """Interpolation settings (units: metres for resolution/sigma)."""

    method: str
    idw_power: float
    rbf_kernel: str
    extrapolation: str
    resolution: float
    smoothing_sigma: float
    aggregation: str = ""


@dataclass(frozen=True)
class ReportPayload:
    """All content needed to render the report (assembled by services)."""

    study: Study
    criteria: AcceptanceCriteria
    results: StudyResults | None
    quantity: Quantity
    space: SpaceSummary
    layers: tuple[LayerInfo, ...]
    obstacles: tuple[ObstacleInfo, ...]
    data_files: tuple[FileInfo, ...]
    mapping: MappingSummary
    aligned: AlignedSummary | None
    validation_rows: tuple[ValidationRow, ...]
    validation_summary: str
    processing: ProcessingSummary
    figures: tuple[ReportFigure, ...] = ()
    audit_lines: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()
    app_version: str = ""
    generated_utc: str = ""


# ------------------------------------------------------------------ styling


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "product": ParagraphStyle(
            "product", parent=base["Title"], fontSize=26, leading=31,
            textColor=_BRAND, alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["BodyText"], fontSize=11, leading=14,
            textColor=_TEXT, alignment=TA_CENTER,
        ),
        "coverline": ParagraphStyle(
            "coverline", parent=base["BodyText"], fontSize=8.5, leading=11,
            textColor=_MUTED, alignment=TA_CENTER,
        ),
        "chapter": ParagraphStyle(
            "chapter", parent=base["Heading1"], fontSize=13.5, leading=17,
            textColor=_BRAND, fontName="Helvetica-Bold", spaceBefore=0, spaceAfter=4,
        ),
        "chapter_toc": ParagraphStyle(
            "chapter_toc", parent=base["Heading1"], fontSize=13.5, leading=17,
            textColor=_BRAND, fontName="Helvetica-Bold", spaceBefore=0, spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "sub", parent=base["Heading2"], fontSize=10, leading=13,
            textColor=_BRAND, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=3,
        ),
        "intro": ParagraphStyle(
            "intro", parent=base["BodyText"], fontSize=8.5, leading=11.5,
            textColor=_MUTED, fontName="Helvetica-Oblique", spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontSize=9, leading=12.5,
            textColor=_TEXT, spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontSize=7.5, leading=10,
            textColor=_MUTED,
        ),
    }


def _table(rows: list[list[str]], header: bool = True) -> Table:
    table = Table(rows, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), _TEXT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), _BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    if len(rows) > 2:
        style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]))
    table.setStyle(TableStyle(style))
    return table


def _kv_table(pairs: list[tuple[str, str]]) -> Table:
    table = Table([["Field", "Value"]] + [[k, v] for k, v in pairs], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), _TEXT),
        ("BACKGROUND", (0, 0), (-1, 0), _BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (0, -1), _BRAND_LIGHT),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _ramp_bar(width: float) -> Table:
    ramp = Table([["", "", "", "", ""]], colWidths=[width / 5.0] * 5, rowHeights=[2.6 * mm])
    style = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    for index, hex_value in enumerate(_ACCENT_RAMP):
        style.append(("BACKGROUND", (index, 0), (index, 0), colors.HexColor(hex_value)))
    ramp.setStyle(TableStyle(style))
    return ramp


def _note_box(lines: list[str]) -> Table:
    box = Table(
        [[Paragraph("<br/>".join(lines), ParagraphStyle(
            "note_inner", fontSize=7.5, leading=10, textColor=_TEXT,
        ))]],
        colWidths=[_CONTENT_WIDTH],
    )
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, _BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return box


def _unit(quantity: Quantity) -> str:
    return "°C" if quantity is Quantity.TEMPERATURE else "%RH"


# ------------------------------------------------------------- page chrome


class _ReportDoc(BaseDocTemplate):
    """Document template that tracks chapter pages and writes PDF bookmarks."""

    def __init__(self, filename, templates, title: str, author: str, probe: bool):
        super().__init__(filename, pageTemplates=templates, title=title, author=author)
        self._probe = probe
        self._chapter_hits: list[tuple[str, int]] = []
        self._current_chapter = ""

    def afterFlowable(self, flowable) -> None:  # noqa: N802 - reportlab hook
        if isinstance(flowable, Paragraph) and flowable.style.name == "chapter":
            title = flowable.getPlainText()
            self._current_chapter = title
            index = len(self._chapter_hits)
            self._chapter_hits.append((title, self.page))
            if not self._probe:
                key = f"chapter-{index}"
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(title, key, level=0, closed=False)


def _draw_chrome(canvas, doc, options: ReportOptions, payload: ReportPayload,
                 total_pages: int, page_size: tuple[float, float]) -> None:
    """Header (logo mark, report title, current chapter) + footer (credit, page)."""
    canvas.saveState()
    width, height = page_size

    x = _MARGIN
    drew_logo = False
    if options.logo_png:
        try:
            reader = ImageReader(_io.BytesIO(options.logo_png))
            image_width, image_height = reader.getSize()
            logo_height = 8 * mm
            logo_width = logo_height * image_width / max(image_height, 1)
            canvas.drawImage(
                reader, x, height - 14.5 * mm, width=logo_width, height=logo_height,
                mask="auto", preserveAspectRatio=True,
            )
            x += logo_width + 4 * mm
            drew_logo = True
        except Exception:  # invalid logo bytes: fall back to the motif
            drew_logo = False
    if not drew_logo:
        square = 2.6 * mm
        for index, hex_value in enumerate(_ACCENT_RAMP):
            canvas.setFillColor(colors.HexColor(hex_value))
            canvas.roundRect(
                x + index * (square + 0.9 * mm), height - 14.5 * mm, square, square,
                0.5 * mm, stroke=0, fill=1,
            )
        x += 5 * (square + 0.9 * mm) + 3 * mm

    canvas.setFillColor(_BRAND)
    canvas.setFont("Helvetica-Bold", 10.5)
    canvas.drawString(x, height - 12 * mm, options.title[:88])
    if payload.study.title:
        canvas.setFillColor(colors.HexColor("#444d56"))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(x, height - 15.5 * mm, payload.study.title[:88])
    chapter = getattr(doc, "_current_chapter", "")
    if chapter:
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(width - _MARGIN, height - 12 * mm, chapter[:70])
    canvas.setStrokeColor(_BRAND)
    canvas.setLineWidth(1.0)
    canvas.line(_MARGIN, height - 19 * mm, width - _MARGIN, height - 19 * mm)

    canvas.setStrokeColor(_RULE)
    canvas.setLineWidth(0.6)
    canvas.line(_MARGIN, 15 * mm, width - _MARGIN, 15 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#57606a"))
    canvas.drawString(_MARGIN, 10.5 * mm, _CREDIT)
    if payload.generated_utc:
        canvas.drawCentredString(width / 2.0, 10.5 * mm,
                                 f"Generated {payload.generated_utc} (UTC)")
    canvas.drawRightString(width - _MARGIN, 10.5 * mm,
                           f"Page {canvas.getPageNumber()} of {total_pages}")
    canvas.restoreState()


def _make_chrome(options, payload, total_pages, page_size):
    def chrome(canvas, doc) -> None:
        _draw_chrome(canvas, doc, options, payload, total_pages, page_size)

    return chrome


def _make_document(target, options, payload, total_pages: int,
                   first_orientation: str, probe: bool) -> _ReportDoc:
    frame_p = Frame(_MARGIN, _FOOTER_BAND, _PORTRAIT[0] - 2 * _MARGIN,
                    _PORTRAIT[1] - _HEADER_BAND - _FOOTER_BAND, id="frame_p")
    frame_l = Frame(_MARGIN, _FOOTER_BAND, _LANDSCAPE[0] - 2 * _MARGIN,
                    _LANDSCAPE[1] - _HEADER_BAND - _FOOTER_BAND, id="frame_l")
    portrait = PageTemplate(
        id="portrait", frames=[frame_p], pagesize=_PORTRAIT,
        onPage=_make_chrome(options, payload, total_pages, _PORTRAIT),
    )
    landscape = PageTemplate(
        id="landscape", frames=[frame_l], pagesize=_LANDSCAPE,
        onPage=_make_chrome(options, payload, total_pages, _LANDSCAPE),
    )
    templates = (
        [landscape, portrait] if first_orientation == "landscape" else [portrait, landscape]
    )
    return _ReportDoc(target, templates, options.title, options.author, probe=probe)


# --------------------------------------------------------------- chapter map


def _chapter_labels(sections: tuple[ReportSection, ...]) -> dict[ReportSection, str]:
    """Number chapters/appendices in render order (stable per options)."""
    labels: dict[ReportSection, str] = {}
    chapter = 0
    appendix = 0
    for section in sections:
        if section is ReportSection.COVER:
            continue
        if section in _APPENDICES:
            appendix += 1
            labels[section] = f"Appendix {chr(64 + appendix)} — {_TITLES[section]}"
        elif section in (ReportSection.TOC, ReportSection.SIGNOFF):
            labels[section] = _TITLES[section]
        else:
            chapter += 1
            labels[section] = f"{chapter}. {_TITLES[section]}"
    return labels


def _toc_rows(labels, sections, pages: list[int] | None) -> list[list[str]]:
    rows: list[list[str]] = []
    page_index = 0
    for section in sections:
        if section in (ReportSection.COVER, ReportSection.TOC):
            continue
        page = "?" if pages is None else str(pages[page_index])
        page_index += 1
        rows.append([labels[section], page])
    return rows


# ------------------------------------------------------------------ sections


def _cover_flows(options, payload, styles) -> list:
    flows: list = [Spacer(1, 24 * mm)]
    if options.logo_png:
        try:
            logo = Image(_io.BytesIO(options.logo_png))
            logo._restrictSize(70 * mm, 48 * mm)
            logo.hAlign = "CENTER"
            flows.append(logo)
        except Exception:  # invalid logo bytes: use the built-in motif
            ramp = _ramp_bar(72 * mm)
            ramp.hAlign = "CENTER"
            flows.append(ramp)
    else:
        ramp = _ramp_bar(72 * mm)
        ramp.hAlign = "CENTER"
        flows.append(ramp)
    flows.append(Spacer(1, 12 * mm))
    flows.append(Paragraph("Traceable.ThermaVisualizer", styles["product"]))
    flows.append(Spacer(1, 4 * mm))
    flows.append(Paragraph(options.title, styles["subtitle"]))
    if payload.study.title:
        flows.append(Spacer(1, 2 * mm))
        flows.append(Paragraph(payload.study.title, styles["coverline"]))
    flows.append(Spacer(1, 30 * mm))
    if payload.generated_utc:
        flows.append(Paragraph(f"Generated {payload.generated_utc} (UTC)",
                               styles["coverline"]))
    flows.append(Paragraph(_CREDIT, styles["coverline"]))
    return flows


def _setup_flows(payload, label, styles) -> list:
    flows: list = []
    prefix = label.split(".", 1)[0] if "." in label else ""

    def sub(text: str, index: int) -> Paragraph:
        return Paragraph(f"{prefix}.{index} {text}" if prefix else text, styles["sub"])

    space = payload.space
    flows.append(sub("Space", 1))
    flows.append(_kv_table([
        ["Space name", space.name],
        ["Space type", space.space_type],
        ["Footprint", f"{space.footprint_kind} — {space.footprint_bounds}"],
        ["Height", f"{space.height:.2f} m"],
    ]))
    flows.append(sub("Layers & loggers", 2))
    if payload.layers:
        rows = [["Layer", "Height (m)", "Loggers"]]
        for layer in payload.layers:
            rows.append([layer.name, f"{layer.height:.2f}", str(layer.logger_count)])
        rows.append(["Total", "", str(sum(l.logger_count for l in payload.layers))])
        flows.append(_table(rows))
    else:
        flows.append(Paragraph("No layers configured.", styles["body"]))
    flows.append(sub("Obstacles & reference objects", 3))
    if payload.obstacles:
        rows = [["Name", "Type", "Position", "Size"]]
        for obstacle in payload.obstacles:
            rows.append([obstacle.name, obstacle.obstacle_type, obstacle.position,
                         obstacle.size])
        flows.append(_table(rows))
    else:
        flows.append(Paragraph("No obstacles configured.", styles["body"]))
    flows.append(sub("Data & coverage", 4))
    if payload.data_files:
        rows = [["File", "Profile", "Rows", "Columns"]]
        for file in payload.data_files:
            rows.append([file.name, file.profile, str(file.rows), str(file.columns)])
        flows.append(_table(rows))
    else:
        flows.append(Paragraph("No data files loaded.", styles["body"]))
    mapping = payload.mapping
    flows.append(Paragraph(
        f"{mapping.temperature_mapped} of {mapping.loggers_total} loggers provide "
        f"temperature data ({mapping.humidity_mapped} also humidity); "
        f"{mapping.excluded} excluded, {mapping.unmapped} unmapped.", styles["body"],
    ))
    if payload.aligned is not None:
        aligned = payload.aligned
        flows.append(Paragraph(
            f"Recordings cover {aligned.start_utc} to {aligned.end_utc} UTC "
            f"({aligned.samples} samples per logger at "
            f"{aligned.interval_seconds:.0f}-second intervals).", styles["body"],
        ))
    return flows


def _criteria_flows(payload, styles) -> list:
    criteria = payload.criteria
    unit = _unit(payload.quantity)
    humidity = (
        "not defined"
        if criteria.humidity_min is None or criteria.humidity_max is None
        else f"{criteria.humidity_min} to {criteria.humidity_max} %RH"
    )
    return [_kv_table([
        ["Criteria name", criteria.name],
        [f"Temperature limits ({unit})",
         f"{criteria.temperature_min} to {criteria.temperature_max}"],
        ["Humidity limits", humidity],
    ])]


def _results_flows(payload, styles) -> list:
    results = payload.results
    if results is None:
        return [Paragraph("No results were computed for this study.", styles["body"])]
    o = results.overall
    unit = _unit(payload.quantity)
    out_of_limit_loggers = sum(1 for lr in results.logger_results if not lr.passed)
    out_of_limit_samples = sum(lr.out_of_limits_samples for lr in results.logger_results)
    total_duration = sum(ex.duration_seconds for ex in results.excursions)
    return [_kv_table([
        ["Evaluation period", f"{results.period_start} to {results.period_end} (UTC)"],
        ["Loggers evaluated", str(len(results.logger_results))],
        ["Hottest location", f"{o.hottest_logger} — {o.hottest_value:.2f} {unit} "
                             f"at {o.hottest_time}"],
        ["Coldest location", f"{o.coldest_logger} — {o.coldest_value:.2f} {unit} "
                             f"at {o.coldest_time}"],
        ["Largest spatial spread", f"{o.largest_spread:.2f} {unit} at "
                                   f"{o.largest_spread_time}"],
        ["Samples outside limits", f"{out_of_limit_samples} across "
                                   f"{out_of_limit_loggers} logger(s)"],
        ["Excursions", f"{len(results.excursions)} (total duration "
                       f"{total_duration:.0f} s)"],
    ])]


def _per_logger_flows(payload, styles) -> list:
    results = payload.results
    if results is None:
        return [Paragraph("No results were computed for this study.", styles["body"])]
    unit = _unit(payload.quantity)
    rows = [["Logger", f"Min ({unit})", f"Max ({unit})", f"Mean ({unit})",
             f"Std ({unit})", f"MKT ({unit})", "Out of limits %", "Excursions"]]
    for lr in results.logger_results:
        mkt = f"{lr.mkt:.2f}" if lr.mkt is not None else "—"
        rows.append([
            lr.logger_id, f"{lr.minimum:.2f}", f"{lr.maximum:.2f}",
            f"{lr.mean:.2f}", f"{lr.std:.2f}", mkt,
            f"{lr.out_of_limits_pct:.1f}", str(lr.excursion_count),
        ])
    flows = [_table(rows), Spacer(1, 1.5 * mm)]
    flows.append(Paragraph(
        "Statistics cover the evaluation period only; percentages refer to samples "
        "outside the acceptance limits.", styles["small"],
    ))
    return flows


def _excursions_flows(payload, styles) -> list:
    results = payload.results
    if results is None or not results.excursions:
        return [Paragraph(
            "No excursions were observed during the evaluation period.", styles["body"],
        )]
    unit = _unit(payload.quantity)
    rows = [["#", "Logger", "Kind", "Start (UTC)", "End (UTC)", "Duration (s)",
             f"Peak ({unit})"]]
    for index, ex in enumerate(results.excursions, start=1):
        rows.append([str(index), ex.logger_id, ex.kind.value, str(ex.start),
                     str(ex.end), f"{ex.duration_seconds:.0f}", f"{ex.peak:.2f}"])
    return [_table(rows)]


def _figures_flows(payload, styles, figure_counter: dict[str, int]) -> list:
    if not payload.figures:
        return [Paragraph("No figures are available for this study.", styles["body"])]
    flows: list = []
    for figure in payload.figures:
        figure_counter["figure"] += 1
        image = Image(_io.BytesIO(figure.png_bytes))
        image._restrictSize(_LANDSCAPE_CONTENT_WIDTH - 8 * mm, 136 * mm)
        image.hAlign = "CENTER"
        flows.append(image)
        caption = f"Figure {figure_counter['figure']}. {figure.caption}"
        if figure.estimated:  # RPT-03: label interpolated figures
            caption += (f" Interpolated estimate — method: {figure.method or 'n/a'}.")
        flows.append(Spacer(1, 1.5 * mm))
        flows.append(Paragraph(caption, styles["small"]))
        flows.append(Spacer(1, 3 * mm))
    return flows


def _data_quality_flows(payload, styles) -> list:
    flows = [Paragraph(payload.validation_summary, styles["body"]), Spacer(1, 1.5 * mm)]
    if not payload.validation_rows:
        flows.append(Paragraph("No data-quality findings were raised.", styles["body"]))
        return flows
    rows = [["Severity", "Code", "File", "Column", "Message"]]
    for row in payload.validation_rows:
        rows.append([row.severity.upper(), row.code, row.file, row.column, row.message])
    table = _table(rows)
    severity_colors = {"error": _FAIL_RED, "warning": _WARN_ORANGE, "info": _MUTED}
    commands = []
    for index, row in enumerate(payload.validation_rows):
        commands.append(("TEXTCOLOR", (0, index + 1), (0, index + 1),
                         severity_colors.get(row.severity, _TEXT)))
        commands.append(("FONTNAME", (0, index + 1), (0, index + 1), "Helvetica-Bold"))
    if commands:
        table.setStyle(TableStyle(commands))
    flows.append(table)
    return flows


def _methods_flows(payload, styles) -> list:
    processing = payload.processing
    rows = [
        ["Interpolation method", processing.method.upper()],
        ["Grid resolution", f"{processing.resolution} m"],
        ["Extrapolation policy", processing.extrapolation],
    ]
    if processing.method == "idw":
        rows.append(["IDW power", f"{processing.idw_power}"])
    if processing.method == "rbf":
        rows.append(["RBF kernel", processing.rbf_kernel])
    if processing.smoothing_sigma > 0:
        rows.append(["Spatial smoothing", f"Gaussian, sigma {processing.smoothing_sigma} m"])
    if processing.aggregation:
        rows.append(["Time aggregation", processing.aggregation])
    return [
        _kv_table(rows),
        Spacer(1, 2.5 * mm),
        _note_box([
            "Values shown between logger positions are interpolated estimates, not "
            f"measurements ({processing.method.upper()}).",
            "Raw logger data is never modified; alignment and interpolation are applied "
            "as separate processing steps.",
            f"Generated with Traceable.ThermaVisualizer {payload.app_version}.",
        ]),
    ]


_GLOSSARY = (
    ("MKT", "Mean kinetic temperature — a single derived temperature expressing the "
            "thermal stress experienced over time."),
    ("Excursion", "A continuous period during which a value is outside the acceptance limits."),
    ("IDW / RBF", "Inverse distance weighting / radial basis function interpolation methods."),
    ("Footprint", "The 2D outline (box or polygon) of the space, extruded to its height."),
    ("%RH", "Relative humidity in percent."),
)


def _glossary_flows(styles) -> list:
    return [_table([["Term", "Definition"]] + [[t, d] for t, d in _GLOSSARY])]


def _audit_flows(payload, styles) -> list:
    if not payload.audit_lines:
        return [Paragraph("No audit entries were recorded.", styles["body"])]
    rows = [["#", "Timestamp (UTC)", "User", "Action", "Target", "Summary"]]
    for line in payload.audit_lines:
        rows.append(line.split("\t"))
    return [_table(rows)]


def _version_flows(payload, styles) -> list:
    rows = [["Component", "Version"]]
    for line in payload.environment:
        name, _, version = line.partition(" ")
        rows.append([name, version or "—"])
    return [_table(rows)]


def _signoff_flows(options, payload, styles) -> list:
    flows: list = [
        _kv_table([
            ["Report", options.title],
            ["Study", payload.study.title or "—"],
            ["Protocol ID", payload.study.protocol_id or "—"],
            ["Generated (UTC)", payload.generated_utc or "—"],
        ]),
        Spacer(1, 5 * mm),
    ]
    signature_table = Table(
        [
            ["Role", "Name", "Signature", "Date"],
            ["Prepared by", payload.study.performed_by, "", ""],
            ["Reviewed by", payload.study.reviewer, "", ""],
            ["Approved by", "", "", ""],
        ],
        colWidths=[34 * mm, 46 * mm, 62 * mm, 32 * mm],
        rowHeights=[None, 16 * mm, 16 * mm, 16 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    signature_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, _RULE),
        ("BACKGROUND", (0, 0), (-1, 0), _BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
    ]))
    flows.append(signature_table)
    flows.append(Spacer(1, 4 * mm))
    flows.append(Paragraph(
        "Signatures confirm review of this report as generated. Interpolated values "
        "are estimates; the method is stated in the Methods chapter. The final "
        "acceptance decision rests with the reviewer.", styles["small"],
    ))
    return flows


# --------------------------------------------------------------------- story


def _section_flows(section, options, payload, styles, labels,
                   figure_counter: dict[str, int]) -> list:
    if section is ReportSection.COVER:
        return _cover_flows(options, payload, styles)
    label = labels.get(section, _TITLES.get(section, ""))
    heading_style = styles["chapter_toc"] if section is ReportSection.TOC else styles["chapter"]
    flows: list = [
        Paragraph(label, heading_style),
        HRFlowable(width="100%", thickness=0.8, color=_BRAND, spaceAfter=3),
    ]
    intro = _INTROS.get(section)
    if intro:
        flows.append(Paragraph(intro, styles["intro"]))
    if section is ReportSection.SETUP:
        flows.extend(_setup_flows(payload, label, styles))
    elif section is ReportSection.CRITERIA:
        flows.extend(_criteria_flows(payload, styles))
    elif section is ReportSection.RESULTS:
        flows.extend(_results_flows(payload, styles))
    elif section is ReportSection.PER_LOGGER:
        flows.extend(_per_logger_flows(payload, styles))
    elif section is ReportSection.EXCURSIONS:
        flows.extend(_excursions_flows(payload, styles))
    elif section is ReportSection.FIGURES:
        flows.extend(_figures_flows(payload, styles, figure_counter))
    elif section is ReportSection.DATA_QUALITY:
        flows.extend(_data_quality_flows(payload, styles))
    elif section is ReportSection.METHODS:
        flows.extend(_methods_flows(payload, styles))
    elif section is ReportSection.GLOSSARY:
        flows.extend(_glossary_flows(styles))
    elif section is ReportSection.AUDIT:
        flows.extend(_audit_flows(payload, styles))
    elif section is ReportSection.VERSION:
        flows.extend(_version_flows(payload, styles))
    elif section is ReportSection.SIGNOFF:
        flows.extend(_signoff_flows(options, payload, styles))
    if section in _KEEP_TOGETHER:
        return [KeepTogether(flows)]
    return flows


def _build_story(options, payload, toc_pages: list[int] | None) -> list:
    styles = _build_styles()
    labels = _chapter_labels(options.sections)
    figure_counter = {"figure": 0}
    story: list = []
    rendered = False
    for section in options.sections:
        if section is ReportSection.TOC:
            flows: list = [
                Paragraph(_TITLES[ReportSection.TOC], styles["chapter_toc"]),
                HRFlowable(width="100%", thickness=0.8, color=_BRAND, spaceAfter=4),
            ]
            rows = _toc_rows(labels, options.sections, toc_pages)
            toc_table = Table(rows, colWidths=[_CONTENT_WIDTH - 16 * mm, 16 * mm],
                              hAlign="LEFT")
            toc_table.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, -1), _TEXT),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flows.append(toc_table)
        else:
            flows = _section_flows(section, options, payload, styles, labels,
                                   figure_counter)
        if not flows:
            continue
        if rendered:
            story.append(NextPageTemplate(_ORIENTATION[section]))
            story.append(PageBreak())
        story.extend(flows)
        rendered = True
    if not story:
        story.append(Paragraph("No sections selected.", styles["body"]))
    return story


# ------------------------------------------------------------------ builder


def build_report_pdf(path: Path, options: ReportOptions, payload: ReportPayload) -> Path:
    """Render the report to ``path`` and return it (RPT-01/02/04).

    Two-pass build: pass one resolves contents page numbers and the total page
    count; pass two renders the final file with PDF bookmarks. Deterministic
    for identical options+payload.
    """
    _rl_config.invariant = 1        # deterministic IDs/timestamps (RPT-04)
    _rl_config.pageCompression = 0  # uncompressed streams: byte-stable and text-searchable
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sections = options.sections if options.sections else (ReportSection.COVER,)
    first_orientation = _ORIENTATION[sections[0]]

    probe = _make_document(_io.BytesIO(), options, payload, 0, first_orientation,
                           probe=True)
    probe.build(_build_story(options, payload, toc_pages=None))
    total_pages = max(probe.page, 1)
    toc_pages = [page for _title, page in probe._chapter_hits]

    document = _make_document(str(path), options, payload, total_pages,
                              first_orientation, probe=False)
    document.build(_build_story(options, payload, toc_pages=toc_pages))
    return path