"""The report bubble's one mutation (#1677): file what a user reports as a GitHub issue, and email it.

Open to every signed-in user, in demo mode or not. A report from demo mode files a real issue - demo
mode is about the data on screen, and a problem seen there is a real problem - and the issue says the
report came from demo mode.
"""

import asyncio
from collections.abc import Callable
from typing import TypeVar

import httpx
import strawberry

from app.auth import (
    NEXUS_ADMIN_ROLE,
    admin_acting_company,
    caller_company,
    caller_demo_mode,
    caller_roles,
    current_user,
)
from app.errors import AppError
from app.repositories import user_repository
from app.services import github_app, issue_report

from .inputs import SubmitIssueReportInput
from .types import IssueReportResult

T = TypeVar("T")


def _or(fallback: T, read: Callable[[], T]) -> T:
    """A detail about the reporter, or the fallback when Clerk cannot say. Clerk down must not stop a
    report about Clerk being down: the verified user id alone still says who sent it. A tab on a stale
    acting company is the same - exactly when somebody reports something."""
    try:
        return read()
    except (AppError, httpx.HTTPError):
        return fallback


def _reporter(info: strawberry.Info) -> issue_report.Reporter:
    """Who is reporting, from the verified session. Blocking (Clerk), so it runs off the event loop."""
    context = info.context
    user_id = current_user(info)["user_id"]
    roles = _or([], lambda: list(caller_roles(context)))
    profile = _or({"first_name": "", "last_name": "", "email": ""}, lambda: user_repository.get_user(user_id))
    name = f"{profile['first_name']} {profile['last_name']}".strip() or profile["email"] or user_id
    acting = _or(None, lambda: admin_acting_company(context)) if NEXUS_ADMIN_ROLE in roles else None
    return issue_report.Reporter(
        user_id=user_id,
        name=name,
        email=profile["email"],
        roles=roles,
        company=_or(None, lambda: caller_company(context)),
        acting_company=acting,
        demo_mode=_or(False, lambda: caller_demo_mode(context)),
    )


def _report(input: SubmitIssueReportInput) -> issue_report.Report:
    c = input.context
    return issue_report.Report(
        kind=input.kind.value,
        description=input.description,
        context=issue_report.ClientContext(
            url=c.url,
            route=c.route,
            module=c.module,
            page_title=c.page_title,
            record_ids={r.name: r.id for r in (c.records or [])[:10]},
            viewport=c.viewport,
            screen=c.screen,
            color_scheme=c.color_scheme,
            user_agent=c.user_agent,
            timezone=c.timezone,
            client_time=c.client_time,
            build=c.build,
            recent_errors=list(c.recent_errors or []),
        ),
    )


@strawberry.type
class IssueReportMutations:
    @strawberry.mutation
    async def submit_issue_report(self, info: strawberry.Info, input: SubmitIssueReportInput) -> IssueReportResult:
        """File a report as a GitHub issue and email the product owner.

        Clerk, GitHub and the mailer are all blocking calls, so the whole of it runs on a worker thread
        (#1277): a slow GitHub must not hold up every other request on the event loop.
        """
        report = _report(input)
        # Before any Clerk call: a deployment that cannot file (every PR environment) says so at once.
        if not github_app.is_configured():
            raise issue_report.ReportNotFiledError(issue_report.NOT_SET_UP)

        def run() -> issue_report.FiledReport:
            return issue_report.submit(report, _reporter(info))

        filed = await asyncio.to_thread(run)
        return IssueReportResult(issue_number=filed.issue_number, issue_url=filed.issue_url, emailed=filed.emailed)
