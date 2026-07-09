# PyInstaller spec for the UC Nexus relay. Produces a single dist/ucnexus-relay.exe.
#
# Build:  pyinstaller --clean --noconfirm ucnexus-relay.spec   (run from the "localhost relay" dir)
# CI builds this on a windows-latest runner and attaches the exe to a GitHub Release; see
# .github/workflows/relay-release.yml. config.toml is NOT bundled - it lives next to the exe on each
# workstation and is created at install/enroll time (see docs/relay-deployment.md).

from PyInstaller.utils.hooks import collect_all, collect_submodules

# uvicorn imports its loop/protocol/lifespan backends lazily by string, so PyInstaller's static analysis
# misses them - pull the whole package in. pyodbc is a C-extension and the json logger is imported by name.
hiddenimports = collect_submodules("uvicorn") + [
    "pyodbc",
    "pythonjsonlogger",
    "pythonjsonlogger.jsonlogger",
    "clr",  # pythonnet's runtime import name (the `ui` window loads the WebView2 backend through it)
]

# The `ui` subcommand's native window (pywebview) reaches the Edge WebView2 backend through pythonnet/clr.
# Those are loaded dynamically (clr assemblies, pywebview's bundled JS + WebView2 loader), so static
# analysis misses them - collect_all pulls each package's submodules, data files, and binaries. pywebview
# also ships a PyInstaller hook that PyInstaller auto-discovers, but collecting explicitly is belt-and-braces.
datas = []
binaries = []
for _pkg in ("webview", "clr_loader", "pythonnet", "pystray", "PIL"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["relay_entry.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
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
    # Windowed (GUI) subsystem: a console-subsystem exe pops a console window every time the tray app is
    # launched (titled with the exe path), which stays for the app's whole life. Building windowed means
    # neither the tray app nor the detached `serve` child ever shows a console. cli.py reattaches to the
    # launching terminal's console (AttachConsole) so CLI subcommands still print when run by hand.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
