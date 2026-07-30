"""Local vendor queries + mutations."""

import uuid

import strawberry

from app.database import SessionLocal
from app.repositories import vendor_repository

from .converters import vendor_to_type
from .inputs import CreateVendorInput, UpdateVendorInput
from .types import Vendor


@strawberry.type
class VendorQueries:
    @strawberry.field
    def vendors(self, info: strawberry.Info) -> list[Vendor]:
        """Signed-in, not admin (#415): VendorSelect renders this list on the PO screens, so it is
        not an admin-only read even though only an admin may write it."""
        with SessionLocal() as session:
            return [vendor_to_type(v) for v in vendor_repository.list_vendors(session)]

    @strawberry.field
    def vendor(self, info: strawberry.Info, id: strawberry.ID) -> Vendor | None:
        with SessionLocal() as session:
            v = vendor_repository.find_vendor(session, uuid.UUID(str(id)))
            return vendor_to_type(v) if v is not None else None


@strawberry.type
class VendorMutations:
    @strawberry.mutation
    def create_vendor(self, info: strawberry.Info, input: CreateVendorInput) -> Vendor:
        """Signed-in, not admin. `VendorSelect` offers "+ Create new vendor" to every caller and
        renders `VendorEditDialog` with `vendor={null}`, so a PO user adding a supplier mid-order goes
        through here. Editing or deleting an existing vendor is still admin - only the admin Vendors
        page reaches those. The dialog living under `modules/admin/` says nothing about who can open
        it, which is exactly the trap this comment exists to stop."""
        with SessionLocal() as session:
            vendor = vendor_repository.create_vendor(
                session,
                name=input.name,
                contact_name=input.contact_name,
                email=input.email,
                phone=input.phone,
                notes=input.notes,
            )
            session.commit()
            session.refresh(vendor)
            return vendor_to_type(vendor)

    @strawberry.mutation
    def update_vendor(self, info: strawberry.Info, id: strawberry.ID, input: UpdateVendorInput) -> Vendor:
        with SessionLocal() as session:
            vendor = vendor_repository.update_vendor(
                session,
                uuid.UUID(str(id)),
                name=input.name,
                contact_name=input.contact_name,
                email=input.email,
                phone=input.phone,
                notes=input.notes,
            )
            session.commit()
            session.refresh(vendor)
            return vendor_to_type(vendor)

    @strawberry.mutation
    def delete_vendor(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        with SessionLocal() as session:
            vendor_repository.delete_vendor(session, uuid.UUID(str(id)))
            session.commit()
            return True
