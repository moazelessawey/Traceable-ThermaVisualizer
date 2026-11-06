# AGENTS.md

Guidance for AI coding agents working on **Traceable.ThermaVisualizer**, a PySide6 + OpenGL desktop app for visualizing thermal mapping (temperature/humidity) studies in pharmaceutical facilities.

The source of truth for requirements is `PRD_Traceable_ThermaVisualizer.md`. Read it before starting any task. If code and PRD disagree, stop and ask.

---

## 1. Project Snapshot

- **Language:** Python 3.11+
- **GUI:** PySide6 (never install or import PyQt5/PyQt6; set `QT_API=pyside6`)
- **3D:** OpenGL via `pyqtgraph.opengl` (v1), hidden behind a `SceneRenderer` abstraction
- **Plots:** matplotlib (`FigureCanvasQTAgg`)
- **Numerics:** numpy, scipy, pandas, scikit-image
- **Export:** imageio + imageio-ffmpeg
- **Tests:** pytest, pytest-qt
- **Maintainer:** Moaz El-Essawey (open source project shared with the community)

---

## 2. How to Work

1. **One milestone at a time.** Milestones M0 to M7 are in the PRD section 9. Do not start the next milestone until the current one passes its acceptance checks and the maintainer confirms.
2. **Plan first for any task larger than a single function:** state the files you will touch and the approach in a few lines, then implement.
3. **Small, reviewable changes.** One feature or fix per change set. Do not refactor unrelated code.
4. **Never invent requirements.** If something is ambiguous, ask or record it in the PRD's open questions rather than guessing.
5. **Run the checks** (section 7) before declaring a task done, and report what you ran and the results.
6. **Do not add dependencies** without asking. If one is needed, explain why and propose the pinned range.

---

## 3. Repository Layout

```
thermavisualizer/
├── pyproject.toml
├── AGENTS.md
├── PRD_Traceable_ThermaVisualizer.md
├── src/thermavisualizer/
│   ├── __main__.py            # entry point
│   ├── core/                  # pure Python, NO Qt imports
│   │   ├── models.py          # Space, Layer, Logger, Obstacle, Mapping, Study, Project dataclasses
│   │   ├── geometry.py        # footprint (box/polygon), point-in-space, masks, obstacle volumes
│   │   ├── layout.py          # lattice generation, bulk layout operations
│   │   ├── results.py         # acceptance criteria, excursions, pass/fail, MKT
│   │   ├── validation.py      # data validation rules (VAL-xx)
│   │   ├── alignment.py       # time-base alignment
│   │   ├── interpolation.py   # IDW, RBF, linear, trilinear, smoothing
│   │   ├── slicing.py         # slice extraction, isosurfaces
│   │   └── statistics.py      # min/max/mean/std, MKT
│   ├── io/
│   │   ├── readers.py         # CSV/TXT/XLSX readers and import profiles
│   │   ├── project_file.py    # .tmap read/write, hashing, migrations
│   │   ├── exporters.py       # CSV/XLSX/image/movie exporters
│   │   ├── layout_io.py       # logger/obstacle/footprint CSV/XLSX import and export
│   │   └── report.py          # PDF report generation (M8)
│   ├── services/
│   │   ├── workers.py         # QThread/QThreadPool workers
│   │   ├── cache.py           # interpolation cache
│   │   ├── undo.py            # QUndoStack commands
│   │   ├── audit.py           # AuditService: append-only, hash-chained audit trail
│   │   └── settings.py        # QSettings wrapper
│   ├── rendering/
│   │   ├── scene.py           # SceneRenderer interface
│   │   ├── gl_backend.py      # pyqtgraph.opengl implementation
│   │   └── offscreen.py       # framebuffer rendering for movies/images
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── tabs/              # configuration, view3d, plots, data
│   │   ├── panels/            # left control panels per tab
│   │   └── widgets/           # RangeSlider, ColorBar, CanvasOverlay, etc.
│   └── resources/             # icons, themes, colormaps
└── tests/
    ├── core/  io/  ui/
    └── data/                  # small sample files for tests
```

---

## 4. Architecture Rules (hard constraints)

1. **`core/` and `io/` must never import PySide6, matplotlib, or OpenGL.** They must be testable headless.
2. **UI never contains business logic.** Panels and tabs call services/core and react to signals.
3. **Single source of state:** an observable `ProjectModel`. Widgets subscribe via Qt signals; they do not hold their own copies of project data.
4. **All configuration edits go through `QUndoCommand`s** so undo/redo works (CFG-08).
5. **Long operations run off the GUI thread:** file loading, validation on large files, interpolation, movie export. Provide progress and cancel. Never call `processEvents()` as a workaround.
6. **Raw data is immutable.** Cleaning, exclusion, alignment, and smoothing are recorded as separate processing steps and applied on top. Never overwrite loaded raw arrays.
7. **One render path.** Live view, screenshots, and movie frames must use the same scene code via `SceneRenderer` so outputs match what the user sees.
8. **Rendering is behind an interface.** Nothing outside `rendering/` may import `pyqtgraph.opengl` or `OpenGL`.
9. **Project file integrity:** `.tmap` saves are atomic (temp file then replace), versioned (`schema_version`), hashed (SHA-256 per member), and migrations are explicit functions.
10. **No network calls, no `eval`/`exec`, no unpickling** of project or data files.
11. **Geometry is never assumed to be a box.** Placement checks, interpolation masks, slicing, and rendering all go through the `Space` geometry in `core/geometry.py`, which supports polygon footprints and obstacle masks.
12. **Audit trail:** every mutating action (see PRD AUD-03) is recorded through a single `AuditService` with user name, UTC timestamp, action type, target, and change summary. Entries are append-only and hash-chained. Undo/redo also logs. The UI must not offer edit or delete of entries.
13. **Derived results are recomputed, never stored as truth.** Study results (`results.py`) derive from raw data, criteria, and processing settings.

---

## 5. UI Layout Contract (do not deviate)

- Top: menu/action bar, then toolbar.
- Center: horizontal splitter. **Left panel about 25% width** (contextual controls). **Right area about 75%:** `QTabWidget` with **`TabPosition.East`** (tab bar on the right edge). Tabs: Configuration, 3D View, Plots, Results, Data (Audit Trail viewer opens from the Tools menu or as an optional tab).
- **Timeline** below the tab area: custom two-handle `RangeSlider` (start/end), optional playhead, play/pause/step/speed controls.
- **3D canvas overlay** (top-right of the canvas): reset camera, preset views, toggles (markers, labels, bounding box, slices), screenshot, color-scale settings.
- **Status bar:** permanent left label exactly: `Developed and maintained by Moaz El-Essawey`.
- Persist window geometry and splitter state with `QSettings`.

---

## 6. Coding Standards

- **PySide6 specifics:** use `Signal`/`Slot` from `PySide6.QtCore` (not `pyqtSignal`/`pyqtSlot`); use fully qualified enums (e.g. `Qt.AlignmentFlag.AlignLeft`, `QTabWidget.TabPosition.East`); import matplotlib's Qt canvas via `matplotlib.backends.backend_qtagg` with `QT_API=pyside6`.

- Python 3.11+, fully **type-annotated**; `mypy --strict` clean for `core/` and `io/`.
- Format with **ruff format**, lint with **ruff**; line length 100.
- Use `dataclasses` (frozen where practical) for models; `pathlib.Path` for paths; `logging` (never `print`) with a module-level logger.
- Docstrings (Google style) on all public functions and classes; explain units (always state °C, %RH, metres) in names or docstrings.
- Use numpy vectorization; no Python loops over samples in hot paths.
- Qt: use signals/slots, name signals in past tense (`mapping_changed`), parent every widget, and avoid blocking calls in slots.
- Use `StrEnum`/`Enum` for fixed choices (interpolation method, aggregation, severity).
- Keep functions short; prefer composition over inheritance; avoid global state.
- Errors: raise specific exceptions from `core`/`io` (e.g., `ValidationError`, `ProjectFileError`); the UI layer converts them to dialogs. Never swallow exceptions silently.

---

## 7. Commands and Definition of Done

Set up (once):
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Checks to run before finishing any task:
```bash
ruff format --check .
ruff check .
mypy src/thermavisualizer/core src/thermavisualizer/io
pytest -q                         # headless: QT_QPA_PLATFORM=offscreen
```

A task is **done** only when:
- [ ] The behavior matches the relevant PRD requirement IDs (cite them, e.g. `DAT-03`, `INT-02`).
- [ ] New code has tests (unit tests for `core`/`io`; `pytest-qt` for UI behavior).
- [ ] All checks above pass.
- [ ] No new dependency was added without approval.
- [ ] The app still launches: `python -m thermavisualizer`.
- [ ] You summarized what changed, what was tested, and any open questions.

---

## 8. Testing Guidance

- **core:** property and edge-case tests for interpolation (known analytic fields, e.g. linear gradient must be reproduced exactly by linear/trilinear), alignment, validation rules (one test file per VAL-xx case), statistics.
- **io:** round-trip tests for `.tmap` (save, load, compare), hash-tamper detection, schema migration, reader tests for delimiter/decimal/timestamp variants.
- **ui:** `pytest-qt` for layout contract (east tabs, 25% panel, status bar credit), RangeSlider behavior (handles cannot cross, signals emitted), undo/redo flows, mapping completeness gating.
- **rendering:** smoke tests with the offscreen platform; compare dimensions and non-blank output rather than pixel-exact images.
- **geometry:** box and L-shaped footprints, point-in-space, mask correctness, obstacle collisions.
- **layout:** bulk CSV/XLSX import (valid and malformed), lattice generation, single-undo-step behavior.
- **results:** hand-computed fixtures for min/max/mean/std, MKT, excursions, recovery time, pass/fail.
- **audit:** every AUD-03 event is recorded, entries are append-only, hash chain verifies and detects tampering.
- **report (M8):** smoke test that a PDF is produced with expected sections and metadata.
- Keep sample data small and in `tests/data/`. Generate synthetic datasets with a seeded RNG.

---

## 9. Domain Notes (pharma context)

- This is a **GxP-adjacent** tool. Favor traceability: record software version, processing steps, and parameters in every export and project.
- Interpolated values are **estimates**. Always label the method and show it in exports and the UI.
- This is an **open-source community tool**: the audit trail is lightweight (user, timestamp, action). Do **not** add electronic signatures or claim 21 CFR Part 11 compliance in code, UI, or docs.
- **Out of scope (do not build without explicit approval):** per-logger calibration data, validation of the tool itself, vendor-specific logger file formats, clock-drift correction. Only generic Excel/CSV/text files are supported.
- Never silently drop or alter data. Excluded loggers, excluded time ranges, and gap handling must be visible and reversible.
- Default units: temperature °C, humidity %RH, length metres. Convert at the edges (import/display), store canonical units internally.
- Use clear, neutral wording in UI text suitable for validation reports.

---

## 10. Common Pitfalls

- Qt has no built-in two-handle slider: implement and test a custom `RangeSlider` early.
- `QOpenGLWidget` / GL calls must run on the GUI thread; do computation in workers and pass numpy arrays back via signals.
- Matplotlib redraws are slow with many points: decimate for display, but compute statistics on full data.
- Time zones and daylight-saving shifts in logger files: parse explicitly, store UTC internally, display per user setting.
- Excel files may store timestamps as serial numbers or strings: handle both.
- Do not let interpolation extrapolate silently outside the logger hull: follow INT-06 (clamp or mask, user-selected).

---

## 11. Do / Don't Summary

**Do**
- Cite PRD IDs in commit messages and summaries.
- Keep `core/` pure and heavily tested.
- Ask when requirements are unclear.
- Keep the UI responsive.

**Don't**
- Don't build features outside the current milestone.
- Don't import Qt or OpenGL in `core/` or `io/`.
- Don't mutate raw data or bypass the undo stack.
- Don't add dependencies, network calls, or telemetry without approval.
- Don't change the UI layout contract without maintainer sign-off.
- Don't treat the space as a box or ignore obstacles in any spatial computation.
- Don't build calibration, vendor parsers, e-signatures, or clock-drift features.
