"""Layout & footprint IO tests (BLK-01, BLK-02, GEO-05)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from thermavisualizer.core.geometry import validate_footprint
from thermavisualizer.core.models import ConfigurationError, PolygonFootprint
from thermavisualizer.io.layout_io import (
    LAYOUT_COLUMNS,
    LayoutIOError,
    LayoutMapping,
    export_layout,
    file_sha256,
    parse_layout_records,
    read_footprint_vertices,
    read_layout_table,
    records_to_layers,
    suggest_mapping,
    write_layout_template,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def test_read_csv_table() -> None:
    table = read_layout_table(DATA / "layout_valid.csv")
    assert table.columns == ("ID", "X", "Y", "Z", "Layer", "Notes")
    assert len(table.rows) == 6
    assert table.rows[0][0] == "L1"


def test_suggest_mapping_with_aliases() -> None:
    columns = ("Logger ID", "X (m)", "Y (m)", "Height", "Level", "Comment")
    mapping = suggest_mapping(columns)
    assert mapping.logger_id == "Logger ID"
    assert mapping.x == "X (m)"
    assert mapping.y == "Y (m)"
    assert mapping.z == "Height"
    assert mapping.layer == "Level"
    assert mapping.notes == "Comment"


def test_parse_valid_records_and_layers() -> None:
    table = read_layout_table(DATA / "layout_valid.csv")
    records, issues = parse_layout_records(table, suggest_mapping(table.columns))
    assert issues == []
    assert len(records) == 6
    assert records[0].x == pytest.approx(0.5)
    assert records[4].notes == "corner"
    layers = records_to_layers(records)
    assert [layer.name for layer in layers] == ["low", "high"]
    assert layers[0].height == pytest.approx(0.5)
    assert layers[1].height == pytest.approx(1.5)
    assert len(layers[0].loggers) == 4
    assert len(layers[1].loggers) == 2


def test_parse_reports_row_errors() -> None:
    table = read_layout_table(DATA / "layout_errors.csv")
    records, issues = parse_layout_records(table, suggest_mapping(table.columns))
    assert [record.logger_id for record in records] == ["L1"]
    by_row = {issue.row: issue.code for issue in issues}
    assert by_row[2] == "duplicate-id"
    assert by_row[3] == "missing-id"
    assert by_row[4] == "invalid-number"
    assert by_row[5] == "missing-coordinate"


def test_parse_flags_duplicates_against_existing_ids() -> None:
    table = read_layout_table(DATA / "layout_valid.csv")
    records, issues = parse_layout_records(
        table, suggest_mapping(table.columns), existing_ids=frozenset({"L3"})
    )
    assert len(records) == 5
    assert any(issue.code == "duplicate-id" and issue.row == 3 for issue in issues)


def test_parse_requires_required_mappings() -> None:
    table = read_layout_table(DATA / "layout_valid.csv")
    with pytest.raises(LayoutIOError):
        parse_layout_records(table, LayoutMapping(logger_id="ID"))


def test_semicolon_delimiter_and_decimal_comma() -> None:
    table = read_layout_table(DATA / "layout_semicolon.csv")  # sniffed ';'
    assert table.columns[0] == "ID"
    records, issues = parse_layout_records(table, suggest_mapping(table.columns), decimal=",")
    assert issues == []
    assert records[0].x == pytest.approx(0.5)
    assert records[1].y == pytest.approx(0.5)


def test_xlsx_read(tmp_path: Path) -> None:
    source = read_layout_table(DATA / "layout_valid.csv")
    xlsx_path = tmp_path / "layout.xlsx"
    pd.DataFrame(source.rows, columns=list(source.columns)).to_excel(xlsx_path, index=False)
    table = read_layout_table(xlsx_path)
    assert table.columns == source.columns
    assert len(table.rows) == 6
    records, issues = parse_layout_records(table, suggest_mapping(table.columns))
    assert issues == []
    assert len(records) == 6


def test_csv_export_roundtrip(tmp_path: Path) -> None:
    table = read_layout_table(DATA / "layout_valid.csv")
    records, _ = parse_layout_records(table, suggest_mapping(table.columns))
    layers = records_to_layers(records)
    out = tmp_path / "out.csv"
    export_layout(out, layers)
    reread = read_layout_table(out)
    records_again, issues = parse_layout_records(reread, suggest_mapping(reread.columns))
    assert issues == []
    assert records_again == records


def test_xlsx_export_roundtrip(tmp_path: Path) -> None:
    table = read_layout_table(DATA / "layout_valid.csv")
    layers = records_to_layers(parse_layout_records(table, suggest_mapping(table.columns))[0])
    out = tmp_path / "out.xlsx"
    export_layout(out, layers)
    reread = read_layout_table(out)
    records_again, issues = parse_layout_records(reread, suggest_mapping(reread.columns))
    assert issues == []
    assert len(records_again) == 6


def test_template(tmp_path: Path) -> None:
    out = tmp_path / "template.csv"
    write_layout_template(out)
    table = read_layout_table(out)
    assert table.columns == LAYOUT_COLUMNS
    assert len(table.rows) == 1
    assert table.rows[0][0] == "L1"


def test_footprint_vertices_l_shape() -> None:
    vertices = read_footprint_vertices(DATA / "footprint_l_shape.csv")
    assert vertices == [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)]
    validate_footprint(PolygonFootprint(tuple(vertices)))  # simple: no raise


def test_footprint_bowtie_fails_validation() -> None:
    vertices = read_footprint_vertices(DATA / "footprint_bowtie.csv")
    with pytest.raises(ConfigurationError):
        validate_footprint(PolygonFootprint(tuple(vertices)))


def test_footprint_too_few_vertices(tmp_path: Path) -> None:
    path = tmp_path / "two.csv"
    path.write_text("x,y\n0,0\n1,1\n", encoding="utf-8")
    with pytest.raises(LayoutIOError):
        read_footprint_vertices(path)


def test_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("ID,X,Y,Z\n", encoding="utf-8")
    with pytest.raises(LayoutIOError):
        read_layout_table(path)


def test_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "hash.bin"
    path.write_bytes(b"thermavisualizer")
    assert file_sha256(path) == __import__("hashlib").sha256(b"thermavisualizer").hexdigest()
