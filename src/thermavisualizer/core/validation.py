"""Validation engine for imported data files and logger mappings (VAL-01..11).

Pure Python, headless (no Qt). Findings carry PRD codes and severities
(error / warning / info). Raw data is never modified (data-integrity rule).
Units: temperature °C, humidity %RH, timestamps naive-UTC.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from thermavisualizer.core.models import (
    ColumnType,
    ImportProfile,
    LoggerMapping,
    ParsedFile,
    Quantity,
    Severity,
)
from thermavisualizer.io.readers import ReaderError, TimestampError, read_data_file

_UNIT_LABELS = {Quantity.TEMPERATURE: "°C", Quantity.HUMIDITY: "%RH"}


@dataclass(frozen=True)
class ValidationFinding:
    """One validation result (PRD 5.3)."""

    severity: Severity
    code: str  # "VAL-01" .. "VAL-11"
    message: str
    file: str = ""
    column: str = ""


@dataclass(frozen=True)
class ValidationOptions:
    """Configurable validation thresholds (VAL-03..07)."""

    gap_multiple: float = 3.0
    nan_warning_pct: float = 5.0
    nan_error_pct: float = 50.0
    temperature_min: float = -80.0
    temperature_max: float = 150.0
    humidity_min: float = 0.0
    humidity_max: float = 100.0
    spike_delta: float = 10.0
    flatline_length: int = 10


@dataclass(frozen=True)
class ValidationReport:
    """Ordered collection of findings with convenience accessors."""

    findings: tuple[ValidationFinding, ...]

    def errors(self) -> list[ValidationFinding]:
        """All error findings."""
        return [f for f in self.findings if f.severity is Severity.ERROR]

    def warnings(self) -> list[ValidationFinding]:
        """All warning findings."""
        return [f for f in self.findings if f.severity is Severity.WARNING]

    def infos(self) -> list[ValidationFinding]:
        """All info findings."""
        return [f for f in self.findings if f.severity is Severity.INFO]

    def has_errors(self) -> bool:
        """True when at least one error finding exists."""
        return any(f.severity is Severity.ERROR for f in self.findings)

    def codes(self) -> set[str]:
        """Distinct VAL codes present."""
        return {f.code for f in self.findings}

    def to_csv_rows(self) -> tuple[tuple[str, ...], list[tuple[str, ...]]]:
        """Header and rows for the CSV/TXT report export (EXP-06)."""
        header = ("Severity", "Code", "File", "Column", "Message")
        rows = [(f.severity.value, f.code, f.file, f.column, f.message) for f in self.findings]
        return header, rows


# ------------------------------------------------------------ entry points


def validate_path(path: Path, profile: ImportProfile) -> tuple[ParsedFile | None, ValidationReport]:
    """Read a file and report structural problems (VAL-01, VAL-02).

    Returns ``(parsed, report)``; ``parsed`` is None when the file could not
    be read at all.
    """
    name = Path(path).name
    try:
        parsed = read_data_file(Path(path), profile)
    except TimestampError as error:
        return None, ValidationReport(
            (ValidationFinding(Severity.ERROR, "VAL-02", str(error), file=name),)
        )
    except ReaderError as error:
        return None, ValidationReport(
            (ValidationFinding(Severity.ERROR, "VAL-01", str(error), file=name),)
        )
    return parsed, ValidationReport(())


def validate_files(
    files: Sequence[ParsedFile],
    mappings: Sequence[LoggerMapping],
    options: ValidationOptions = ValidationOptions(),
) -> ValidationReport:
    """Run VAL-02..VAL-11 over parsed files and their logger mappings."""
    findings: list[ValidationFinding] = []
    for file in files:
        findings.extend(_check_timestamps(file))
        findings.extend(_check_intervals(file, options))
        findings.extend(_check_numeric_quality(file, options))
        findings.extend(_check_mapped_columns(file, mappings, options))
        findings.extend(_coverage_findings(file, mappings))
    findings.extend(_check_mapping_consistency(files, mappings))
    findings.extend(_check_time_overlap(files, mappings))
    return ValidationReport(tuple(findings))


# ----------------------------------------------------------- per-file checks


def _timestamp_column_name(file: ParsedFile) -> str:
    for column in file.columns:
        if column.column_type is ColumnType.TIMESTAMP:
            return column.name
    return ""


def _check_timestamps(file: ParsedFile) -> list[ValidationFinding]:
    """VAL-02: parseable, strictly increasing timestamps."""
    stamps = file.timestamp_array()
    if stamps is None:
        return [
            ValidationFinding(Severity.ERROR, "VAL-02", "timestamp column missing", file=file.name)
        ]
    column = _timestamp_column_name(file)
    findings: list[ValidationFinding] = []
    nat_count = int(np.count_nonzero(np.isnat(stamps)))
    if nat_count:
        findings.append(
            ValidationFinding(
                Severity.ERROR,
                "VAL-02",
                f"{nat_count} unparseable timestamp(s)",
                file=file.name,
                column=column,
            )
        )
    diffs = np.diff(stamps)
    duplicates = int(np.count_nonzero(diffs == np.timedelta64(0, "ns")))
    if duplicates:
        findings.append(
            ValidationFinding(
                Severity.ERROR,
                "VAL-02",
                f"{duplicates} duplicate timestamp(s)",
                file=file.name,
                column=column,
            )
        )
    out_of_order = int(np.count_nonzero(diffs < np.timedelta64(0, "ns")))
    if out_of_order:
        findings.append(
            ValidationFinding(
                Severity.ERROR,
                "VAL-02",
                f"{out_of_order} out-of-order timestamp(s)",
                file=file.name,
                column=column,
            )
        )
    return findings


def _format_seconds(delta: np.timedelta64) -> str:
    seconds = float(delta / np.timedelta64(1, "s"))
    return f"{seconds:.0f} s"


def _check_intervals(file: ParsedFile, options: ValidationOptions) -> list[ValidationFinding]:
    """VAL-03: gaps larger than N times the sampling interval."""
    stamps = file.timestamp_array()
    if stamps is None:
        return []
    diffs = np.diff(stamps)
    positive = diffs[diffs > np.timedelta64(0, "ns")]
    if positive.size < 2:
        return []
    interval_ns = float(np.median(positive.astype("int64")))
    threshold_ns = interval_ns * options.gap_multiple
    positive_ns = positive.astype("int64")
    gap_mask = positive_ns > threshold_ns
    count = int(gap_mask.sum())
    if count == 0:
        return []
    largest = np.timedelta64(int(positive_ns[gap_mask].max()), "ns")
    interval = np.timedelta64(int(interval_ns), "ns")
    return [
        ValidationFinding(
            Severity.WARNING,
            "VAL-03",
            f"{count} gap(s) larger than {options.gap_multiple:.0f}x the "
            f"{_format_seconds(interval)} interval; largest {_format_seconds(largest)}",
            file=file.name,
        )
    ]


def _check_numeric_quality(file: ParsedFile, options: ValidationOptions) -> list[ValidationFinding]:
    """VAL-04: non-numeric/empty/NaN counts and percentages per column."""
    findings: list[ValidationFinding] = []
    for column in file.columns:
        if column.column_type is not ColumnType.NUMERIC:
            continue
        nan_count = int(np.count_nonzero(np.isnan(column.values)))
        if nan_count == 0:
            continue
        pct = 100.0 * nan_count / max(file.row_count, 1)
        if pct >= options.nan_error_pct:
            severity = Severity.ERROR
        elif pct >= options.nan_warning_pct:
            severity = Severity.WARNING
        else:
            severity = Severity.INFO
        findings.append(
            ValidationFinding(
                severity,
                "VAL-04",
                f"{nan_count} of {file.row_count} values ({pct:.1f}%) are "
                f"non-numeric/empty in column '{column.name}'",
                file=file.name,
                column=column.name,
            )
        )
    return findings


def _mapped_quantities(
    file: ParsedFile, mappings: Sequence[LoggerMapping]
) -> dict[str, set[Quantity]]:
    """Columns of ``file`` mapped by loggers, with their quantities."""
    result: dict[str, set[Quantity]] = {}
    for mapping in mappings:
        if mapping.excluded:
            continue
        if mapping.temperature_file == file.path and mapping.temperature_column:
            result.setdefault(mapping.temperature_column, set()).add(Quantity.TEMPERATURE)
        if mapping.humidity_file == file.path and mapping.humidity_column:
            result.setdefault(mapping.humidity_column, set()).add(Quantity.HUMIDITY)
    return result


def _longest_equal_run(values: np.ndarray) -> int:
    """Longest run of identical consecutive values; NaN always breaks a run."""
    if values.size == 0:
        return 0
    equal = np.concatenate(([True], values[1:] == values[:-1]))
    starts = np.concatenate(([0], np.flatnonzero(~equal), [values.size]))
    return int(np.diff(starts).max())


def _check_mapped_columns(
    file: ParsedFile, mappings: Sequence[LoggerMapping], options: ValidationOptions
) -> list[ValidationFinding]:
    """VAL-05 ranges, VAL-06 spikes, VAL-07 flat lines on mapped columns."""
    findings: list[ValidationFinding] = []
    quantities = _mapped_quantities(file, mappings)
    for column_name, qtys in quantities.items():
        column = file.column(column_name)
        if column is None or column.column_type is not ColumnType.NUMERIC:
            continue  # VAL-09 / VAL-10 report these
        if len(qtys) != 1:
            continue  # conflicting quantities are reported by VAL-10
        quantity = next(iter(qtys))
        values = column.values
        label = _UNIT_LABELS[quantity]
        if quantity is Quantity.TEMPERATURE:
            low, high = options.temperature_min, options.temperature_max
        else:
            low, high = options.humidity_min, options.humidity_max
        out_of_range = int(np.count_nonzero((values < low) | (values > high)))
        if out_of_range:
            findings.append(
                ValidationFinding(
                    Severity.ERROR,
                    "VAL-05",
                    f"{out_of_range} value(s) outside plausible range "
                    f"[{low:.1f}, {high:.1f}] {label}",
                    file=file.name,
                    column=column_name,
                )
            )
        spikes = int(np.count_nonzero(np.abs(np.diff(values)) > options.spike_delta))
        if spikes:
            findings.append(
                ValidationFinding(
                    Severity.WARNING,
                    "VAL-06",
                    f"{spikes} jump(s) larger than {options.spike_delta:.1f} {label} "
                    "between consecutive samples",
                    file=file.name,
                    column=column_name,
                )
            )
        run = _longest_equal_run(values)
        if run >= options.flatline_length:
            findings.append(
                ValidationFinding(
                    Severity.WARNING,
                    "VAL-07",
                    f"flat line of {run} identical consecutive samples",
                    file=file.name,
                    column=column_name,
                )
            )
    return findings


def _coverage_findings(
    file: ParsedFile, mappings: Sequence[LoggerMapping]
) -> list[ValidationFinding]:
    """VAL-11: row count and coverage summary per mapped logger."""
    findings: list[ValidationFinding] = []
    stamps = file.timestamp_array()
    for mapping in mappings:
        if mapping.excluded:
            continue
        pairs: list[tuple[str, Quantity]] = []
        if mapping.temperature_file == file.path and mapping.temperature_column:
            pairs.append((mapping.temperature_column, Quantity.TEMPERATURE))
        if mapping.humidity_file == file.path and mapping.humidity_column:
            pairs.append((mapping.humidity_column, Quantity.HUMIDITY))
        for column_name, _ in pairs:
            column = file.column(column_name)
            if column is None or column.column_type is not ColumnType.NUMERIC:
                continue  # VAL-09 reports these
            finite = np.isfinite(column.values)
            valid = int(finite.sum())
            message = (
                f"'{mapping.logger_id}' <- '{file.name}:{column_name}': "
                f"{valid} of {file.row_count} samples valid"
            )
            if stamps is not None and valid:
                good = stamps[finite & ~np.isnat(stamps)]
                if good.size:
                    message += f", {good.min()} -> {good.max()}"
            findings.append(
                ValidationFinding(
                    Severity.INFO, "VAL-11", message, file=file.name, column=column_name
                )
            )
    return findings


# ---------------------------------------------------------- cross-file checks


def _check_mapping_consistency(
    files: Sequence[ParsedFile], mappings: Sequence[LoggerMapping]
) -> list[ValidationFinding]:
    """VAL-09 (missing/mapped/unmapped columns) and VAL-10 (duplicates, units)."""
    findings: list[ValidationFinding] = []
    by_path = {file.path: file for file in files}
    keys: dict[tuple[str, str, Quantity], list[str]] = {}
    pair_quantities: dict[tuple[str, str], set[Quantity]] = {}

    for mapping in mappings:
        if mapping.excluded:
            continue
        triples = (
            (mapping.temperature_file, mapping.temperature_column, Quantity.TEMPERATURE),
            (mapping.humidity_file, mapping.humidity_column, Quantity.HUMIDITY),
        )
        for file_ref, column_name, quantity in triples:
            if not file_ref or not column_name:
                continue
            keys.setdefault((file_ref, column_name, quantity), []).append(mapping.logger_id)
            pair_quantities.setdefault((file_ref, column_name), set()).add(quantity)
            file = by_path.get(file_ref)
            if file is None:
                findings.append(
                    ValidationFinding(
                        Severity.ERROR,
                        "VAL-09",
                        f"logger '{mapping.logger_id}' references file '{file_ref}' "
                        "which is not loaded",
                        file=file_ref,
                    )
                )
            elif file.column(column_name) is None:
                findings.append(
                    ValidationFinding(
                        Severity.ERROR,
                        "VAL-09",
                        f"logger '{mapping.logger_id}': column '{column_name}' not found "
                        f"in '{file.name}'",
                        file=file.name,
                        column=column_name,
                    )
                )

    for (file_ref, column_name, quantity), logger_ids in keys.items():
        if len(logger_ids) > 1:
            display = by_path[file_ref].name if file_ref in by_path else file_ref
            findings.append(
                ValidationFinding(
                    Severity.ERROR,
                    "VAL-10",
                    f"column '{column_name}' in '{display}' is mapped to multiple "
                    f"loggers ({', '.join(logger_ids)}) as {quantity.value}",
                    file=display,
                    column=column_name,
                )
            )
    for (file_ref, column_name), qtys in pair_quantities.items():
        if len(qtys) > 1:
            display = by_path[file_ref].name if file_ref in by_path else file_ref
            findings.append(
                ValidationFinding(
                    Severity.ERROR,
                    "VAL-10",
                    f"column '{column_name}' in '{display}' is mapped with conflicting "
                    "quantities (temperature and humidity)",
                    file=display,
                    column=column_name,
                )
            )

    units = {
        by_path[file_ref].temperature_unit
        for (file_ref, _, quantity) in keys
        if quantity is Quantity.TEMPERATURE and file_ref in by_path
    }
    if len(units) > 1:
        unit_list = ", ".join(sorted(unit.value for unit in units))
        findings.append(
            ValidationFinding(
                Severity.ERROR,
                "VAL-10",
                f"mapped temperature columns use mixed units: {unit_list}",
            )
        )

    used: dict[str, set[str]] = {}
    for file_ref, column_name, _ in keys:
        used.setdefault(file_ref, set()).add(column_name)
    for file in files:
        unused = [
            column.name
            for column in file.columns
            if column.column_type is ColumnType.NUMERIC
            and column.name not in used.get(file.path, set())
        ]
        if unused:
            findings.append(
                ValidationFinding(
                    Severity.INFO,
                    "VAL-09",
                    f"unmapped columns in '{file.name}': {', '.join(unused)}",
                    file=file.name,
                )
            )
    return findings


def _check_time_overlap(
    files: Sequence[ParsedFile], mappings: Sequence[LoggerMapping]
) -> list[ValidationFinding]:
    """VAL-08: common time window across mapped files."""
    mapped_refs = set()
    for mapping in mappings:
        if mapping.excluded:
            continue
        if mapping.temperature_file:
            mapped_refs.add(mapping.temperature_file)
        if mapping.humidity_file:
            mapped_refs.add(mapping.humidity_file)
    intervals: list[tuple[str, np.datetime64, np.datetime64]] = []
    for file in files:
        if file.path not in mapped_refs:
            continue
        stamps = file.timestamp_array()
        if stamps is None:
            continue
        valid = stamps[~np.isnat(stamps)]
        if valid.size == 0:
            continue
        intervals.append((file.name, valid.min(), valid.max()))
    if len(intervals) < 2:
        return []
    start = max(interval[1] for interval in intervals)
    end = min(interval[2] for interval in intervals)
    if start >= end:
        names = ", ".join(interval[0] for interval in intervals)
        return [
            ValidationFinding(
                Severity.WARNING,
                "VAL-08",
                f"mapped files share no common time period: {names}",
            )
        ]
    duration = _format_seconds(end - start)
    return [
        ValidationFinding(Severity.INFO, "VAL-08", f"common window {start} -> {end} ({duration})")
    ]
