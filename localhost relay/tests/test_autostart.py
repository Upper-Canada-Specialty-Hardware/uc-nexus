"""No-admin autostart (HKCU Run) registration. Exercises the real winreg calls against a THROWAWAY
HKCU subkey - never the live Run key - so a test run can't leave a stray logon entry behind."""

import pytest

from ucnexus_relay import autostart

pytestmark = pytest.mark.skipif(autostart.winreg is None, reason="Windows-only (winreg unavailable)")

_TEST_SUBKEY = r"Software\UCNexusRelayTest\Run"
_TEST_PARENT = r"Software\UCNexusRelayTest"


@pytest.fixture
def clean_test_key():
    yield
    wr = autostart.winreg
    try:
        with wr.CreateKeyEx(wr.HKEY_CURRENT_USER, _TEST_SUBKEY, 0, wr.KEY_SET_VALUE) as k:
            try:
                wr.DeleteValue(k, autostart.VALUE_NAME)
            except FileNotFoundError:
                pass
        wr.DeleteKey(wr.HKEY_CURRENT_USER, _TEST_SUBKEY)
        wr.DeleteKey(wr.HKEY_CURRENT_USER, _TEST_PARENT)
    except OSError:
        pass


def test_status_false_when_absent(clean_test_key):
    assert autostart.autostart_status(subkey=_TEST_SUBKEY) == {"installed": False, "command": None}


def test_install_then_status_reports_command(clean_test_key):
    autostart.install_autostart(command='"C:\\x\\ucnexus-relay.exe" serve', subkey=_TEST_SUBKEY)
    st = autostart.autostart_status(subkey=_TEST_SUBKEY)
    assert st["installed"] is True
    assert st["command"] == '"C:\\x\\ucnexus-relay.exe" serve'


def test_install_overwrites(clean_test_key):
    autostart.install_autostart(command='"old" serve', subkey=_TEST_SUBKEY)
    autostart.install_autostart(command='"new" serve', subkey=_TEST_SUBKEY)
    assert autostart.autostart_status(subkey=_TEST_SUBKEY)["command"] == '"new" serve'


def test_uninstall_reports_whether_it_existed(clean_test_key):
    autostart.install_autostart(command='"x" serve', subkey=_TEST_SUBKEY)
    assert autostart.uninstall_autostart(subkey=_TEST_SUBKEY) is True
    assert autostart.uninstall_autostart(subkey=_TEST_SUBKEY) is False


def test_default_command_quotes_the_exe(monkeypatch):
    monkeypatch.setattr(autostart.sys, "executable", r"C:\Program Files\UC\ucnexus-relay.exe")
    assert autostart.default_command() == '"C:\\Program Files\\UC\\ucnexus-relay.exe" serve'
