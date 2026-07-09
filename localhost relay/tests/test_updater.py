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


def test_latest_release_picks_highest_build_not_list_order(monkeypatch):
    # regression: GitHub's /releases list is NOT reliably newest-first - the real API returned
    # build.9, build.8, build.7, build.10 in that order. Picking the first entry gives build.9 and
    # would offer a DOWNGRADE to anyone on build.10. Pick by build number, not position.
    payload = [
        {"tag_name": "some-other-v1", "assets": []},
        {
            "tag_name": "relay-v0.1.0-build.9",
            "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "https://x/build9.exe"}],
        },
        {
            "tag_name": "relay-v0.1.0-build.8",
            "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "https://x/build8.exe"}],
        },
        {
            "tag_name": "relay-v0.1.0-build.10",  # newest, but appears AFTER the older ones in the list
            "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "https://x/build10.exe"}],
            "published_at": "t10",
        },
    ]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    r = updater.latest_release()
    assert r["tag"] == "relay-v0.1.0-build.10"
    assert r["url"].endswith("build10.exe")


def test_latest_release_returns_empty_when_no_relay_release(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp([{"tag_name": "some-other-v1", "assets": []}]))
    assert updater.latest_release() == {}


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


def test_check_update_never_offers_a_downgrade(monkeypatch):
    # installed build is NEWER than what discovery returns (e.g. GitHub API lag) -> must NOT offer to
    # "update" to the older build.
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.10")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.9", "url": "u"})
    assert updater.check_update()["update_available"] is False


def test_check_update_from_dev_offers_any_release(monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "dev")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.1", "url": "u"})
    assert updater.check_update()["update_available"] is True


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
    assert not (tmp_path / "ucnexus-relay.exe.old").exists()  # cleaned up after a successful swap
    assert not (tmp_path / "ucnexus-relay.exe.new").exists()  # moved into place
    assert started["exe"] == exe  # serve restarted from the new exe
    assert stopped["d"] == tmp_path


def test_apply_update_restarts_serve_even_when_the_swap_fails(tmp_path, monkeypatch):
    # regression: a failed swap must NOT leave the relay stopped (it took GP down once).
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD")
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"N" * 6_000_000))
    started = []
    monkeypatch.setattr(setup, "stop_serve", lambda d: {"ok": True})
    monkeypatch.setattr(setup, "start_serve", lambda e, d: started.append(e) or {"ok": True})

    def _raise(a, b):
        raise OSError("locked")

    monkeypatch.setattr(updater.os, "replace", _raise)
    r = updater.apply_update("u", tmp_path)
    assert r["ok"] is False
    assert "swap failed" in r["error"]
    assert started == [exe]  # serve was restarted on the current version despite the failure


def test_apply_update_rejects_a_tiny_download(tmp_path, monkeypatch):
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD")
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"tiny"))
    monkeypatch.setattr(setup, "stop_serve", lambda d: {"ok": True})

    r = updater.apply_update("u", tmp_path)
    assert r["ok"] is False
    assert "too small" in r["error"]
    assert exe.read_bytes() == b"OLD"  # left untouched on a bad download


def test_stage_update_downloads_writes_helper_and_spawns_it(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"N" * 6_000_000))
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    r = updater.stage_update("u", tmp_path, 4242)
    assert r["ok"] is True
    helper = tmp_path / "update-helper.bat"
    assert helper.exists()
    txt = helper.read_text(encoding="utf-8")
    assert "4242" in txt  # waits for the app pid
    assert "ucnexus-relay.exe" in txt  # relaunches the exe
    assert (tmp_path / "ucnexus-relay.exe.new").exists()  # the new exe downloaded, not yet swapped
    assert calls and calls[0][0][0] == ["cmd", "/c", str(helper)]  # helper spawned


def test_stage_update_rejects_a_tiny_download_and_does_not_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"tiny"))

    def _no_spawn(*a, **k):
        raise AssertionError("must not spawn the helper on a bad download")

    monkeypatch.setattr(updater.subprocess, "Popen", _no_spawn)
    r = updater.stage_update("u", tmp_path, 1)
    assert r["ok"] is False
    assert "too small" in r["error"]
