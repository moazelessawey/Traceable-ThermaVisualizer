"""Logger-to-column mapping helpers (DAT-04 auto-suggest, DAT-05 duplicates).

Pure Python, headless (no Qt). A mapping links each configured logger to a
temperature column (required) and an optional humidity column in a loaded file.
"""

from __future__ import annotations

from collections.abc import Sequence

from thermavisualizer.core.models import (
    ColumnType,
    LoggerMapping,
    ParsedFile,
    Quantity,
)


def suggest_logger_mappings(
    logger_ids: Sequence[str], files: Sequence[ParsedFile]
) -> list[LoggerMapping]:
    """Suggest one mapping per logger by matching logger IDs in column names (DAT-04).

    For each logger ID, scan every file's NUMERIC columns (case-insensitive
    substring match). The first unused matching column becomes the temperature
    column. Loggers with no match get an empty (unmapped) mapping. Results are
    suggestions only; the user can override every assignment.
    """
    mappings: list[LoggerMapping] = []
    taken: set[tuple[str, str]] = set()
    for logger_id in logger_ids:
        needle = logger_id.strip().lower()
        mapping = LoggerMapping(logger_id=logger_id)
        if needle:
            for file in files:
                for column in file.columns:
                    if column.column_type is not ColumnType.NUMERIC:
                        continue
                    key = (file.path, column.name)
                    if key in taken:
                        continue
                    if needle in column.name.strip().lower():
                        mapping.temperature_file = file.path
                        mapping.temperature_column = column.name
                        taken.add(key)
                        break
                if mapping.has_temperature():
                    break
        mappings.append(mapping)
    return mappings


def find_duplicate_column_mappings(
    mappings: Sequence[LoggerMapping],
) -> list[tuple[str, str, Quantity, list[str]]]:
    """Return columns claimed by more than one logger (DAT-05 warnings).

    Each item is ``(file, column, quantity, logger_ids)``. Excluded mappings
    are ignored. A column mapped once per quantity is not a duplicate.
    """
    usage: dict[tuple[str, str, Quantity], list[str]] = {}
    for mapping in mappings:
        if mapping.excluded:
            continue
        if mapping.has_temperature():
            usage.setdefault(
                (mapping.temperature_file, mapping.temperature_column, Quantity.TEMPERATURE),
                [],
            ).append(mapping.logger_id)
        if mapping.has_humidity():
            usage.setdefault(
                (mapping.humidity_file, mapping.humidity_column, Quantity.HUMIDITY),
                [],
            ).append(mapping.logger_id)
    return [
        (file, column, quantity, ids)
        for (file, column, quantity), ids in usage.items()
        if len(ids) > 1
    ]
