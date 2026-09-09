"""INVENTORY VALUE queries + mutations (#662).

The page is one read and three writes, and all four answer with the WHOLE page. That is deliberate:
every edit here moves one of the three figures, so a mutation returning only the row it touched would
leave the client holding a table that no longer adds up to the totals printed above it, and the
client would have to guess how to re-derive them. Returning the recomputed page makes that
impossible.

Both gates are named on every field. `ROOT_FIELD_POLICY` decides WHO may call (Admin/Manager or the
Shop Assembly Manager); `tenancy.require_company_in_scope` decides WHICH company they may name, which
the policy table cannot - the argument is a tenant, not a row.
"""

import uuid
from decimal import Decimal

import strawberry

from app.auth import current_user, resolve_display_name, tenant_scope
from app.database import SessionLocal
from app.repositories import inventory_value_repository, tenancy

from .inputs import SaveDoorsOnHandInput
from .types import DoorsOnHandRow, InventoryValue, InventoryValueBucket


def _bucket(data: dict) -> InventoryValueBucket:
    return InventoryValueBucket(
        hardware_value=float(data["hardware_value"]),
        door_count=data["door_count"],
        door_value=float(data["door_value"]),
        total_value=float(data["total_value"]),
    )


def _inventory_value_to_type(data: dict) -> InventoryValue:
    return InventoryValue(
        company=data["company"],
        ossa=_bucket(data["ossa"]),
        non_ossa=_bucket(data["non_ossa"]),
        general_stock=_bucket(data["general_stock"]),
        average_door_cost=float(data["average_door_cost"]),
        average_door_cost_updated_at=data["average_door_cost_updated_at"],
        average_door_cost_updated_by=data["average_door_cost_updated_by"],
        doors_on_hand=[
            DoorsOnHandRow(
                id=strawberry.ID(str(row["id"])),
                project_id=strawberry.ID(str(row["project_id"])) if row["project_id"] else None,
                project_number=row["project_number"],
                project_name=row["project_name"],
                is_ossa=row["is_ossa"],
                quantity=row["quantity"],
            )
            for row in data["doors_on_hand"]
        ],
        general_door_count=data["general_door_count"],
        ossa_door_count=data["ossa_door_count"],
        non_ossa_door_count=data["non_ossa_door_count"],
        total_door_count=data["total_door_count"],
    )


def _read(session, company: str) -> InventoryValue:
    """Recompute and serialize the page. Every field in this module ends here."""
    data = inventory_value_repository.get_inventory_value(session, company)
    session.commit()
    return _inventory_value_to_type(data)


@strawberry.type
class InventoryValueQueries:
    @strawberry.field
    def inventory_value(self, info: strawberry.Info, company: str) -> InventoryValue:
        """What everything in the building is worth, split OSSA / NON-OSSA / GENERAL STOCK (#662).

        A first read for a company creates that company's AVERAGE DOOR COST row and its general
        DOORS ON HAND row, which is why this read commits."""
        with SessionLocal() as session:
            requested = tenancy.require_company_in_scope(company, tenant_scope(info))
            return _read(session, requested)

    @strawberry.field
    def inventory_value_companies(self, info: strawberry.Info) -> list[str]:
        """The companies the page can be shown for - every GP company that owns a project.

        Off Nexus's own rows rather than the relay's company list, so the page still opens when the
        relay is down. A scoped caller gets their own company and nothing else (#637)."""
        with SessionLocal() as session:
            return inventory_value_repository.list_companies_with_projects(session, tenant_scope(info))


@strawberry.type
class InventoryValueMutations:
    @strawberry.mutation
    def save_doors_on_hand(self, info: strawberry.Info, input: SaveDoorsOnHandInput) -> InventoryValue:
        """Set one DOORS ON HAND row's count, creating the row the first time a project is named.

        A null `projectId` is the company's general row. Returns the whole recomputed page."""
        with SessionLocal() as session:
            requested = tenancy.require_company_in_scope(input.company, tenant_scope(info))
            inventory_value_repository.save_doors_on_hand(
                session,
                requested,
                uuid.UUID(str(input.project_id)) if input.project_id else None,
                input.quantity,
            )
            return _read(session, requested)

    @strawberry.mutation
    def remove_doors_on_hand(self, info: strawberry.Info, id: strawberry.ID) -> InventoryValue:
        """Drop a project's DOORS ON HAND row. The general row is refused - it is a line of the
        table, not something somebody added, so it is set to 0 rather than removed.

        The row's own company is read and checked against the caller's scope BEFORE the delete,
        because the id is the only thing the client sends: checking afterwards would already have
        deleted another tenant's row for anyone who could guess a uuid."""
        with SessionLocal() as session:
            row_id = uuid.UUID(str(id))
            owner = inventory_value_repository.company_of_doors_on_hand(session, row_id)
            requested = tenancy.require_company_in_scope(owner, tenant_scope(info))
            inventory_value_repository.remove_doors_on_hand(session, row_id)
            return _read(session, requested)

    @strawberry.mutation
    def set_average_door_cost(self, info: strawberry.Info, company: str, amount: float) -> InventoryValue:
        """The one dollar figure every DOORS ON HAND row of this company is multiplied by.

        Stamped with the Clerk-authenticated caller (#427), never a name the client sends."""
        actor = resolve_display_name(current_user(info)["user_id"])
        with SessionLocal() as session:
            requested = tenancy.require_company_in_scope(company, tenant_scope(info))
            inventory_value_repository.set_average_door_cost(session, requested, Decimal(str(amount)), actor)
            return _read(session, requested)
