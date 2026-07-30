"""Buyer assignment queries + mutations (issue #216: per-buyer project authorization)."""

import uuid
from typing import Annotated

import strawberry

from app.auth import current_user
from app.database import SessionLocal
from app.repositories import buyer_repository, user_repository

from .converters import buyer_assignment_to_type
from .types import BuyerAssignment


@strawberry.type
class BuyerQueries:
    @strawberry.field
    def buyer_assignments(self, info: strawberry.Info) -> list[BuyerAssignment]:
        """Issue #216: which projects the CALLER's buyer identity may create POs for. The PO dialog
        reads this to filter its project options; the create/register mutations re-enforce it
        server-side. Signed-in, not admin (#415), because that dialog is a PO-user screen.

        Scoped to the caller's own row as of #428. It used to return the whole table, so any signed-in
        account - Shop Assembly, Shipping Out, Warehouse Staff - could enumerate which buyer owns
        which project. Not an escalation (createPo and registerPoInGp already check the caller's own
        assignment), but the dialog never needed anyone else's row: it looks up exactly the one
        matching the caller's GP buyer id and ignores the rest. An account with no GP buyer id linked
        yet gets an empty list rather than an error - it simply cannot create project POs, which is
        the state the dialog already handles. `allBuyerAssignments` is the admin-gated whole-table
        read for the Buyers page."""
        auth = current_user(info)
        # Same identity registerPoInGp enforces the PO against, so the dialog and the mutation can
        # never disagree about which assignment applies.
        buyer_id = user_repository.get_user_gp_buyer_id(auth["user_id"])
        if not buyer_id:
            return []
        with SessionLocal() as session:
            assignment = buyer_repository.get_assignment_for_identity(session, buyer_id)
            return [buyer_assignment_to_type(assignment)] if assignment is not None else []

    @strawberry.field
    def all_buyer_assignments(self, info: strawberry.Info) -> list[BuyerAssignment]:
        """Every buyer's assignment, for the Buyers admin page (#428).

        This is what `buyerAssignments` used to be. It stayed a single signed-in resolver because
        one admin screen and one PO-user dialog happened to want the same shape - but the dialog only
        ever wants its own row, and the whole table is a map of which buyer owns which project. The
        page that genuinely needs all of them is admin-only anyway, so the whole-table read is gated
        to match."""
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
        # (The current frontend keeps sending a defaulted [] too, so a frontend deployed ahead of a
        # pre-removal backend still satisfies the old required argument.) Dropped once deployed
        # frontends stop sending it, together with the field on BuyerAssignment. deprecation_reason
        # makes the no-op visible in introspection/GraphiQL, not just in this comment.
        cost_codes: Annotated[
            list[str] | None,
            strawberry.argument(deprecation_reason="cost-code designation removed; ignored"),
        ] = None,
    ) -> BuyerAssignment:
        """Issue #216: upsert a buyer's whole assignment (the projects they may order for). Admin."""
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
        with SessionLocal() as session:
            buyer_repository.delete_assignment(session, buyer_id)
            session.commit()
            return True
