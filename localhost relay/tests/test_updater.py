"""Updater: release discovery over the public GitHub API, the current-vs-latest comparison, and the
download + rename-swap that applies an update. No network (urlopen/urlretrieve mocked), no real exe."""

import json
from pathlib import Path

from ucnexus_relay import setup, updater


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_current_build_falls_back_to_dev():
    # a dev checkout has no _build.py (CI stamps it); the fallback keeps the updater always "behind"
    assert updater.current_build() == "dev"


def test_latest_release_picks_newest_relay_asset(monkeypatch):
    payload = [
        {"tag_name": "some-other-v1", "assets": []},
        {
            "tag_name": "relay-v0.1.0-build.9",
            "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "https://x/build9.exe"}],
            "published_at": "t9",
        },
        {
            "tag_name": "relay-v0.1.0-build.8",
            "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "https://x/build8.exe"}],
        },
    ]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    r = updater.latest_release()
    assert r["tag"] == "relay-v0.1.0-build.9"
    assert r["url"].endswith("build9.exe")


def test_latest_release_skips_releases_without_the_exe_asset(monkeypatch):
    payload = [{"tag_name": "relay-v0.1.0-build.9", "assets": [{"name": "notes.txt", "browser_download_url": "u"}]}]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    assert updater.latest_release() == {}


def test_check_update_reports_available(monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.7")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.9", "url": "https://x/e.exe"})
    r = updater.check_update()
    assert r["ok"] is True
    assert r["update_available"] is True
    assert r["latest"] == "relay-v0.1.0-build.9"
    assert r["url"].endswith("e.exe")


def test_check_update_up_to_date(monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.9")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.9", "url": "u"})
    assert updater.check_update()["update_available"] is False


def test_check_update_no_release(monkeypatch):
    monkeypatch.setattr(updater, "latest_release", lambda: {})
    assert updater.check_update()["ok"] is False


def test_apply_update_swaps_and_restarts(tmp_path, monkeypatch):
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD-EXE")

    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"N" * 6_000_000))
    stopped, started = {}, {}

    def _stop(d):
        stopped["d"] = d
        return {"ok": True}

    def _start(e, d):
        started["exe"] = e
        return {"ok": True}

    monkeypatch.setattr(setup, "stop_serve", _stop)
    monkeypatch.setattr(setup, "start_serve", _start)

    r = updater.apply_update("https://x/e.exe", tmp_path)
    assert r["ok"] is True
    assert exe.read_bytes()[:1] == b"N"  # exe now holds the new bytes
    assert (tmp_path / "ucnexus-relay.exe.old").read_bytes() == b"OLD-EXE"  # old renamed aside
    assert not (tmp_path / "ucnexus-relay.exe.new").exists()  # moved into place
    assert started["exe"] == exe  # serve restarted from the new exe
    assert stopped["d"] == tmp_path


def test_apply_update_rejects_a_tiny_download(tmp_path, monkeypatch):
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD")
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"tiny"))
    monkeypatch.setattr(setup, "stop_serve", lambda d: {"ok": True})

    r = updater.apply_update("u", tmp_path)
    assert r["ok"] is False
    assert "too small" in r["error"]
    assert exe.read_bytes() == b"OLD"  # left untouched on a bad download
