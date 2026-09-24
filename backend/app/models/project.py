import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import GpJobState


class Project(Base):
    __tablename__ = "projects"
    # A GP job number is only unique WITHIN a company (#637): TUBC and UCSH can both hold job 1001 and
    # they are two different projects. The single-column constraint migration 024 added would let the
    # first company to adopt a number lock every other company out of it.
    __table_args__ = (UniqueConstraint("company", "project_id", name="uq_projects_company_project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The GP company that owns this project - the tenant (#637). Stamped from the relay install the
    # sync/create ran against; every non-admin read and write is filtered on it.
    company: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Hidden from the project picker every module reads, and from nothing else (#637). Archiving is a
    # visibility decision, not a lifecycle one: POs, inventory and shipments on an archived project
    # keep working exactly as they did.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    client: Mapped[str | None] = mapped_column(String, nullable=True)
    job_site_name: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    zip: Mapped[str | None] = mapped_column(String, nullable=True)
    contractor: Mapped[str | None] = mapped_column(String, nullable=True)
    project_manager: Mapped[str | None] = mapped_column(String, nullable=True)
    application: Mapped[str | None] = mapped_column(String, nullable=True)
    submittal_job_no: Mapped[str | None] = mapped_column(String, nullable=True)
    submittal_assignment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimator_code: Mapped[str | None] = mapped_column(String, nullable=True)
    titan_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # #627: the source XML file name of the persisted hardware schedule, shown on the wizard's
    # "use last uploaded" picker and loaded-schedule card. Written on a fresh-parse finalize; a
    # hydrate-from-persisted finalize leaves it, so the stored name survives. NULL = imported before
    # this, or a hydrate that never carried one.
    schedule_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    off_site_storage_agreement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    gc_contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    gc_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    gc_email: Mapped[str | None] = mapped_column(String, nullable=True)
    # GP job setup verdict, stamped by every gp_job_sync pass (#425). The project's GP job may carry
    # JC00701 cost codes pointing at GL account indexes this company does not have - a legacy of the
    # pre-2023 UCSH -> UBC job copy - which makes a PO on that job registerable but never receivable.
    #
    # NULL means never checked, and never-checked does NOT quarantine: the sync only runs while a
    # relay is connected, so a relay outage would otherwise freeze all of Nexus. Only an explicit
    # False blocks. gp_setup_detail is a JSON list of {cost_code, account_index} so the quarantine
    # banner can name the codes accounting has to fix rather than saying "something is wrong".
    gp_setup_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gp_setup_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    gp_setup_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # --- the GP job, as GP holds it (#730) ------------------------------------------------------------
    # GP owns every field below, plus description (job name), client (customer name) and the site
    # address above: the GP JOBS SYNC overwrites them on every pass and a job edit writes them into GP
    # first. NULL gp_job_state means the project has never been mirrored, and like gp_setup_ok None it
    # refuses nothing - an old relay or a relay outage must not freeze every project.
    gp_job_state: Mapped[GpJobState | None] = mapped_column(
        Enum(GpJobState, name="gp_job_state", create_constraint=True), nullable=True
    )
    gp_closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # First pass that could not find the job in GP at all. A second consecutive miss marks it NOT_IN_GP;
    # seeing it again clears this. Same two-pass rule as purchase_orders.gp_missing_since.
    gp_missing_since: Mapped[datetime | None] = mapped_column(nullable=True)
    customer_number: Mapped[str | None] = mapped_column(String, nullable=True)
    job_address_code: Mapped[str | None] = mapped_column(String, nullable=True)
    billto_address_code: Mapped[str | None] = mapped_column(String, nullable=True)
    address2: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    division: Mapped[str | None] = mapped_column(String, nullable=True)
    tax_schedule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    use_tax_schedule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # GP's estimator, not estimator_code above - that one is the TITAN schedule's and Nexus-only.
    estimator_id: Mapped[str | None] = mapped_column(String, nullable=True)
    estimator_name: Mapped[str | None] = mapped_column(String, nullable=True)
    ws_manager_id: Mapped[str | None] = mapped_column(String, nullable=True)
    ws_manager_name: Mapped[str | None] = mapped_column(String, nullable=True)
    gp_created_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    schedule_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    scheduled_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bid_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    orig_contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 5), nullable=True)
    contract_to_date: Mapped[Decimal | None] = mapped_column(Numeric(19, 5), nullable=True)
    total_actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(19, 5), nullable=True)
    billed_amount_ttd: Mapped[Decimal | None] = mapped_column(Numeric(19, 5), nullable=True)
    retention_amount_ttd: Mapped[Decimal | None] = mapped_column(Numeric(19, 5), nullable=True)
    net_billed_ttd: Mapped[Decimal | None] = mapped_column(Numeric(19, 5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    openings: Mapped[list["Opening"]] = relationship(back_populates="project")


class Opening(Base):
    __tablename__ = "openings"
    __table_args__ = (Index("ix_openings_project_opening", "project_id", "opening_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    opening_number: Mapped[str] = mapped_column(String, nullable=False)
    building: Mapped[str | None] = mapped_column(String, nullable=True)
    floor: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    location_to: Mapped[str | None] = mapped_column(String, nullable=True)
    location_from: Mapped[str | None] = mapped_column(String, nullable=True)
    hand: Mapped[str | None] = mapped_column(String, nullable=True)
    width: Mapped[str | None] = mapped_column(String, nullable=True)
    length: Mapped[str | None] = mapped_column(String, nullable=True)
    door_thickness: Mapped[str | None] = mapped_column(String, nullable=True)
    jamb_thickness: Mapped[str | None] = mapped_column(String, nullable=True)
    door_type: Mapped[str | None] = mapped_column(String, nullable=True)
    frame_type: Mapped[str | None] = mapped_column(String, nullable=True)
    interior_exterior: Mapped[str | None] = mapped_column(String, nullable=True)
    keying: Mapped[str | None] = mapped_column(String, nullable=True)
    heading_no: Mapped[str | None] = mapped_column(String, nullable=True)
    single_pair: Mapped[str | None] = mapped_column(String, nullable=True)
    assignment_multiplier: Mapped[str | None] = mapped_column(String, nullable=True)
    # Number of door leaves (#311): 1 (single) or 2 (pair), captured at import from the distinct
    # parsed Leaf attributes. The immutable "N of M leaves shipped" denominator. Null = legacy.
    leaf_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    project: Mapped["Project"] = relationship(back_populates="openings")
