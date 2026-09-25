"""The Tenant Owner's override of a project's hardware classifications after import (#735)."""

import uuid
from datetime import datetime

import strawberry

from app.auth import current_user, resolve_display_name, tenant_scope
from app.database import SessionLocal
from app.repositories import classification_override_repository as repo
from app.repositories import tenancy

from .enums import HardwareClassificationChoice


@strawberry.type
class ProjectHardwareClassification:
    """One product on the project's schedule and the classification it has now."""

    hardware_category: str
    product_code: str
    quantity: int
    opening_count: int
    # UNCLASSIFIED or MIXED describe what is there; only the other three can be set.
    choice: HardwareClassificationChoice


@strawberry.type
class HardwareClassificationChange:
    id: strawberry.ID
    hardware_category: str
    product_code: str
    from_choice: str
    to_choice: str
    changed_by: str
    changed_at: datetime


@strawberry.input
class HardwareClassificationChangeInput:
    hardware_category: str
    product_code: str
    choice: HardwareClassificationChoice


@strawberry.input
class SetHardwareClassificationsInput:
    project_id: strawberry.ID
    changes: list[HardwareClassificationChangeInput]


def _change_to_type(c) -> HardwareClassificationChange:
    return HardwareClassificationChange(
        id=strawberry.ID(str(c.id)),
        hardware_category=c.hardware_category,
        product_code=c.product_code,
        from_choice=c.from_choice,
        to_choice=c.to_choice,
        changed_by=c.changed_by,
        changed_at=c.changed_at,
    )


def _rows(session, project_id: uuid.UUID) -> list[ProjectHardwareClassification]:
    return [
        ProjectHardwareClassification(
            hardware_category=r["hardware_category"],
            product_code=r["product_code"],
            quantity=r["quantity"],
            opening_count=r["opening_count"],
            choice=r["choice"],
        )
        for r in repo.list_product_classifications(session, project_id)
    ]


@strawberry.type
class ClassificationOverrideQueries:
    @strawberry.field
    def project_hardware_classifications(
        self, info: strawberry.Info, project_id: strawberry.ID
    ) -> list[ProjectHardwareClassification]:
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id))
            tenancy.require_project_in_scope(session, pid, tenant_scope(info))
            return _rows(session, pid)

    @strawberry.field
    def hardware_classification_changes(
        self, info: strawberry.Info, project_id: strawberry.ID
    ) -> list[HardwareClassificationChange]:
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id))
            tenancy.require_project_in_scope(session, pid, tenant_scope(info))
            return [_change_to_type(c) for c in repo.list_changes(session, pid)]


@strawberry.type
class ClassificationOverrideMutations:
    @strawberry.mutation
    def set_hardware_classifications(
        self, info: strawberry.Info, input: SetHardwareClassificationsInput
    ) -> list[ProjectHardwareClassification]:
        """All or nothing: a change something depends on refuses the whole set, naming each product."""
        actor = resolve_display_name(current_user(info)["user_id"])
        with SessionLocal() as session:
            pid = uuid.UUID(str(input.project_id))
            tenancy.require_project_in_scope(session, pid, tenant_scope(info))
            repo.set_product_classifications(
                session,
                pid,
                [(c.hardware_category, c.product_code, c.choice) for c in input.changes],
                changed_by=actor,
            )
            session.commit()
            return _rows(session, pid)
