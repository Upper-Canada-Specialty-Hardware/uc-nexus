"""The report bubble's mutation (#1677): filed as a GitHub issue, emailed through ucsh-mailer.

Nothing reaches GitHub, the mailer or Clerk: every outside call is stubbed."""

import asyncio
import re
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.repositories import user_repository
from app.services import github_app, issue_report, mailer
from main import schema

MUTATION = """
mutation($input: SubmitIssueReportInput!) {
  submitIssueReport(input: $input) { issueNumber issueUrl emailed }
}
"""


class _FakeRequest:
    headers = {"authorization": "Bearer tok"}


def _context(*, roles=None, company="TUBC", demo=False):
    return {
        "request": _FakeRequest(),
        "_auth_user_id": "u_test",
        "_auth_roles": roles or [],
        "_auth_company": company,
        "_auth_demo_mode": demo,
    }


def _input(**overrides):
    value = {
        "kind": "PROBLEM",
        "description": "Receiving won't save\nIt spins forever on the last line.",
        "context": {
            "url": "https://nexus.example/app/warehouse/receive/abc",
            "route": "/app/warehouse/receive/abc",
            "module": "warehouse",
            "pageTitle": "Receive PO",
            "records": [{"name": "po", "id": "abc"}],
            "viewport": "1440x900",
            "userAgent": "Mozilla/5.0 test",
            "build": "abc1234",
            "recentErrors": ["[GraphQL error]: boom"],
        },
    }
    value.update(overrides)
    return value


@pytest.fixture
def world(monkeypatch):
    """GitHub and the mailer configured and stubbed, recording what they were asked to do."""
    issue_report.reset_throttle()
    calls = {"issues": [], "mails": []}

    def _create_issue(*, title, body):
        calls["issues"].append({"title": title, "body": body})
        return github_app.FiledIssue(number=4242, url="https://github.com/o/r/issues/4242")

    def _send(**kwargs):
        calls["mails"].append(kwargs)

    monkeypatch.setattr(github_app, "is_configured", lambda: True)
    monkeypatch.setattr(github_app, "create_issue", _create_issue)
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send", _send)
    monkeypatch.setenv("ISSUE_REPORT_EMAIL_TO", "owner@example.test")
    monkeypatch.setattr(
        user_repository,
        "get_user",
        lambda user_id: {"first_name": "Pat", "last_name": "Lee", "email": "pat@example.test"},
    )
    yield calls
    issue_report.reset_throttle()


def _submit(context=None, **overrides):
    return asyncio.run(
        schema.execute(MUTATION, variable_values={"input": _input(**overrides)}, context_value=context or _context())
    )


def test_files_the_issue_and_emails_it(world):
    result = _submit()

    assert result.errors is None, result.errors
    assert result.data["submitIssueReport"] == {
        "issueNumber": 4242,
        "issueUrl": "https://github.com/o/r/issues/4242",
        "emailed": True,
    }
    [issue] = world["issues"]
    assert issue["title"] == "user report: Receiving won't save"
    assert "Pat Lee (pat@example.test)" in issue["body"]
    assert "| company | TUBC |" in issue["body"]
    assert "| demo mode | off |" in issue["body"]
    assert "| records | po abc |" in issue["body"]
    assert "[GraphQL error]: boom" in issue["body"]
    assert "### points" not in issue["body"]

    [mail] = world["mails"]
    assert mail["to"] == ["owner@example.test"]
    assert mail["subject"] == "Nexus report #4242: Receiving won't save"
    assert mail["idempotency_key"] == "nexus-report-4242"
    assert "https://github.com/o/r/issues/4242" in mail["text"]


def test_a_report_from_demo_mode_is_filed_and_says_so(world):
    result = _submit(_context(company="UBC", demo=True))

    assert result.errors is None, result.errors
    assert "| demo mode | on |" in world["issues"][0]["body"]
    assert "in demo mode" in world["mails"][0]["text"]


def test_who_reported_comes_from_the_session_not_the_client(world):
    """There is no field for the user at all: the identity is the verified session's."""
    _submit(_context(roles=["PO User"]))

    body = world["issues"][0]["body"]
    assert "| user id | u_test |" in body
    assert "| roles | PO User |" in body


def test_not_configured_files_nothing_and_says_so(world, monkeypatch):
    monkeypatch.setattr(github_app, "is_configured", lambda: False)

    result = _submit()

    assert result.errors[0].extensions["code"] == "REPORT_NOT_FILED"
    assert world["issues"] == [] and world["mails"] == []


def test_github_refusing_emails_nothing(world, monkeypatch):
    def _refuse(**kwargs):
        raise github_app.GitHubError("403 Resource not accessible by integration")

    monkeypatch.setattr(github_app, "create_issue", _refuse)

    result = _submit()

    assert result.errors[0].extensions["code"] == "REPORT_NOT_FILED"
    assert world["mails"] == []


def test_the_issue_stands_when_the_email_fails(world, monkeypatch):
    def _fail(**kwargs):
        raise mailer.MailerError("the mailer refused it: 401 unauthorized")

    monkeypatch.setattr(mailer, "send", _fail)

    result = _submit()

    assert result.errors is None, result.errors
    assert result.data["submitIssueReport"]["emailed"] is False


def test_no_recipient_files_without_emailing(world, monkeypatch):
    monkeypatch.delenv("ISSUE_REPORT_EMAIL_TO")

    result = _submit()

    assert result.data["submitIssueReport"]["emailed"] is False
    assert world["mails"] == []


def test_an_empty_description_is_refused(world):
    result = _submit(description="   ")

    assert result.errors[0].extensions["code"] == "VALIDATION_ERROR"
    assert world["issues"] == []


def test_a_second_report_straight_after_is_throttled(world):
    assert _submit().errors is None

    result = _submit()

    assert result.errors[0].extensions["code"] == "REPORT_THROTTLED"
    assert len(world["issues"]) == 1


def test_the_hourly_limit_holds_after_the_gap():
    issue_report.reset_throttle()
    start = 1000.0
    for i in range(10):
        issue_report._take_slot("u", now=start + i * 30)
    with pytest.raises(issue_report.ReportThrottledError):
        issue_report._take_slot("u", now=start + 10 * 30)
    # An hour after the first, there is room again.
    issue_report._take_slot("u", now=start + 3601 + 9 * 30)
    issue_report.reset_throttle()


def test_two_reports_at_once_cannot_both_pass():
    """The slot is claimed in the same lock as the check, before GitHub is called."""
    issue_report.reset_throttle()
    issue_report._take_slot("u", now=5000.0)
    with pytest.raises(issue_report.ReportThrottledError):
        issue_report._take_slot("u", now=5000.5)
    issue_report.reset_throttle()


def test_a_report_github_refused_does_not_count(world, monkeypatch):
    def _refuse(**kwargs):
        raise github_app.GitHubError("502")

    monkeypatch.setattr(github_app, "create_issue", _refuse)
    assert _submit().errors[0].extensions["code"] == "REPORT_NOT_FILED"
    monkeypatch.setattr(github_app, "create_issue", lambda **kw: github_app.FiledIssue(number=1, url="u"))

    result = _submit()

    assert result.errors is None, result.errors


def test_clerk_down_still_files_the_report(world, monkeypatch):
    def _down(user_id):
        raise httpx.HTTPStatusError("503", request=httpx.Request("GET", "x"), response=httpx.Response(503))

    monkeypatch.setattr(user_repository, "get_user_roles", _down)
    monkeypatch.setattr(user_repository, "get_user", _down)
    context = _context()
    del context["_auth_roles"]

    result = _submit(context)

    assert result.errors is None, result.errors
    body = world["issues"][0]["body"]
    assert "| user | u_test |" in body
    assert "| roles | none |" in body


def test_not_configured_answers_before_asking_clerk(world, monkeypatch):
    monkeypatch.setattr(github_app, "is_configured", lambda: False)

    def _never(user_id):
        raise AssertionError("Clerk was asked")

    monkeypatch.setattr(user_repository, "get_user", _never)

    assert _submit().errors[0].extensions["code"] == "REPORT_NOT_FILED"


# --- the body ---------------------------------------------------------------------------------------


def _reporter(**overrides):
    value = dict(
        user_id="u1",
        name="Pat Lee",
        email="pat@example.test",
        roles=[],
        company="UBC",
        acting_company=None,
        demo_mode=False,
    )
    value.update(overrides)
    return issue_report.Reporter(**value)


def _body(report, reporter=None):
    from datetime import UTC, datetime

    return issue_report.body_for(
        report, reporter or _reporter(), reported_at=datetime(2026, 10, 16, tzinfo=UTC), backend_build="def5678"
    )


def test_table_cells_cannot_break_the_table():
    report = issue_report.Report(
        kind="problem",
        description="x",
        context=issue_report.ClientContext(page_title="a | b\nc"),
    )

    assert "| page | a \\| b c |" in _body(report)


def test_an_error_with_backticks_cannot_close_its_code_block():
    report = issue_report.Report(
        kind="problem", description="x", context=issue_report.ClientContext(recent_errors=["a ``` b"])
    )

    body = _body(report)

    assert "> ````\n> a ``` b\n> ````" in body


# The org's own reader, as clock/points.js and the board job have it: raw lines, no idea of fences.
_SAME_LINE = re.compile(r"^\s*(?:#+\s*)?points\s*:\s*([0-9]+)\s*$", re.I)
_HEADING = re.compile(r"^\s*(?:#+\s*)?points\s*:?\s*$", re.I)


def _filed_points(body):
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if _SAME_LINE.match(line):
            return int(_SAME_LINE.match(line).group(1))
        if _HEADING.match(line):
            following = next((rest for rest in lines[i + 1 :] if rest.strip()), "")
            if re.match(r"^\s*([0-9]+)\s*$", following):
                return int(following)
    return None


@pytest.mark.parametrize("text", ["Points: 3", "### points\n\n40", "points\n5"])
def test_nothing_the_user_types_can_set_the_points(text):
    report = issue_report.Report(
        kind="problem",
        description=f"it broke\n{text}",
        context=issue_report.ClientContext(recent_errors=[text]),
    )

    assert _filed_points(_body(report)) is None


def test_mentions_in_the_report_do_not_notify():
    report = issue_report.Report(
        kind="problem",
        description="ask @someone or @Upper-Canada-Specialty-Hardware/devs",
        context=issue_report.ClientContext(),
    )

    body = _body(report)

    assert "@someone" not in body
    assert "@​someone" in body


def test_an_admin_working_in_another_company_is_named_with_both():
    report = issue_report.Report(kind="change", description="x", context=issue_report.ClientContext())

    body = _body(report, _reporter(company=None, acting_company="TUBC"))

    assert "| company | none assigned, working in TUBC |" in body
    assert "| kind | change request |" in body


def test_long_titles_are_cut():
    report = issue_report.Report(kind="problem", description="word " * 50, context=issue_report.ClientContext())

    title = issue_report.title_for(report)

    assert title.startswith("user report: word word")
    assert len(title) <= len("user report: ") + 80


# --- github app -------------------------------------------------------------------------------------


@pytest.fixture
def app_config():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()
    github_app.forget_token()
    yield github_app.GitHubAppConfig(client_id="Iv23test", private_key=pem, repo="o/r"), key.public_key()
    github_app.forget_token()


def test_the_app_jwt_follows_githubs_rules(app_config):
    config, public_key = app_config

    token = github_app.app_jwt(config, now=1_000_000)

    claims = jwt.decode(token, public_key, algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False})
    assert claims["iss"] == "Iv23test"
    assert claims["iat"] == 1_000_000 - 60
    assert claims["exp"] - 1_000_000 <= 600


def test_the_installation_token_is_minted_once_and_reused(app_config, monkeypatch):
    config, _ = app_config
    expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    seen = []

    def _request(method, path, *, bearer, json=None):
        seen.append((method, path))
        if path == "/repos/o/r/installation":
            return {"id": 77}
        return {"token": "ghs_one", "expires_at": expires}

    monkeypatch.setattr(github_app, "_request", _request)

    assert github_app.installation_token(config) == "ghs_one"
    assert github_app.installation_token(config) == "ghs_one"
    assert seen == [("GET", "/repos/o/r/installation"), ("POST", "/app/installations/77/access_tokens")]


def test_a_token_near_expiry_is_replaced(app_config, monkeypatch):
    config, _ = app_config
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 120))
    minted = []

    def _request(method, path, *, bearer, json=None):
        if path.endswith("/installation"):
            return {"id": 77}
        minted.append(path)
        return {"token": f"ghs_{len(minted)}", "expires_at": soon}

    monkeypatch.setattr(github_app, "_request", _request)

    assert github_app.installation_token(config) == "ghs_1"
    assert github_app.installation_token(config) == "ghs_2"


def test_a_200_that_is_not_json_is_github_not_answering(monkeypatch):
    monkeypatch.setattr(
        github_app._client, "request", lambda *a, **kw: httpx.Response(200, text="<html>maintenance</html>")
    )

    with pytest.raises(github_app.GitHubError, match="not JSON"):
        github_app._request("GET", "/x", bearer="t")


def test_escaped_line_breaks_in_the_key_are_restored(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_CLIENT_ID", "Iv23test")
    escaped = "-----BEGIN RSA PRIVATE KEY-----\\nabc\\n-----END RSA PRIVATE KEY-----"
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", escaped)
    monkeypatch.setenv("GITHUB_REPORT_REPO", "o/r")

    assert github_app.get_config().private_key.count("\n") == 2


def test_nothing_set_means_disabled(monkeypatch):
    for name in ("GITHUB_APP_CLIENT_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_REPORT_REPO"):
        monkeypatch.delenv(name, raising=False)

    assert github_app.is_configured() is False


# --- mailer -----------------------------------------------------------------------------------------


@pytest.fixture
def mailer_env(monkeypatch):
    monkeypatch.setenv("MAILER_URL", "https://mailer.example/")
    monkeypatch.setenv("MAILER_KEY", "ucshm_nexus_test")
    monkeypatch.setattr(mailer.time, "sleep", lambda seconds: None)


def _responses(monkeypatch, *statuses):
    sent = []
    queue = list(statuses)

    def _post(url, *, json, headers, timeout):
        sent.append({"url": url, "json": json, "headers": headers})
        status = queue.pop(0)
        return httpx.Response(status, json={"error": "hve_unavailable" if status == 503 else "x"})

    monkeypatch.setattr(mailer.httpx, "post", _post)
    return sent


def test_mailer_sends_with_the_key_and_idempotency_key(mailer_env, monkeypatch):
    sent = _responses(monkeypatch, 200)

    mailer.send(to=["a@example.test"], subject="s", text="t", html="<p>t</p>", idempotency_key="k1")

    [request] = sent
    assert request["url"] == "https://mailer.example/v1/send"
    assert request["headers"] == {"Authorization": "Bearer ucshm_nexus_test", "Idempotency-Key": "k1"}
    assert request["json"] == {"to": ["a@example.test"], "subject": "s", "text": "t", "html": "<p>t</p>"}


def test_mailer_retries_only_when_hve_is_unavailable(mailer_env, monkeypatch):
    sent = _responses(monkeypatch, 503, 200)

    mailer.send(to=["a@example.test"], subject="s", text="t", idempotency_key="k1")

    assert len(sent) == 2
    assert {r["headers"]["Idempotency-Key"] for r in sent} == {"k1"}


def test_mailer_does_not_retry_a_refusal(mailer_env, monkeypatch):
    sent = _responses(monkeypatch, 401)

    with pytest.raises(mailer.MailerError, match="401"):
        mailer.send(to=["a@example.test"], subject="s", text="t", idempotency_key="k1")

    assert len(sent) == 1
