"""Onedir install layout: version-folder naming, installed-exe resolution, old-version cleanup, and the
junction repoint (mklink mocked). Pure path logic, no real junction."""

import zipfile

from ucnexus_relay import layout


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
