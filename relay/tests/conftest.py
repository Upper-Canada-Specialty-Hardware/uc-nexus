"""Suite-wide guards.

The relay arms daemon timers that call os._exit(0) as an exit-anyway fallback when a graceful teardown
leaves the GUI loop stuck (see app.RelayApp._arm_hard_exit). Those timers outlive the test that armed
them and resolve os._exit at FIRE time, so a per-test monkeypatch of os._exit is undone at teardown while
the timer is still pending. When it fired it took the pytest process with it: exit code 0, no summary,
no failures - and a CI run that reported green having actually executed about a third of the suite.

So os._exit is disarmed for the whole session rather than per test. Calls are recorded on the fixture in
case a test wants to assert one happened; nothing ever exits the runner.
"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _never_hard_exit_the_test_runner():
    calls = []
    real_exit = os._exit
    os._exit = lambda code=0: calls.append(code)  # noqa: SLF001 - disarming it is the point
    try:
        yield calls
    finally:
        os._exit = real_exit
