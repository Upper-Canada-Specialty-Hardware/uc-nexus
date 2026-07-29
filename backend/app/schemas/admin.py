"""Admin status queries."""

import uuid

import strawberry

from app.auth import require_admin
from app.database import SessionLocal
from app.repositories import admin_repository

from .types import OpeningHardwareStatus, OpeningHardwareStatusItem


@strawberry.type
class AdminQueries:
    @strawberry.field
    def opening_hardware_status(
        self, info: strawberry.Info, project_id: strawberry.ID | None = None
    ) -> list[OpeningHardwareStatus]:
        """Admin-gated (#415): only the admin Opening Status tab reads it, and it walks every opening
        in a project."""
        require_admin(info)
        with SessionLocal() as session:
            rows = admin_repository.get_opening_hardware_status(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [
                OpeningHardwareStatus(
                    opening_number=r["opening_number"],
                    building=r["building"],
                    floor=r["floor"],
                    location=r["location"],
                    items=[
                        OpeningHardwareStatusItem(
                            hardware_category=item["hardware_category"],
                            product_code=item["product_code"],
                            item_quantity=item["item_quantity"],
                            status=item["status"],
                        )
                        for item in r["items"]
                    ],
                )
                for r in rows
            ]
