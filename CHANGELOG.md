# Changelog

Format: milestone (PRD §9) → highlights with PRD requirement IDs.

## [1.0.0] — 2026-11 (M0–M7)
### Added
- Window shell: east tabs, 25 % contextual left panel, timeline, status-bar
  credit (M0).
- Configuration: box/polygon spaces, layers, loggers, obstacles, lattice,
  bulk CSV/XLSX layout IO, undo/redo, live 3D preview (M1: CFG/GEO/OBS/BLK).
- Data: readers with saveable profiles, validation engine VAL-01..11,
  mapping UI with completeness gate, alignment/resampling, multi-file merge
  (M2: DAT/VAL).
- Interpolation IDW/RBF/linear/trilinear with cached weights, masked voxel
  grid, background worker; slices; color maps; 3D view + overlay; probe
  (M3: INT/SLC/VIS).
- Timeline playback driving all views; plots (matplotlib) with MKT;
  acceptance criteria; results & excursion tables (M4: PLT/RES).
- Animation polish and movie/image/data exports incl. offscreen MP4/GIF,
  audit-stamped with SHA-256 (M5: EXP).
- `.tmap` project files: integrity hashes, schema migrations, study metadata,
  audit storage & viewer, autosave/recovery (M6: EXP-05/STY/AUD).
- Light/dark/system themes, PyInstaller spec, docs, performance guardrails
  (M7: VIS-08, NFRs), startup splash screen.

### Notes
- 3D backend: PyVista/pyvistaqt (M0 spike decision; PRD open question 6 resolved).
- The audit trail is lightweight and explicitly not a Part 11 feature.