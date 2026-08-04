"""Admin status queries."""

import uuid

import strawberry

from app.database import SessionLocal
from app.repositories import opening_deep_dive

from .enums import LeafStatus, OpeningStage
from .types import (
    AdminLeafClaim,
    AdminLooseLine,
    AdminOpeningDeepDive,
    AdminOpeningLine,
    AdminOpeningStatus,
    AdminPoLineRef,
    OpeningLeafState,
)


def _leaves(rows) -> list[OpeningLeafState]:
    return [OpeningLeafState(leaf=leaf.leaf, status=LeafStatus(leaf.status)) for leaf in rows]


def _line_to_type(line) -> AdminOpeningLine:
    return AdminOpeningLine(
        leaf=line.leaf,
        hardware_category=line.hardware_category,
        product_code=line.product_code,
        owed_quantity=line.owed_quantity,
        shipped_on_leaf=line.shipped_on_leaf,
        shipped_loose=line.shipped_loose,
        staged=line.staged,
        pulled_for_shipping=line.pulled_for_shipping,
        assembled_in_inventory=line.assembled_in_inventory,
        pulled_for_assembly=line.pulled_for_assembly,
        ordered=line.ordered,
        po_drafted=line.po_drafted,
        not_purchased=line.not_purchased,
        po_lines=[
            AdminPoLineRef(
                po_number=ref.po_number,
                status=ref.status,
                ordered_quantity=ref.ordered_quantity,
                received_quantity=ref.received_quantity,
            )
            for ref in line.po_lines
        ],
    )


@strawberry.type
class AdminQueries:
    @strawberry.field
    def admin_opening_statuses(self, info: strawberry.Info, project_id: strawberry.ID) -> list[AdminOpeningStatus]:
        """Every opening in ONE project, with its hardware partitioned across the lifecycle.

        Admin-gated: it walks every opening in the project and puts purchasing next to fulfilment.
        `projectId` is required - this page is project-scoped by design. The all-projects form it
        used to have merged openings that merely shared a number across different projects into one
        fabricated row.
        """
        with SessionLocal() as session:
            rows = opening_deep_dive.get_project_opening_statuses(session, uuid.UUID(str(project_id)))
            return [
                AdminOpeningStatus(
                    opening_number=row.opening_number,
                    building=row.building,
                    floor=row.floor,
                    location=row.location,
                    leaf_count=row.leaf_count,
                    stage=OpeningStage(row.stage),
                    owed_units=row.owed_units,
                    shipped_units=row.shipped_units,
                    staged_units=row.staged_units,
                    assembled_units=row.assembled_units,
                    pulled_units=row.pulled_units,
                    shipped_loose_units=row.shipped_loose_units,
                    pulled_for_shipping_units=row.pulled_for_shipping_units,
                    ordered_units=row.ordered_units,
                    po_drafted_units=row.po_drafted_units,
                    not_purchased_units=row.not_purchased_units,
                    leaves=_leaves(row.leaves),
                )
                for row in rows
            ]

    @strawberry.field
    def admin_opening_deep_dive(
        self, info: strawberry.Info, project_id: strawberry.ID, opening_number: str
    ) -> AdminOpeningDeepDive | None:
        """One opening's every hardware line, per leaf, plus what it has sent loose.

        Fetched only when a row is expanded, which is what keeps the list payload to a handful of
        integers per opening rather than the whole schedule.
        """
        with SessionLocal() as session:
            dive = opening_deep_dive.get_opening_deep_dive(session, uuid.UUID(str(project_id)), opening_number)
            if dive is None:
                return None
            return AdminOpeningDeepDive(
                opening_number=dive.opening_number,
                building=dive.building,
                floor=dive.floor,
                location=dive.location,
                leaf_count=dive.leaf_count,
                leaves=_leaves(dive.leaves),
                leaf_claims=[
                    AdminLeafClaim(leaf=leaf, request_number=request_number)
                    for leaf, request_number in sorted(
                        dive.leaf_claims.items(), key=lambda item: (item[0] is None, item[0])
                    )
                ],
                lines=[_line_to_type(line) for line in dive.lines],
                loose=[
                    AdminLooseLine(
                        hardware_category=line.hardware_category,
                        product_code=line.product_code,
                        pulled_for_shipping=line.pulled_for_shipping,
                        shipped_loose=line.shipped_loose,
                    )
                    for line in dive.loose
                ],
            )
