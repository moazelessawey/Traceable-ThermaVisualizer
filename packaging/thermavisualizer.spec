# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Traceable.ThermaVisualizer (PRD §3 packaging).

Build from the repository root:
    pip install pyinstaller
    python -m PyInstaller packaging/thermavisualizer.spec --noconfirm

Output: dist/ThermaVisualizer/ThermaVisualizer.exe

Notes:
- Paths resolve from SPECPATH (this file's directory), so the build works from
  any working directory and any checkout location.
- PyQt5/PyQt6 are excluded (PRD: PySide6 only, never co-installed).
- Optional heavyweight extras (trame web UI, numba kernels, bundled test
  suites, PySide6 deploy scripts) are excluded, which removes the collection
  warnings and shrinks the bundle.
- For first-run debugging, set console=True below to see tracebacks.
"""

import importlib
import pkgutil
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

PROJECT_ROOT = Path(SPECPATH).resolve().parent  # SPECPATH is provided by PyInstaller
ENTRY_POINT = PROJECT_ROOT / "src" / "thermavisualizer" / "__main__.py"

# Optional extras we never ship; skipped during submodule enumeration.
_EXCLUDED_PREFIXES = (
    "pyvista.trame",
    "matplotlib.tests",
    "matplotlib.backends.tests",
    "pandas.tests",
    "pandas.core._numba",
    "PySide6.scripts",
    "PySide6.examples",
)


def submodules(package_name: str) -> list[str]:
    """Enumerate a package's submodules without importing excluded extras.

    Unlike collect_all/walk_packages this skips excluded prefixes *before*
    import (so packages that raise OSError/ImportError at import time, like
    ``matplotlib.tests``, never run) and silently drops optional modules that
    fail to import (trame, numba kernels, deploy tooling). Units: n/a.
    """
    package = importlib.import_module(package_name)
    names = [package_name]
    if not hasattr(package, "__path__"):
        return names

    def _walk(path, prefix: str) -> None:
        for info in pkgutil.iter_modules(path, prefix):
            if info.name.startswith(_EXCLUDED_PREFIXES):
                continue  # excluded: do not import, do not descend
            names.append(info.name)
            if info.ispkg:
                try:
                    module = importlib.import_module(info.name)
                except Exception:  # optional extra not installed: skip subtree
                    continue
                if hasattr(module, "__path__"):
                    _walk(module.__path__, info.name + ".")

    _walk(package.__path__, package_name + ".")
    return names


datas: list = []
binaries: list = []
hiddenimports: list = []

# Packages where collect_all is clean and needed (data + native libs + metadata).
for _package in (
    "scipy", "skimage", "imageio_ffmpeg", "openpyxl", "pyarrow",
    "reportlab", "vtkmodules", "pyvistaqt",
):
    _datas, _binaries, _hidden = collect_all(_package)
    datas += _datas
    binaries += _binaries
    hiddenimports += _hidden

# Packages with noisy optional extras: collect selectively.
datas += collect_data_files("pyvista")
hiddenimports += submodules("pyvista")

datas += collect_data_files("matplotlib")
binaries += collect_dynamic_libs("matplotlib")
hiddenimports += submodules("matplotlib")

datas += collect_data_files("pandas")
binaries += collect_dynamic_libs("pandas")
hiddenimports += submodules("pandas")

hiddenimports += collect_submodules("PIL")

# --- Native extensions that static analysis misses (runtime dynamic imports) ---
# pyvista ships a mypyc-compiled typing plugin: `pyvista/typing/mypy_plugin.py`
# is a shim that dynamically imports a hashed companion extension
# (e.g. "6ec57f84c680d3a3778b__mypyc"). PyInstaller cannot see that name, so
# collect every native file under the pyvista package into its package
# directory, and place hashed __mypyc modules also at the bundle root so the
# bare-name import resolves in the frozen app.
import pyvista  # build-environment import, not bundled

_PYVISTA_DIR = Path(pyvista.__file__).resolve().parent
for _native in _PYVISTA_DIR.rglob("*"):
    if _native.suffix.lower() in {".pyd", ".dll", ".so", ".dylib"}:
        _relative_dir = _native.parent.relative_to(_PYVISTA_DIR.parent)
        binaries.append((str(_native), str(_relative_dir)))
        if "__mypyc" in _native.name:
            binaries.append((str(_native), "."))

# Cheap insurance: hashed mypyc group extensions occasionally sit at the
# site-packages root instead of inside the package.
for _native in _PYVISTA_DIR.parent.glob("*__mypyc*"):
    binaries.append((str(_native), "."))

a = Analysis(
    [str(ENTRY_POINT)],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5", "PyQt6", "PySide2", "tkinter",
        "pytest", "pytestqt", "IPython", "notebook",
        "trame", "trame_pyvista", "numba",
        "pyvista.trame", "matplotlib.tests", "pandas.tests",
        "PySide6.scripts", "PySide6.examples",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ThermaVisualizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,  # TODO: point at resources/app.ico once the icon asset exists
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="ThermaVisualizer",
)