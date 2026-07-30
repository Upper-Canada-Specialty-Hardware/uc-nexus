"""Buyer assignment queries + mutations (issue #216: per-buyer project authorization)."""

import uuid

import strawberry

from app.auth import require_admin
from app.database import SessionLocal
from app.repositories import buyer_repository

from .converters import buyer_assignment_to_type
from .types import BuyerAssignment


@strawberry.type
class BuyerQueries:
    @strawberry.field
    def buyer_assignments(self) -> list[BuyerAssignment]:
        """Issue #216: which projects each buyer may create POs for. The PO dialog reads this to
        filter its project options; the create/register mutations re-enforce it server-side."""
        with SessionLocal() as session:
            return [buyer_assignment_to_type(a) for a in buyer_repository.list_assignments(session)]


@strawberry.type
class BuyerMutations:
    @strawberry.mutation
    def save_buyer_assignment(
        self,
        info: strawberry.Info,
        buyer_id: str,
        project_ids: list[strawberry.ID],
        # Accepted and ignored: cost-code designation was removed, but an admin tab loaded before that
        # deploy still sends this argument, and an unknown argument fails GraphQL validation outright.
        # Dropped once deployed frontends stop sending it, together with the field on BuyerAssignment.
        cost_codes: list[str] | None = None,  # noqa: ARG002
    ) -> BuyerAssignment:
        """Issue #216: upsert a buyer's whole assignment (the projects they may order for). Admin."""
        require_admin(info)
        with SessionLocal() as session:
            assignment = buyer_repository.save_assignment(
                session,
                buyer_id,
                [uuid.UUID(str(pid)) for pid in project_ids],
            )
            session.commit()
            refreshed = buyer_repository.get_assignment(session, assignment.buyer_id)
            return buyer_assignment_to_type(refreshed)

    @strawberry.mutation
    def delete_buyer_assignment(self, info: strawberry.Info, buyer_id: str) -> bool:
        require_admin(info)
        with SessionLocal() as session:
            buyer_repository.delete_assignment(session, buyer_id)
            session.commit()
            return True
