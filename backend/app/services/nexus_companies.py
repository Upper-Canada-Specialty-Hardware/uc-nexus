"""The GP companies a UC NEXUS ADMIN may act in (#845).

An admin works in ONE GP company at a time, picked with the app bar's switcher and sent as the
`X-Nexus-Company` header. This module answers "which companies are there to pick", for the switcher
(`nexusCompanies`) and for the header check in `app.auth.tenant_scope` alike, so the two cannot
disagree about what a valid company is.

The answer is a union of two sources, and each covers the other's blind spot:

  - the companies the connected relay serves, which is also the only place GP's display names come
    from - but empty whenever the relay is down;
  - the distinct `projects.company` values, which survive a relay outage - an admin must still be
    able to open a company's projects while GP is unreachable.
"""

from sqlalchemy import distinct, select

from app.database import SessionLocal
from app.models.project import Project
from app.services.relay_gateway import gateway as relay_gateway


def project_companies() -> set[str]:
    """Every company that owns at least one project. One indexed DISTINCT over `projects.company`."""
    with SessionLocal() as session:
        return {c for c in session.scalars(select(distinct(Project.company))) if c}


def relay_companies() -> set[str]:
    """The companies the live relay serves; empty when it is disconnected. In-memory, no I/O."""
    return set(relay_gateway.companies)


def is_known_company(company: str) -> bool:
    """Whether `company` (already normalized) is one an admin may act in. The relay is asked first
    because it is free; the database only when the relay does not serve it."""
    return company in relay_companies() or company in project_companies()


def list_companies() -> list[tuple[str, str]]:
    """Every company an admin may act in, as (code, name), sorted by code. The name is GP's when the
    relay reported one, else the bare code - the same fallback `relayStatus.gpCompanies` uses."""
    names = relay_gateway.company_names
    codes = relay_companies() | project_companies()
    return [(code, names.get(code) or code) for code in sorted(codes)]
