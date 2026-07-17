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
    def vendors(self) -> list[Vendor]:
        with SessionLocal() as session:
            return [vendor_to_type(v) for v in vendor_repository.list_vendors(session)]

    @strawberry.field
    def vendor(self, id: strawberry.ID) -> Vendor | None:
        with SessionLocal() as session:
            v = vendor_repository.find_vendor(session, uuid.UUID(str(id)))
            return vendor_to_type(v) if v is not None else None


@strawberry.type
class VendorMutations:
    @strawberry.mutation
    def create_vendor(self, input: CreateVendorInput) -> Vendor:
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
    def update_vendor(self, id: strawberry.ID, input: UpdateVendorInput) -> Vendor:
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
    def delete_vendor(self, id: strawberry.ID) -> bool:
        with SessionLocal() as session:
            vendor_repository.delete_vendor(session, uuid.UUID(str(id)))
            session.commit()
            return True
