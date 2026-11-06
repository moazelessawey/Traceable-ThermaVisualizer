# Traceable.ThermaVisualizer — User Manual (v1.0.0-rc1)

## 1. Introduction
Traceable.ThermaVisualizer visualizes thermal mapping studies: you design the
logger layout, load data files, map loggers to columns, and explore the result
as an interpolated 3D heat map with slices, plots, timeline playback,
acceptance-criteria results, and exports.

The audit trail records who did what and when. It is a lightweight community
feature, **not** a regulatory-compliance (Part 11) claim.

## 2. Installation
- From source: `pip install -e .` (Python 3.11+), then `python -m thermavisualizer`.
- Binary: unzip the PyInstaller build (`dist/ThermaVisualizer`) and run the
  executable. An OpenGL 3.3-capable driver is required; without one, 3D views
  show a labeled fallback and Help ▸ Diagnostics explains what is missing.

## 3. Workflow
### 3.1 Design the layout (Configuration tab)
1. Set the space: name, type, dimensions, length unit; footprint is a box by
   default — switch to Polygon and edit vertices in the 2D editor (drag to
   move, click an edge to insert, Delete to remove).
2. Add layers (height in metres), place loggers by clicking (Add logger mode),
   dragging, the lattice generator, or Bulk layout ▸ Import layout… (CSV/XLSX).
3. Add obstacles (racks, doors, evaporators…). Mark an obstacle **solid** to
   exclude it from interpolation.
4. The 3D preview at the right updates live; every edit is undoable.

### 3.2 Load data (File ▸ Import Data / Data tab)
1. Choose files (CSV/TXT/XLSX) and an import profile (delimiter, decimal,
   header row, timestamp column/format, timezone, temperature unit); save
   profiles for reuse.
2. Preview rows and confirm column types, then map every logger to a file and
   column (temperature required, humidity optional) or exclude it. The app
   refuses to proceed while any logger is unmapped.
3. Validation findings (VAL-01..11) appear with severities and can be exported.

### 3.3 Explore (3D View + Timeline + Plots)
- 3D View: pick interpolation method/resolution, press **Compute & update
  view**. Slices (X/Y/Z/plane), color scale, limits highlight, axes/labels,
  and the probe are in the left panel; the canvas overlay (top-right) has
  camera presets, toggles, screenshot, and color settings. Interpolated values
  are estimates — the method is always shown.
- Timeline: drag the handles to select a range (drives 3D/plots/statistics),
  use play/pause/step/speed/loop; choose *Aggregate range* (default) or
  *Instant at playhead*.
- Plots: multi-select loggers, dual-axis or separate temperature/humidity,
  statistics table (min/max/mean/std/MKT), limit lines, hot/cold summary with
  nearby door/vent/evaporator context.

### 3.4 Results (Results tab)
Edit acceptance criteria (presets included), choose the evaluation scope
(timeline selection, full dataset, or named period), press **Evaluate**.
Per-logger and overall pass/fail, excursion tables, and CSV export are shown;
**Show limits in 3D** links the criteria to the 3D overlay.

### 3.5 Study metadata
The Results panel's Study group (title, protocol, equipment, location, type,
performer, reviewer, dates, notes) appears in the window title and stamps
exports.

### 3.6 Save, export, recover
- File ▸ Save Project writes one `.tmap` file containing layout, raw data,
  mapping, settings, results, view state, and the audit trail, with SHA-256
  integrity checks on open (tampering produces warnings).
- File ▸ Export: image (PNG/JPG), movie (MP4, GIF fallback), data (aligned
  CSV/XLSX, volume NPZ, slice CSV/PNG, validation CSV). All exports are
  audit-logged with hashes.
- The project autosaves every minute while modified; after a crash you are
  offered the recovery file on the next start.

## 4. Troubleshooting
| Symptom | Remedy |
| --- | --- |
| 3D view shows "unavailable" | OpenGL driver issue; see Help ▸ Diagnostics |
| `.xls` files rejected | Install `xlrd` or convert to `.xlsx` |
| Timestamps shift by hours | Set the profile timezone; data is stored UTC |
| Values look wrong | Check the profile's temperature unit (°C/°F/K) |
| Slow playback | Increase movie time step / coarser resolution |

## 5. Limitations (v1)
No volume rendering (VIS-05), no wall-aware interpolation (GEO-06), no study
comparison yet (M8), PDF report in M8.