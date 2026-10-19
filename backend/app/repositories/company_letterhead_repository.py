"""What a GP company prints as itself: its name and its address (#1689).

The name is GP's own (the product owner's ruling on #1689 / #1762): the name the connected relay
reports, else the last one it reported, else the bare code. The address is the company's own, typed per
company; a company with none yet falls back to the shared PO document settings' from-address below its
first line, which is the name the shared row used to carry for everybody.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.demo import DEMO_COMPANY_NAME, is_demo_company
from app.errors import ValidationError
from app.models.company_letterhead import CompanyLetterhead
from app.repositories import po_document_settings_repository
from app.services.relay_gateway import gateway as relay_gateway

MAX_ADDRESS_LENGTH = 1000


def record_gp_names(session: Session, names: dict[str, str]) -> None:
    """Keep the GP names a relay hello reported, so they outlive the connection.

    Only a name that changed is written: the relay re-sends its hello whenever GP's company master
    changes, and every reconnect sends one, so most of these frames carry nothing new."""
    if not names:
        return
    known = dict(
        session.execute(
            select(CompanyLetterhead.company, CompanyLetterhead.gp_name).where(CompanyLetterhead.company.in_(names))
        ).all()
    )
    now = datetime.utcnow()
    for company, name in names.items():
        name = (name or "").strip()
        if not name or known.get(company) == name:
            continue
        session.execute(
            pg_insert(CompanyLetterhead)
            .values(company=company, gp_name=name, gp_name_seen_at=now)
            .on_conflict_do_update(
                index_elements=[CompanyLetterhead.company], set_={"gp_name": name, "gp_name_seen_at": now}
            )
        )


def printed_name(session: Session, company: str) -> str:
    """GP's name for the company: the live relay's, else the last one kept, else the code."""
    if is_demo_company(company):
        return DEMO_COMPANY_NAME
    live = relay_gateway.company_names.get(company)
    if live:
        return live
    kept = session.scalar(select(CompanyLetterhead.gp_name).where(CompanyLetterhead.company == company))
    return kept or company


def get_letterhead(session: Session, company: str) -> dict:
    """The company's printed name and the address lines under it."""
    row = session.get(CompanyLetterhead, company)
    address = row.address if row is not None and row.address else None
    if address is None:
        shared = po_document_settings_repository.get_settings(session).company_from_address or ""
        # The shared block's first line is the name it printed for every company; the name is GP's now.
        address = "\n".join(shared.splitlines()[1:]).strip()
    return {"company": company, "name": printed_name(session, company), "address": address}


def set_address(session: Session, company: str, address: str) -> dict:
    """Write the company's own address lines. Blank clears it back to the shared fallback."""
    address = (address or "").strip()
    if len(address) > MAX_ADDRESS_LENGTH:
        raise ValidationError(f"The address must be {MAX_ADDRESS_LENGTH} characters or fewer.", field="address")
    now = datetime.utcnow()
    session.execute(
        pg_insert(CompanyLetterhead)
        .values(company=company, address=address or None, address_updated_at=now)
        .on_conflict_do_update(
            index_elements=[CompanyLetterhead.company], set_={"address": address or None, "address_updated_at": now}
        )
    )
    session.flush()
    return get_letterhead(session, company)
