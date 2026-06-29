# PyInstaller spec for the UC Nexus relay. Produces a single dist/ucnexus-relay.exe.
#
# Build:  pyinstaller --clean --noconfirm ucnexus-relay.spec   (run from the "localhost relay" dir)
# CI builds this on a windows-latest runner and attaches the exe to a GitHub Release; see
# .github/workflows/relay-release.yml. config.toml is NOT bundled - it lives next to the exe on each
# workstation and is created at install/enroll time (see docs/relay-deployment.md).

from PyInstaller.utils.hooks import collect_submodules

# uvicorn imports its loop/protocol/lifespan backends lazily by string, so PyInstaller's static analysis
# misses them - pull the whole package in. pyodbc is a C-extension and the json logger is imported by name.
hiddenimports = collect_submodules("uvicorn") + [
    "pyodbc",
    "pythonjsonlogger",
    "pythonjsonlogger.jsonlogger",
]

a = Analysis(
    ["relay_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "ruff"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ucnexus-relay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
