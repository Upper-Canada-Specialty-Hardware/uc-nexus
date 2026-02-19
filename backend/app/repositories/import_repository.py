"""Repository for hardware schedule import operations."""

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from app.models.project import Project as ProjectModel, Opening as OpeningModel
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.purchase_order import PurchaseOrder as POModel, POLineItem as POLineItemModel
from app.models.pull_request import PullRequest as PullRequestModel, PullRequestItem as PullRequestItemModel
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.shop_assembly import (
    ShopAssemblyRequest as SARModel,
    ShopAssemblyOpening as SAOModel,
    ShopAssemblyOpeningItem as SAOItemModel,
)
from app.models.enums import (
    HardwareItemState,
    POStatus,
    Classification,
    PullRequestSource,
    PullRequestStatus,
    PullRequestItemType,
    ShopAssemblyRequestStatus,
    PullStatus,
    AssemblyStatus,
)
from app.errors import NotFoundError, ConflictError


def reconcile_schedule(
    session: Session,
    project_id: uuid.UUID,
    items: list[dict],
) -> list[dict]:
    """Compare needed items against existing inventory pool."""
    # Query pool availability
    stmt = (
        select(
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
            func.sum(InventoryLocationModel.quantity).label("total_available"),
        )
        .where(InventoryLocationModel.project_id == project_id)
        .group_by(
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
        )
    )
    rows = session.execute(stmt).all()

    # Build mutable availability map
    available_map: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row.hardware_category, row.product_code)
        available_map[key] = row.total_available

    results = []
    for item in items:
        key = (item["hardware_category"], item["product_code"])
        pool_available = available_map.get(key, 0)
        needed = item["quantity_needed"]

        # Determine how much we can allocate from pool
        can_allocate = min(pool_available, needed)

        if can_allocate >= needed:
            status = "AVAILABLE"
        elif can_allocate > 0:
            status = "PARTIAL"
        else:
            status = "NOT_AVAILABLE"

        # Deduct from pool to prevent double-counting
        if can_allocate > 0:
            available_map[key] = pool_available - can_allocate

        results.append({
            "opening_number": item["opening_number"],
            "hardware_category": item["hardware_category"],
            "product_code": item["product_code"],
            "quantity_needed": needed,
            "quantity_available": can_allocate,
            "status": status,
        })

    return results


def finalize_import_session(
    session: Session,
    input_data: dict,
) -> dict:
    """Finalize an import session: create project, POs, PRs, and SAR atomically."""
    project_input = input_data["project"]
    openings_input = input_data.get("openings", [])
    hardware_items_input = input_data.get("hardware_items") or []
    po_drafts = input_data.get("po_drafts") or []
    classifications_input = input_data.get("classifications") or []
    shipping_pr_drafts = input_data.get("shipping_out_pr_drafts") or []
    include_sar = input_data.get("include_shop_assembly_request", False)
    sar_request_number = input_data.get("shop_assembly_request_number")
    sar_openings_input = input_data.get("shop_assembly_openings") or []

    # 1. Project lookup/create
    project_stmt = (
        select(ProjectModel)
        .options(selectinload(ProjectModel.openings))
        .where(ProjectModel.project_id == project_input["project_id"])
    )
    project = session.scalars(project_stmt).unique().first()

    if project is None:
        # First import — create project + openings
        project = ProjectModel(
            id=uuid.uuid4(),
            project_id=project_input["project_id"],
            description=project_input.get("description"),
            job_site_name=project_input.get("job_site_name"),
            address=project_input.get("address"),
            city=project_input.get("city"),
            state=project_input.get("state"),
            zip=project_input.get("zip"),
            contractor=project_input.get("contractor"),
            project_manager=project_input.get("project_manager"),
            application=project_input.get("application"),
            submittal_job_no=project_input.get("submittal_job_no"),
            submittal_assignment_count=project_input.get("submittal_assignment_count"),
            estimator_code=project_input.get("estimator_code"),
            titan_user_id=project_input.get("titan_user_id"),
        )
        session.add(project)
        session.flush()

        for opening_input in openings_input:
            opening = OpeningModel(
                id=uuid.uuid4(),
                project_id=project.id,
                opening_number=opening_input["opening_number"],
                building=opening_input.get("building"),
                floor=opening_input.get("floor"),
                location=opening_input.get("location"),
                location_to=opening_input.get("location_to"),
                location_from=opening_input.get("location_from"),
                hand=opening_input.get("hand"),
                width=opening_input.get("width"),
                length=opening_input.get("length"),
                door_thickness=opening_input.get("door_thickness"),
                jamb_thickness=opening_input.get("jamb_thickness"),
                door_type=opening_input.get("door_type"),
                frame_type=opening_input.get("frame_type"),
                interior_exterior=opening_input.get("interior_exterior"),
                keying=opening_input.get("keying"),
                heading_no=opening_input.get("heading_no"),
                single_pair=opening_input.get("single_pair"),
                assignment_multiplier=opening_input.get("assignment_multiplier"),
            )
            session.add(opening)
        session.flush()

        # Re-load project with openings
        project = session.scalars(
            select(ProjectModel)
            .options(selectinload(ProjectModel.openings))
            .where(ProjectModel.id == project.id)
        ).unique().first()

    # Build opening_map: opening_number -> Opening.id
    opening_map: dict[str, uuid.UUID] = {
        o.opening_number: o.id for o in project.openings
    }

    # 2. Build classification map
    classification_map: dict[tuple[str, str, float], Classification] = {}
    for c in classifications_input:
        key = (c["hardware_category"], c["product_code"], c["unit_cost"])
        classification_map[key] = Classification(c["classification"])

    # 3. PO creation
    created_pos: list[POModel] = []
    if po_drafts:
        # Build hardware items lookup: (opening_number, product_code, material_id) -> hardware item data
        hw_items_lookup: dict[tuple[str, str, str], dict] = {}
        for hi in hardware_items_input:
            key = (hi["opening_number"], hi["product_code"], hi["material_id"])
            hw_items_lookup[key] = hi

        for po_draft in po_drafts:
            # Validate PO number uniqueness
            existing_po = session.scalars(
                select(POModel).where(POModel.po_number == po_draft["po_number"])
            ).first()
            if existing_po is not None:
                raise ConflictError(
                    f"Purchase order {po_draft['po_number']} already exists",
                    field="po_number",
                )

            # Create PO
            po = POModel(
                id=uuid.uuid4(),
                po_number=po_draft["po_number"],
                project_id=project.id,
                status=POStatus.DRAFT,
                vendor_name=po_draft.get("vendor_name"),
                vendor_contact=po_draft.get("vendor_contact"),
            )
            session.add(po)
            session.flush()

            # Collect hardware items for this PO and aggregate into line items
            # Key: (hardware_category, product_code, unit_cost, classification) -> list of HardwareItem models
            line_item_agg: dict[tuple, list] = defaultdict(list)

            for ref in po_draft.get("hardware_item_refs", []):
                ref_key = (ref["opening_number"], ref["product_code"], ref["material_id"])
                hi_data = hw_items_lookup.get(ref_key)
                if hi_data is None:
                    raise NotFoundError(
                        f"Hardware item not found: {ref_key}"
                    )

                opening_id = opening_map.get(ref["opening_number"])
                if opening_id is None:
                    raise NotFoundError(
                        f"Opening {ref['opening_number']} not found in project"
                    )

                unit_cost = hi_data.get("unit_cost") or 0.0
                class_key = (hi_data["hardware_category"], hi_data["product_code"], unit_cost)
                classification = classification_map.get(class_key, Classification.SITE_HARDWARE)

                # Create HardwareItem
                hw_item = HardwareItemModel(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    opening_id=opening_id,
                    hardware_category=hi_data["hardware_category"],
                    product_code=hi_data["product_code"],
                    material_id=hi_data["material_id"],
                    item_quantity=hi_data["item_quantity"],
                    unit_cost=Decimal(str(unit_cost)) if unit_cost else None,
                    unit_price=Decimal(str(hi_data["unit_price"])) if hi_data.get("unit_price") else None,
                    list_price=Decimal(str(hi_data["list_price"])) if hi_data.get("list_price") else None,
                    vendor_discount=Decimal(str(hi_data["vendor_discount"])) if hi_data.get("vendor_discount") else None,
                    markup_pct=Decimal(str(hi_data["markup_pct"])) if hi_data.get("markup_pct") else None,
                    vendor_no=hi_data.get("vendor_no"),
                    phase_code=hi_data.get("phase_code"),
                    item_category_code=hi_data.get("item_category_code"),
                    product_group_code=hi_data.get("product_group_code"),
                    submittal_id=hi_data.get("submittal_id"),
                    classification=classification,
                    state=HardwareItemState.IN_PO,
                )
                session.add(hw_item)

                agg_key = (
                    hi_data["hardware_category"],
                    hi_data["product_code"],
                    unit_cost,
                    classification,
                )
                line_item_agg[agg_key].append(hw_item)

            session.flush()

            # Create POLineItems from aggregation
            for (cat, code, cost, cls), hw_items in line_item_agg.items():
                total_qty = sum(hi.item_quantity for hi in hw_items)
                poli = POLineItemModel(
                    id=uuid.uuid4(),
                    po_id=po.id,
                    hardware_category=cat,
                    product_code=code,
                    classification=cls,
                    ordered_quantity=total_qty,
                    received_quantity=0,
                    unit_cost=Decimal(str(cost)) if cost else Decimal("0"),
                )
                session.add(poli)
                session.flush()

                # Update HardwareItems with po_line_item_id
                for hi in hw_items:
                    hi.po_line_item_id = poli.id

            created_pos.append(po)

    # 4. Shipping Out PRs
    created_prs: list[PullRequestModel] = []
    if shipping_pr_drafts:
        for pr_draft in shipping_pr_drafts:
            # Validate uniqueness
            existing_pr = session.scalars(
                select(PullRequestModel).where(
                    PullRequestModel.request_number == pr_draft["request_number"]
                )
            ).first()
            if existing_pr is not None:
                raise ConflictError(
                    f"Pull request {pr_draft['request_number']} already exists",
                    field="request_number",
                )

            pr = PullRequestModel(
                id=uuid.uuid4(),
                request_number=pr_draft["request_number"],
                project_id=project.id,
                source=PullRequestSource.SHIPPING_OUT,
                status=PullRequestStatus.PENDING,
                requested_by=pr_draft["requested_by"],
            )
            session.add(pr)
            session.flush()

            for item_input in pr_draft.get("items", []):
                item_type = PullRequestItemType(item_input["item_type"])
                pr_item = PullRequestItemModel(
                    id=uuid.uuid4(),
                    pull_request_id=pr.id,
                    item_type=item_type,
                    opening_number=item_input["opening_number"],
                    opening_item_id=uuid.UUID(str(item_input["opening_item_id"])) if item_input.get("opening_item_id") else None,
                    hardware_category=item_input.get("hardware_category"),
                    product_code=item_input.get("product_code"),
                    requested_quantity=item_input.get("requested_quantity", 1),
                )
                session.add(pr_item)

            created_prs.append(pr)

    # 5. SAR creation
    sar = None
    if include_sar and sar_request_number:
        # Validate uniqueness
        existing_sar = session.scalars(
            select(SARModel).where(SARModel.request_number == sar_request_number)
        ).first()
        if existing_sar is not None:
            raise ConflictError(
                f"Shop assembly request {sar_request_number} already exists",
                field="shop_assembly_request_number",
            )

        sar = SARModel(
            id=uuid.uuid4(),
            request_number=sar_request_number,
            project_id=project.id,
            status=ShopAssemblyRequestStatus.PENDING,
            created_by="Hardware Schedule Import",
        )
        session.add(sar)
        session.flush()

        for sa_opening_input in sar_openings_input:
            opening_id = opening_map.get(sa_opening_input["opening_number"])
            if opening_id is None:
                raise NotFoundError(
                    f"Opening {sa_opening_input['opening_number']} not found in project"
                )

            sa_opening = SAOModel(
                id=uuid.uuid4(),
                shop_assembly_request_id=sar.id,
                opening_id=opening_id,
                pull_status=PullStatus.NOT_PULLED,
                assembly_status=AssemblyStatus.PENDING,
            )
            session.add(sa_opening)
            session.flush()

            for item_input in sa_opening_input.get("items", []):
                sa_item = SAOItemModel(
                    id=uuid.uuid4(),
                    shop_assembly_opening_id=sa_opening.id,
                    hardware_category=item_input["hardware_category"],
                    product_code=item_input["product_code"],
                    quantity=item_input["quantity"],
                )
                session.add(sa_item)

    session.flush()

    return {
        "project": project,
        "purchase_orders": created_pos,
        "shipping_out_pull_requests": created_prs,
        "shop_assembly_request": sar,
    }
