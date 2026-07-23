# PyInstaller spec for the UC Nexus relay. Produces a single dist/ucnexus-relay.exe.
#
# Build:  pyinstaller --clean --noconfirm ucnexus-relay.spec   (run from the relay dir)
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
    # The `idna` text codec is loaded LAZILY by the codec registry the first time socket.getaddrinfo()
    # has to encode a hostname. The onedir bundle DID carry encodings/idna.pyc (default encodings
    # collection), but that collection doesn't analyze it, so idna.py's `import stringprep` was never
    # followed and stringprep was left out. At runtime `import encodings.idna` then died on the missing
    # stringprep, the codec registry swallowed that ImportError, and the caller got the misleading
    # `LookupError: unknown encoding: idna` - which crashed the self-update health probe (issue #318).
    # Naming encodings.idna explicitly makes PyInstaller analyze it and follow its stringprep + unicodedata
    # deps into the bundle; stringprep is listed too as belt-and-braces. Verified by a pre/post spec build:
    # pre-fix bundle has idna.pyc + unicodedata but NO stringprep; post-fix has all three.
    "encodings.idna",
    "stringprep",
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

# ONEDIR (not onefile): a onefile exe re-extracts its whole bundle - including C-extension .pyd like
# _multiprocessing and PIL._imaging - to %TEMP%\_MEIxxxx on EVERY launch. On a Windows Defender box with no
# %TEMP%/install-dir exclusions, a freshly-written exe (a self-update swap) launched immediately has its
# just-extracted .pyd scanned as they load, and the relaunched relay crashes (ModuleNotFoundError:
# _multiprocessing / ImportError: _imaging). Onedir writes the .pyd once, as permanent files in the install
# folder (Defender scans them at install/update time, before launch), so every launch loads the same
# pre-scanned files - no per-launch extraction, no scan collision. See docs/relay-deployment.md + the
# updater's versioned-folder self-update.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: binaries/datas go in COLLECT below, not baked into the exe
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

# Collect the exe + binaries + datas into dist/ucnexus-relay/ (ucnexus-relay.exe + _internal/). The install
# and self-update flows ship/extract this whole folder (zipped) into a versioned app-<build>/ directory.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ucnexus-relay",
)
