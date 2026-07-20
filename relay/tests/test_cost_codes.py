"""Auth gate + required-param checks for /cost-codes. The 401 short-circuits before any SQL, so the
auth tests never touch GP; the missing-job 422 fires on param validation before the body runs."""

from fastapi.testclient import TestClient

from ucnexus_relay.config import get_settings
from ucnexus_relay.main import create_app

client = TestClient(create_app())
TOKEN = get_settings().auth.shared_secret


def test_cost_codes_requires_token():
    assert client.get("/cost-codes?job=80003").status_code == 401


def test_cost_codes_rejects_bad_token():
    assert client.get("/cost-codes?job=80003", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_cost_codes_requires_job():
    # `job` is a required query param. With a valid token, a missing job is a 422 from param
    # validation - before the endpoint body opens any SQL connection.
    r = client.get("/cost-codes", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 422
