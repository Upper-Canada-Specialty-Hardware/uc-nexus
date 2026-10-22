"""A user's report from the report bubble, filed as a GitHub issue and emailed (#1677).

The report is filed as a parent issue on the repository, as is, with everything needed to act on it
without going back to the user: who they are, where they were, what was on screen, and what had just
gone wrong. Ruled on #1678: the repository is public and the whole report goes in the body anyway. It
is filed with no points; the board job marks it waiting on points, which is the triage queue.

Who the user is comes from the verified session, never from the client. Where they were and what was
on screen only the browser knows, so that part is whatever the tab sent, capped.
"""

import html
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.errors import AppError, ValidationError
from app.services import github_app, mailer

logger = logging.getLogger(__name__)

TITLE_PREFIX = "user report: "
_TITLE_TEXT_LIMIT = 80
DESCRIPTION_LIMIT = 5000
FIELD_LIMIT = 500
ERRORS_LIMIT = 10
ERROR_LIMIT = 1000

# Enough for a person, not for a stuck button or a loop: one report at a time, and a handful an hour.
_MIN_GAP_SECONDS = 20
_HOURLY_LIMIT = 10


NOT_SET_UP = "Reporting is not set up on this deployment yet."


class ReportThrottledError(AppError):
    def __init__(self, message: str):
        super().__init__(message, "REPORT_THROTTLED")


class ReportNotFiledError(AppError):
    """GitHub is not configured or refused: nothing was filed, and nothing was emailed."""

    def __init__(self, message: str):
        super().__init__(message, "REPORT_NOT_FILED")


@dataclass(frozen=True)
class Reporter:
    """Who sent it, from the session."""

    user_id: str
    name: str
    email: str
    roles: list[str]
    company: str | None
    acting_company: str | None
    demo_mode: bool


@dataclass(frozen=True)
class ClientContext:
    """What only the browser knows. Every field is optional: a report with less context still files."""

    url: str = ""
    route: str = ""
    module: str = ""
    page_title: str = ""
    record_ids: dict[str, str] = field(default_factory=dict)
    viewport: str = ""
    screen: str = ""
    color_scheme: str = ""
    user_agent: str = ""
    timezone: str = ""
    client_time: str = ""
    build: str = ""
    recent_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Report:
    kind: str
    description: str
    context: ClientContext


@dataclass(frozen=True)
class FiledReport:
    issue_number: int
    issue_url: str
    emailed: bool


# --- throttle ---------------------------------------------------------------------------------------

_throttle_lock = threading.Lock()
_sent: dict[str, deque[float]] = {}


def _take_slot(user_id: str, *, now: float | None = None) -> float:
    """Claim one report for this user, or refuse. Checked and claimed under one lock, so two reports
    sent at once (two tabs, a retry) cannot both pass while neither has been counted yet."""
    now = time.monotonic() if now is None else now
    with _throttle_lock:
        times = _sent.setdefault(user_id, deque())
        while times and now - times[0] > 3600:
            times.popleft()
        if times and now - times[-1] < _MIN_GAP_SECONDS:
            raise ReportThrottledError("Your last report was just sent. Wait a few seconds before sending another.")
        if len(times) >= _HOURLY_LIMIT:
            raise ReportThrottledError("That is a lot of reports in an hour. Try again later, or email instead.")
        times.append(now)
        return now


def _give_back_slot(user_id: str, claimed: float) -> None:
    """A report that was not filed does not count against the user."""
    with _throttle_lock:
        times = _sent.get(user_id)
        if times and claimed in times:
            times.remove(claimed)


def reset_throttle() -> None:
    """For tests."""
    with _throttle_lock:
        _sent.clear()


# --- body -------------------------------------------------------------------------------------------


def _clip(value: str | None, limit: int = FIELD_LIMIT) -> str:
    value = (value or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _cell(value: str | None) -> str:
    """A markdown table cell: one line, pipes escaped, mentions defused, a dash when empty. The cells are
    client text too (#1814): a screen of `1920x1080 @2x` would otherwise ping the account named 2x."""
    value = _defuse(re.sub(r"\s+", " ", _clip(value)).replace("|", "\\|"))
    return value or "-"


def _defuse(text: str) -> str:
    """@mentions in client text do not notify: a zero-width space after the @ looks the same and is not
    a mention, so a report cannot ping a person or an org team from a public issue."""
    return re.sub(r"@(?=[\w-])", "@​", text)


def _quoted(lines: list[str]) -> str:
    """Client text as a blockquote. Every line then starts with `>`, which is what keeps it from being
    read as this issue's own: the board job and the clock take Points from any line shaped `points: 5`
    or a `points` heading with a number under it, and they read raw lines, fences and all."""
    return "\n".join(f"> {line}" if line.strip() else ">" for line in lines)


def _fence(lines: list[str]) -> list[str]:
    """A code block no line inside it can close early."""
    text = "\n".join(lines)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return [ticks, *text.splitlines(), ticks]


def title_for(report: Report) -> str:
    first_line = next((line.strip() for line in report.description.splitlines() if line.strip()), "")
    text = re.sub(r"\s+", " ", first_line)
    if len(text) > _TITLE_TEXT_LIMIT:
        text = text[: _TITLE_TEXT_LIMIT - 1].rstrip() + "…"
    return TITLE_PREFIX + (text or "(no description)")


def body_for(report: Report, reporter: Reporter, *, reported_at: datetime, backend_build: str) -> str:
    c = report.context
    kind = "change request" if report.kind == "change" else "problem"
    company = reporter.company or "none assigned"
    if reporter.acting_company and reporter.acting_company != reporter.company:
        company = f"{company}, working in {reporter.acting_company}"
    records = ", ".join(f"{k} {v}" for k, v in sorted(c.record_ids.items())) if c.record_ids else ""

    rows = [
        ("kind", kind),
        ("user", f"{reporter.name} ({reporter.email})" if reporter.email else reporter.name),
        ("user id", reporter.user_id),
        ("roles", ", ".join(reporter.roles) or "none"),
        ("company", company),
        ("demo mode", "on" if reporter.demo_mode else "off"),
        ("page", c.page_title),
        ("module", c.module),
        ("route", c.route),
        ("url", c.url),
        ("records", records),
        ("viewport", c.viewport),
        ("screen", c.screen),
        ("theme", c.color_scheme),
        ("browser", c.user_agent),
        ("timezone", c.timezone),
        ("their clock", c.client_time),
        ("reported at", reported_at.strftime("%Y-%m-%d %H:%M:%S UTC")),
        ("frontend build", c.build),
        ("backend build", backend_build),
    ]
    parts = [
        "filed from the report bubble in nexus.",
        "",
        "### what the user wrote",
        "",
        _quoted(_defuse(_clip(report.description, DESCRIPTION_LIMIT)).splitlines()),
        "",
        "### context",
        "",
        "| | |",
        "|---|---|",
        *(f"| {name} | {_cell(value)} |" for name, value in rows),
        "",
        "### recent errors",
        "",
    ]
    errors = [_clip(e, ERROR_LIMIT) for e in c.recent_errors[-ERRORS_LIMIT:] if e and e.strip()]
    # Quoted as well as fenced: the Points reader does not know what a fence is.
    parts.append(_quoted(_fence(errors)) if errors else "none in this tab before the report.")
    return "\n".join(parts) + "\n"


# --- email ------------------------------------------------------------------------------------------


def _recipients() -> list[str]:
    raw = os.getenv("ISSUE_REPORT_EMAIL_TO") or ""
    return [a.strip() for a in raw.split(",") if a.strip()]


def _email(report: Report, reporter: Reporter, issue: github_app.FiledIssue, title: str) -> bool:
    """Tell the product owner. False when it was not sent; the issue stands either way."""
    to = _recipients()
    if not to or not mailer.is_configured():
        logger.info("Report #%s filed; no email sent (mailer or recipient not configured)", issue.number)
        return False
    who = reporter.name + (f", {reporter.company}" if reporter.company else "")
    if reporter.demo_mode:
        who += ", in demo mode"
    where = report.context.page_title or report.context.route or "unknown page"
    subject = f"Nexus report #{issue.number}: {title.removeprefix(TITLE_PREFIX)}"
    description = _clip(report.description, DESCRIPTION_LIMIT)
    text = f"{who} sent a report from {where}.\n\n{description}\n\nIssue: {issue.url}\n"
    page = (
        f"<p>{html.escape(who)} sent a report from {html.escape(where)}.</p>"
        f'<blockquote style="white-space:pre-wrap">{html.escape(description)}</blockquote>'
        f'<p><a href="{html.escape(issue.url)}">Open issue #{issue.number}</a></p>'
    )
    try:
        mailer.send(
            to=to,
            subject=subject,
            text=text,
            html=page,
            # One issue, one email: a retried send is answered from the mailer's first result.
            idempotency_key=f"nexus-report-{issue.number}",
        )
    except mailer.MailerError:
        logger.warning("Report #%s filed; email not sent", issue.number, exc_info=True)
        return False
    return True


# --- the whole thing --------------------------------------------------------------------------------


def submit(report: Report, reporter: Reporter) -> FiledReport:
    """File the report, then email it. Synchronous: the resolver runs it off the event loop."""
    if report.kind not in ("problem", "change"):
        raise ValidationError("A report is a problem or a change request.", field="kind")
    if not report.description.strip():
        raise ValidationError("Say what happened or what you want changed.", field="description")
    if not github_app.is_configured():
        raise ReportNotFiledError(NOT_SET_UP)
    claimed = _take_slot(reporter.user_id)

    title = title_for(report)
    body = body_for(
        report,
        reporter,
        reported_at=datetime.now(UTC),
        backend_build=(os.getenv("RAILWAY_GIT_COMMIT_SHA") or "dev")[:12],
    )
    try:
        issue = github_app.create_issue(title=title, body=body)
    except github_app.GitHubError as exc:
        _give_back_slot(reporter.user_id, claimed)
        logger.warning("Report not filed: %s", exc)
        raise ReportNotFiledError("The report could not be filed. Try again in a minute.") from exc
    return FiledReport(issue_number=issue.number, issue_url=issue.url, emailed=_email(report, reporter, issue, title))
