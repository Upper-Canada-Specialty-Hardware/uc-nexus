"""Two halves of "the relay can serve from a Linux container".

The import half runs in a SUBPROCESS with pyodbc blocked out of sys.modules and sys.platform forced to
linux, because both are process-wide facts: doing it in-process would leave the rest of the suite
importing a differently-shaped ucnexus_relay.

The HTTP half runs in-process: the local endpoints all open a GP connection, and in fixture mode there
is none to open, so each has to say so rather than fail deep inside the driver.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ucnexus_relay import fixture_ops
from ucnexus_relay.config import get_settings
from ucnexus_relay.main import create_app

SRC = Path(__file__).resolve().parents[1] / "src"

# Everything `ucnexus-relay serve` reaches: the CLI dispatcher, the FastAPI app (which pulls auth,
# buyers, channel, db, econnect, cors and logging_setup with it), and the fixture registry the channel
# resolves to. dpapi and autostart are imported outright because they are the two Windows-only modules
# config and the CLI reach through.
_SCRIPT = """
import sys

sys.modules["pyodbc"] = None   # any `import pyodbc` now raises ImportError, as it does with no ODBC stack
sys.platform = "linux"         # the non-Windows path through dpapi (ctypes.wintypes will not import there)

from ucnexus_relay import autostart, channel, cli, companies, db, dpapi, fixture_ops
from ucnexus_relay.main import app

assert channel.pyodbc is None
assert db.pyodbc is None
assert db.driver_available() is False, "no pyodbc means no driver, not a crash"
assert dpapi.unprotect("plain-dev-secret") == "plain-dev-secret"
assert set(fixture_ops.OPS) == set(channel._OPS)
assert channel.ops_registry() is fixture_ops.OPS, "UCNEXUS_RELAY_MODE=fixture selects the fixture registry"
assert app.title == "UC Nexus Relay"
assert cli.main is not None
assert autostart is not None

# the companies a fixture relay serves are discovered from the snapshot, exactly as a workstation
# relay discovers GP's company master - nothing lists them in the environment
assert companies.refresh(max_age=0).companies == ["TUBC", "TUCSH"]

reply = channel._dispatch("list_jobs", "TUBC", {})
assert reply["ok"] is True and reply["result"]["jobs"], reply

print("ok")
"""


def test_serve_path_imports_and_dispatches_without_pyodbc(tmp_path):
    # Inherit the real environment (a stripped PATH / SystemRoot breaks socket and ssl init on Windows)
    # and override only what the relay reads.
    env = {
        **os.environ,
        "PYTHONPATH": str(SRC),
        "PYTHONIOENCODING": "utf-8",
        "UCNEXUS_RELAY_MODE": "fixture",
        "UCNEXUS_RELAY_SHARED_SECRET": "container-secret",
        "UCNEXUS_RELAY_LOG_FILE": "-",
        "UCNEXUS_RELAY_FIXTURE_PATH": str(SRC.parent / "fixtures" / "gp-snapshot.json"),
    }
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    # stdout-only logging leaves nothing behind, which is what the ephemeral container filesystem wants
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def fixture_client(monkeypatch):
    monkeypatch.setenv("UCNEXUS_RELAY_MODE", "fixture")
    monkeypatch.setenv("UCNEXUS_RELAY_SHARED_SECRET", "container-secret")
    get_settings.cache_clear()
    fixture_ops.reset_state()
    try:
        with TestClient(create_app()) as client:
            yield client
    finally:
        get_settings.cache_clear()
        fixture_ops.reset_state()


_AUTH = {"Authorization": "Bearer container-secret"}


@pytest.mark.parametrize("path", ["/info", "/vendors", "/buyers", "/tax-details", "/cost-codes?job=23093"])
def test_gp_reads_answer_a_fixture_mode_error(fixture_client, path):
    response = fixture_client.get(path, headers=_AUTH)
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "fixture_mode"


# Bodies complete enough to pass FastAPI's own request-model validation, which runs BEFORE the route -
# a short body would answer 422 and prove nothing about the fixture-mode gate.
_WRITE_BODIES = {
    "/po/next-number": {"company": "TUBC"},
    "/po": {
        "company": "TUBC",
        "header": {"vendor_id": "ALLEGION", "confirm_with": "Mira", "doc_date": "2026-09-01"},
        "lines": [
            {
                "item_number": "L9070",
                "item_description": "L9070 MORTISE LOCK",
                "quantity": "1",
                "unit_cost": "10.00",
            }
        ],
    },
    "/receipt": {
        "company": "TUBC",
        "po_number": "PO0000044",
        "lines": [{"po_line_ord": 16384, "quantity": "1", "rack_location": "A-1"}],
    },
}


@pytest.mark.parametrize("path", sorted(_WRITE_BODIES))
def test_gp_writes_answer_a_fixture_mode_error(fixture_client, path):
    response = fixture_client.post(path, json=_WRITE_BODIES[path], headers=_AUTH)
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "fixture_mode"


def test_health_still_answers(fixture_client):
    body = fixture_client.get("/health").json()
    assert body["status"] == "ok"
    assert "channel" in body
