"""Buyer assignment queries + mutations (issue #216: per-buyer project/cost-code authorization)."""

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
        """Issue #216: per-buyer project + cost-code authorization. The PO dialog reads this to
        filter its options; the create/register mutations re-enforce it server-side."""
        with SessionLocal() as session:
            return [buyer_assignment_to_type(a) for a in buyer_repository.list_assignments(session)]


@strawberry.type
class BuyerMutations:
    @strawberry.mutation
    def save_buyer_assignment(
        self, info: strawberry.Info, buyer_id: str, project_ids: list[strawberry.ID], cost_codes: list[str]
    ) -> BuyerAssignment:
        """Issue #216: upsert a buyer's whole assignment (projects + designated cost codes). Admin."""
        require_admin(info)
        with SessionLocal() as session:
            assignment = buyer_repository.save_assignment(
                session,
                buyer_id,
                [uuid.UUID(str(pid)) for pid in project_ids],
                cost_codes,
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
