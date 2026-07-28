"""Onedir install layout: version-folder naming, installed-exe resolution, old-version cleanup, and the
junction repoint (mklink mocked). Pure path logic, no real junction."""

import sys
import zipfile

import pytest

from ucnexus_relay import layout


def _version(root, name: str):
    """An app-<build>/ folder that looks installable (carries the exe)."""
    d = root / name
    d.mkdir()
    (d / "ucnexus-relay.exe").write_bytes(b"exe")
    return d


def test_version_dir_name_sanitizes():
    assert layout.version_dir_name("relay-v0.1.0-build.27") == "app-relay-v0.1.0-build.27"
    assert layout.version_dir_name("") == "app-staged"
    assert layout.version_dir_name("weird/\\ name") == "app-weird---name"  # path separators + space sanitized (dots kept)


def test_installed_exe_prefers_current(tmp_path):
    cur = tmp_path / "current"  # a plain dir stands in for the junction (exists() + child exe)
    cur.mkdir()
    (cur / "ucnexus-relay.exe").write_bytes(b"exe")
    assert layout.installed_exe(tmp_path) == cur / "ucnexus-relay.exe"


def test_installed_exe_falls_back_to_newest_version(tmp_path):
    for b in ("app-relay-v0.1.0-build.8", "app-relay-v0.1.0-build.26", "app-relay-v0.1.0-build.9"):
        d = tmp_path / b
        d.mkdir()
        (d / "ucnexus-relay.exe").write_bytes(b"exe")
    assert layout.installed_exe(tmp_path) == tmp_path / "app-relay-v0.1.0-build.26" / "ucnexus-relay.exe"


def test_installed_exe_legacy_flat_fallback(tmp_path):
    # no junction, no app-*/ -> the legacy flat path (a onefile install / a dev checkout)
    assert layout.installed_exe(tmp_path) == tmp_path / "ucnexus-relay.exe"


def test_newest_version_dir_ignores_folders_without_the_exe(tmp_path):
    (tmp_path / "app-relay-v0.1.0-build.8").mkdir()  # no exe inside -> not a candidate
    good = tmp_path / "app-relay-v0.1.0-build.5"
    good.mkdir()
    (good / "ucnexus-relay.exe").write_bytes(b"e")
    assert layout.newest_version_dir(tmp_path) == good


def test_cleanup_old_versions_keeps_named(tmp_path):
    for b in ("app-a", "app-b", "app-c"):
        (tmp_path / b).mkdir()
    layout.cleanup_old_versions(tmp_path, keep={"app-b"})
    assert sorted(p.name for p in tmp_path.glob("app-*")) == ["app-b"]
    assert list(tmp_path.glob(layout.TRASH_PREFIX + "*")) == []  # moved aside AND deleted, nothing left over


@pytest.mark.skipif(sys.platform != "win32", reason="the move-aside guard relies on Windows rename semantics")
def test_cleanup_leaves_a_version_folder_that_is_in_use_completely_intact(tmp_path):
    """The #376 regression, exactly as it happened.

    A self-update's helper runs from the PREVIOUS version folder while it health-gates the new one, so the
    newly launched app's startup cleanup targets a folder that is very much in use. The old code called
    shutil.rmtree(ignore_errors=True), which does NOT skip an in-use folder - it deletes every file it can
    and leaves the locked ones, hollowing out the live helper's own bundle (unicodedata.pyd, webview/,
    pyodbc all went; only what the helper already held open survived). Removal must be all-or-nothing."""
    victim = _version(tmp_path, "app-relay-v0.1.0-build.36")
    (victim / "_internal").mkdir()
    (victim / "_internal" / "unicodedata.pyd").write_bytes(b"pyd")  # NOT open: rmtree would have taken it
    held_open = victim / "_internal" / "python311.dll"
    held_open.write_bytes(b"dll")

    with held_open.open("rb"):  # stands in for the helper process holding its own bundle open
        layout.cleanup_old_versions(tmp_path, keep={"app-relay-v0.1.0-build.37"})

    assert victim.exists()
    assert (victim / "ucnexus-relay.exe").exists()
    assert (victim / "_internal" / "unicodedata.pyd").exists()  # the file whose loss caused the outage
    assert (victim / "_internal" / "python311.dll").exists()


def test_cleanup_sweeps_trash_a_previous_pass_left_behind(tmp_path):
    stale = tmp_path / (layout.TRASH_PREFIX + "app-relay-v0.1.0-build.20")
    stale.mkdir()
    (stale / "leftover").write_bytes(b"x")

    layout.cleanup_old_versions(tmp_path, keep=set())

    assert not stale.exists()


def test_version_dirs_are_newest_build_first(tmp_path):
    for b in ("app-relay-v0.1.0-build.8", "app-relay-v0.1.0-build.26", "app-relay-v0.1.0-build.9"):
        _version(tmp_path, b)
    assert [p.name for p in layout.version_dirs(tmp_path)] == [
        "app-relay-v0.1.0-build.26",
        "app-relay-v0.1.0-build.9",
        "app-relay-v0.1.0-build.8",
    ]


def test_versions_to_keep_holds_the_newest_two_so_a_rollback_target_survives(tmp_path):
    for b in ("app-relay-v0.1.0-build.36", "app-relay-v0.1.0-build.37", "app-relay-v0.1.0-build.20"):
        _version(tmp_path, b)

    keep = layout.versions_to_keep(tmp_path)

    # 37 is running, 36 is what a failed update rolls back to; 20 is dead weight
    assert keep == {"app-relay-v0.1.0-build.37", "app-relay-v0.1.0-build.36"}


def test_versions_to_keep_adds_the_extras_it_is_given(tmp_path):
    for b in ("app-relay-v0.1.0-build.36", "app-relay-v0.1.0-build.37"):
        _version(tmp_path, b)
    odd = _version(tmp_path, "app-dev")  # no build number, so never in the newest-N slice

    keep = layout.versions_to_keep(tmp_path, extra=(odd, None))

    assert "app-dev" in keep  # a running / current folder is kept however it is named
    assert {"app-relay-v0.1.0-build.37", "app-relay-v0.1.0-build.36"} <= keep


def test_current_target_resolves_the_link_and_tolerates_its_absence(tmp_path):
    assert layout.current_target(tmp_path) is None
    cur = tmp_path / "current"  # a plain dir stands in for the junction
    cur.mkdir()
    assert layout.current_target(tmp_path) == cur.resolve()


def test_extract_zip_roundtrip(tmp_path):
    zp = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("ucnexus-relay.exe", b"exe")
        zf.writestr("_internal/x", b"y")
    dest = tmp_path / "app-x"
    layout.extract_zip(zp, dest)
    assert (dest / "ucnexus-relay.exe").read_bytes() == b"exe"
    assert (dest / "_internal" / "x").exists()


def test_repoint_current_calls_mklink_junction(tmp_path, monkeypatch):
    calls = []

    class _R:
        returncode = 0

    monkeypatch.setattr(layout.subprocess, "run", lambda args, **k: calls.append(args) or _R())
    target = tmp_path / "app-relay-v0.1.0-build.27"
    assert layout.repoint_current(tmp_path, target) is True
    assert calls and calls[0][:4] == ["cmd", "/c", "mklink", "/J"]
    assert str(target) in calls[0]
