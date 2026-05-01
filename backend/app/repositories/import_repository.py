"""Repository for hardware schedule import operations."""

import uuid
from collections import defaultdict
from decimal import Decimal
from math import floor

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, NotFoundError
from app.models.enums import (
    AssemblyStatus,
    Classification,
    HardwareItemState,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.opening_item import OpeningItemHardware as OpeningItemHardwareModel
from app.models.project import Opening as OpeningModel
from app.models.project import Project as ProjectModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.shop_assembly import (
    ShopAssemblyOpening as SAOModel,
)
from app.models.shop_assembly import (
    ShopAssemblyOpeningItem as SAOItemModel,
)
from app.models.shop_assembly import (
    ShopAssemblyRequest as SARModel,
)


def get_project_hardware_schedule(
    session: Session,
    project_id: uuid.UUID,
) -> dict | None:
    """Load a project's persisted hardware schedule (openings + items) for wizard hydration."""
    project = (
        session.scalars(
            select(ProjectModel).where(ProjectModel.id == project_id).options(selectinload(ProjectModel.openings))
        )
        .unique()
        .first()
    )
    if project is None:
        return None

    opening_number_by_id = {o.id: o.opening_number for o in project.openings}

    hardware_items = session.scalars(select(HardwareItemModel).where(HardwareItemModel.project_id == project_id)).all()

    return {
        "project": project,
        "openings": list(project.openings),
        "hardware_items": [
            {
                "opening_number": opening_number_by_id.get(hi.opening_id, ""),
                "product_code": hi.product_code,
                "material_id": hi.material_id or str(hi.id),
                "hardware_category": hi.hardware_category,
                "item_quantity": hi.item_quantity,
                "unit_cost": float(hi.unit_cost) if hi.unit_cost is not None else None,
                "unit_price": float(hi.unit_price) if hi.unit_price is not None else None,
                "list_price": float(hi.list_price) if hi.list_price is not None else None,
                "vendor_discount": float(hi.vendor_discount) if hi.vendor_discount is not None else None,
                "markup_pct": float(hi.markup_pct) if hi.markup_pct is not None else None,
                "vendor_no": hi.vendor_no,
                "phase_code": hi.phase_code,
                "item_category_code": hi.item_category_code,
                "product_group_code": hi.product_group_code,
                "submittal_id": hi.submittal_id,
            }
            for hi in hardware_items
        ],
    }


def reconcile_schedule(
    session: Session,
    project_id: uuid.UUID,
    items: list[dict],
) -> list[dict]:
    """Compare needed items against existing HardwareItem lifecycle state."""
    from app.models.project_excluded_item import ProjectExcludedItem as PEIModel

    # Pre-load excluded items for this project
    excluded_rows = session.scalars(select(PEIModel).where(PEIModel.project_id == project_id)).all()
    excluded_set = {(r.hardware_category, r.product_code) for r in excluded_rows}

    results = []

    # Separate excluded (BY_OTHERS) items from items needing lifecycle queries
    lifecycle_items = []
    for item in items:
        if (item["hardware_category"], item["product_code"]) in excluded_set:
            results.append(
                {
                    "opening_number": item["opening_number"],
                    "hardware_category": item["hardware_category"],
                    "product_code": item["product_code"],
                    "quantity": item["quantity_needed"],
                    "status": "BY_OTHERS",
                }
            )
        else:
            lifecycle_items.append(item)

    if not lifecycle_items:
        return results

    pairs = list({(item["opening_number"], item["product_code"]) for item in lifecycle_items})

    # ---- Bulk Query 1: HardwareItems linked to non-cancelled, non-deleted POs ----
    hi_stmt = (
        select(
            OpeningModel.opening_number,
            HardwareItemModel.product_code,
            HardwareItemModel.item_quantity,
            POModel.status.label("po_status"),
            POLineItemModel.ordered_quantity,
            POLineItemModel.received_quantity,
        )
        .join(OpeningModel, HardwareItemModel.opening_id == OpeningModel.id)
        .join(POLineItemModel, HardwareItemModel.po_line_item_id == POLineItemModel.id)
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            HardwareItemModel.project_id == project_id,
            POModel.status != POStatus.CANCELLED,
            POModel.deleted_at.is_(None),
            tuple_(OpeningModel.opening_number, HardwareItemModel.product_code).in_(pairs),
        )
    )
    hi_by_pair: dict[tuple[str, str], list] = defaultdict(list)
    for row in session.execute(hi_stmt).all():
        hi_by_pair[(row.opening_number, row.product_code)].append(row)

    # ---- Bulk Query 2: PullRequest aggregates ----
    pr_stmt = (
        select(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.product_code,
            PullRequestModel.source,
            PullRequestModel.status,
            func.sum(PullRequestItemModel.requested_quantity).label("total_pulled"),
        )
        .join(PullRequestItemModel, PullRequestItemModel.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.project_id == project_id,
            PullRequestModel.status != PullRequestStatus.CANCELLED,
            tuple_(PullRequestItemModel.opening_number, PullRequestItemModel.product_code).in_(pairs),
        )
        .group_by(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.product_code,
            PullRequestModel.source,
            PullRequestModel.status,
        )
    )
    pr_by_pair: dict[tuple[str, str], list] = defaultdict(list)
    for row in session.execute(pr_stmt).all():
        pr_by_pair[(row.opening_number, row.product_code)].append(row)

    # ---- Bulk Query 3: OpeningItemHardware shipped + assembled sums ----
    oi_stmt = (
        select(
            OpeningItemModel.opening_number,
            OpeningItemHardwareModel.product_code,
            OpeningItemModel.state,
            func.sum(OpeningItemHardwareModel.quantity).label("qty"),
        )
        .join(OpeningItemModel, OpeningItemHardwareModel.opening_item_id == OpeningItemModel.id)
        .where(
            OpeningItemModel.project_id == project_id,
            OpeningItemModel.state.in_(
                [OpeningItemState.SHIPPED_OUT, OpeningItemState.IN_INVENTORY, OpeningItemState.SHIP_READY]
            ),
            tuple_(OpeningItemModel.opening_number, OpeningItemHardwareModel.product_code).in_(pairs),
        )
        .group_by(
            OpeningItemModel.opening_number,
            OpeningItemHardwareModel.product_code,
            OpeningItemModel.state,
        )
    )
    shipped_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    assembled_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    for row in session.execute(oi_stmt).all():
        key = (row.opening_number, row.product_code)
        if row.state == OpeningItemState.SHIPPED_OUT:
            shipped_by_pair[key] += row.qty or 0
        else:
            assembled_by_pair[key] += row.qty or 0

    # ---- Process each item using pre-loaded data ----
    for item in lifecycle_items:
        opening_number = item["opening_number"]
        hardware_category = item["hardware_category"]
        product_code = item["product_code"]
        quantity_needed = item["quantity_needed"]
        pair_key = (opening_number, product_code)

        # Step 2: Bucket quantities by PO status
        buckets: dict[str, int] = defaultdict(int)
        for row in hi_by_pair.get(pair_key, []):
            hi_qty = row.item_quantity
            po_status = row.po_status

            if po_status == POStatus.DRAFT:
                buckets["PO_DRAFTED"] += hi_qty
            elif po_status in (POStatus.ORDERED, POStatus.VENDOR_CONFIRMED):
                buckets["ORDERED"] += hi_qty
            elif po_status == POStatus.PARTIALLY_RECEIVED:
                if row.ordered_quantity > 0:
                    ratio = row.received_quantity / row.ordered_quantity
                else:
                    ratio = 0
                received_portion = floor(hi_qty * ratio)
                ordered_portion = hi_qty - received_portion
                if received_portion > 0:
                    buckets["RECEIVED"] += received_portion
                if ordered_portion > 0:
                    buckets["ORDERED"] += ordered_portion
            elif po_status == POStatus.CLOSED:
                buckets["RECEIVED"] += hi_qty

        # Step 3: PR deductions
        received_qty = buckets.get("RECEIVED", 0)
        if received_qty > 0:
            for pr_row in pr_by_pair.get(pair_key, []):
                pulled_qty = pr_row.total_pulled or 0
                deduct = min(pulled_qty, received_qty)
                if deduct <= 0:
                    continue

                if pr_row.source == PullRequestSource.SHOP_ASSEMBLY:
                    if pr_row.status in (PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS):
                        buckets["ASSEMBLING"] += deduct
                        received_qty -= deduct
                    elif pr_row.status == PullRequestStatus.COMPLETED:
                        buckets["ASSEMBLED"] += deduct
                        received_qty -= deduct
                elif pr_row.source == PullRequestSource.SHIPPING_OUT:
                    if pr_row.status in (PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS):
                        buckets["SHIPPING_OUT"] += deduct
                        received_qty -= deduct
                    elif pr_row.status == PullRequestStatus.COMPLETED:
                        buckets["SHIPPED_OUT"] += deduct
                        received_qty -= deduct

            buckets["RECEIVED"] = max(0, received_qty)

        # Step 4: Shipped cross-check
        oi_shipped = shipped_by_pair.get(pair_key, 0)
        existing_shipped = buckets.get("SHIPPED_OUT", 0)
        if oi_shipped > existing_shipped:
            extra = oi_shipped - existing_shipped
            from_received = min(extra, buckets.get("RECEIVED", 0))
            buckets["RECEIVED"] = max(0, buckets.get("RECEIVED", 0) - from_received)
            buckets["SHIPPED_OUT"] = existing_shipped + from_received

        # Step 4b: Assembled cross-check
        oi_assembled = assembled_by_pair.get(pair_key, 0)
        existing_assembled = buckets.get("ASSEMBLED", 0)
        if oi_assembled > existing_assembled:
            extra = oi_assembled - existing_assembled
            from_received = min(extra, buckets.get("RECEIVED", 0))
            buckets["RECEIVED"] = max(0, buckets.get("RECEIVED", 0) - from_received)
            buckets["ASSEMBLED"] = existing_assembled + from_received

        # Step 5: Calculate NOT_COVERED gap
        total_committed = sum(buckets.values())
        gap = max(0, quantity_needed - total_committed)
        if gap > 0:
            buckets["NOT_COVERED"] = gap

        # Step 6: Generate result rows
        for status_key, qty in buckets.items():
            if qty > 0:
                results.append(
                    {
                        "opening_number": opening_number,
                        "hardware_category": hardware_category,
                        "product_code": product_code,
                        "quantity": qty,
                        "status": status_key,
                    }
                )

    return results


def finalize_import_session(
    session: Session,
    input_data: dict,
) -> dict:
    """Finalize an import session: attach openings/POs/PRs/SAR to an existing project atomically."""
    project_id = uuid.UUID(input_data["project_id"])
    openings_input = input_data.get("openings", [])
    hardware_items_input = input_data.get("hardware_items") or []
    po_drafts = input_data.get("po_drafts") or []
    classifications_input = input_data.get("classifications") or []
    excluded_items_input = input_data.get("excluded_items") or []
    shipping_pr_drafts = input_data.get("shipping_out_pr_drafts") or []
    include_sar = input_data.get("include_shop_assembly_request", False)
    sar_request_number = input_data.get("shop_assembly_request_number")
    sar_openings_input = input_data.get("shop_assembly_openings") or []

    # 1. Project lookup (must already exist)
    project_stmt = (
        select(ProjectModel).options(selectinload(ProjectModel.openings)).where(ProjectModel.id == project_id)
    )
    project = session.scalars(project_stmt).unique().first()

    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    # Create any NEW openings from this import (idempotent across re-imports)
    existing_opening_numbers = {o.opening_number for o in project.openings}
    for opening_input in openings_input:
        if opening_input["opening_number"] not in existing_opening_numbers:
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
            project.openings.append(opening)
    session.flush()

    # Build opening_map: opening_number -> Opening.id
    opening_map: dict[str, uuid.UUID] = {o.opening_number: o.id for o in project.openings}

    # 2. Build classification map
    classification_map: dict[tuple[str, str, float], Classification] = {}
    for c in classifications_input:
        key = (c["hardware_category"], c["product_code"], c["unit_cost"])
        classification_map[key] = Classification(c["classification"])

    # 2b. Manage project excluded items (By Others scope classification)
    if excluded_items_input is not None:
        from app.models.project_excluded_item import ProjectExcludedItem as PEIModel

        new_excluded_set = {(ei["hardware_category"], ei["product_code"]) for ei in excluded_items_input}

        # Load existing exclusions for this project
        existing_exclusions = session.scalars(select(PEIModel).where(PEIModel.project_id == project.id)).all()
        existing_set = {(e.hardware_category, e.product_code): e for e in existing_exclusions}

        # Add new exclusions
        for hw_cat, prod_code in new_excluded_set:
            if (hw_cat, prod_code) not in existing_set:
                session.add(
                    PEIModel(
                        id=uuid.uuid4(),
                        project_id=project.id,
                        hardware_category=hw_cat,
                        product_code=prod_code,
                    )
                )

        # Remove exclusions that are no longer By Others (user reclassified to By UCSH)
        for key, entity in existing_set.items():
            if key not in new_excluded_set:
                session.delete(entity)

        session.flush()

    # 3. PO creation
    created_pos: list[POModel] = []
    if po_drafts:
        # Build hardware items lookup: (opening_number, product_code, hardware_category) -> hardware item data
        hw_items_lookup: dict[tuple[str, str, str], dict] = {}
        for hi in hardware_items_input:
            key = (hi["opening_number"], hi["product_code"], hi["hardware_category"])
            hw_items_lookup[key] = hi

        # Generate request_number sequence for new POs
        from app.repositories.po_repository import generate_next_request_number

        next_request_number = generate_next_request_number(session)
        next_seq = int(next_request_number.replace("PO-REQ-", ""))

        for po_draft in po_drafts:
            # Validate PO number uniqueness within project if provided
            po_number = po_draft.get("po_number")
            if po_number and po_number.strip():
                existing_po = session.scalars(
                    select(POModel).where(
                        POModel.project_id == project.id,
                        POModel.po_number == po_number,
                        POModel.deleted_at.is_(None),
                    )
                ).first()
                if existing_po is not None:
                    raise ConflictError(
                        f"Purchase order {po_number} already exists in this project",
                        field="po_number",
                    )
            else:
                po_number = None

            # Auto-generate request_number
            request_number = f"PO-REQ-{next_seq:03d}"
            next_seq += 1

            # Resolve vendor_id (validate FK target exists if provided)
            vendor_id_str = po_draft.get("vendor_id")
            vendor_id = uuid.UUID(vendor_id_str) if vendor_id_str else None
            if vendor_id is not None:
                from app.models.vendor import Vendor as VendorModel

                if session.get(VendorModel, vendor_id) is None:
                    raise NotFoundError(f"Vendor {vendor_id} not found")

            # Create PO
            po = POModel(
                id=uuid.uuid4(),
                po_number=po_number,
                request_number=request_number,
                project_id=project.id,
                status=POStatus.DRAFT,
                vendor_id=vendor_id,
                notes=po_draft.get("notes"),
            )
            session.add(po)
            session.flush()

            # Collect hardware items for this PO and aggregate into line items
            # Key: (hardware_category, product_code, unit_cost, classification) -> list of HardwareItem models
            line_item_agg: dict[tuple, list] = defaultdict(list)

            for ref in po_draft.get("hardware_item_refs", []):
                ref_key = (ref["opening_number"], ref["product_code"], ref["hardware_category"])
                hi_data = hw_items_lookup.get(ref_key)
                if hi_data is None:
                    raise NotFoundError(f"Hardware item not found: {ref_key}")

                opening_id = opening_map.get(ref["opening_number"])
                if opening_id is None:
                    raise NotFoundError(f"Opening {ref['opening_number']} not found in project")

                unit_cost = hi_data.get("unit_cost") or 0.0
                class_key = (hi_data["hardware_category"], hi_data["product_code"], unit_cost)
                classification = classification_map.get(class_key)

                # Create HardwareItem
                hw_item = HardwareItemModel(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    opening_id=opening_id,
                    hardware_category=hi_data["hardware_category"],
                    product_code=hi_data["product_code"],
                    item_quantity=hi_data["item_quantity"],
                    unit_cost=Decimal(str(unit_cost)) if unit_cost else None,
                    unit_price=Decimal(str(hi_data["unit_price"])) if hi_data.get("unit_price") else None,
                    list_price=Decimal(str(hi_data["list_price"])) if hi_data.get("list_price") else None,
                    vendor_discount=(
                        Decimal(str(hi_data["vendor_discount"])) if hi_data.get("vendor_discount") else None
                    ),
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

            # Build alias lookup from line_item_aliases
            alias_lookup: dict[tuple[str, str], str] = {}
            for alias_entry in po_draft.get("line_item_aliases", []):
                key = (alias_entry["hardware_category"], alias_entry["product_code"])
                alias_lookup[key] = alias_entry["order_as"]

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
                    order_as=alias_lookup.get((cat, code)),
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
                select(PullRequestModel).where(PullRequestModel.request_number == pr_draft["request_number"])
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
                    opening_item_id=(
                        uuid.UUID(str(item_input["opening_item_id"])) if item_input.get("opening_item_id") else None
                    ),
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
        existing_sar = session.scalars(select(SARModel).where(SARModel.request_number == sar_request_number)).first()
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
                raise NotFoundError(f"Opening {sa_opening_input['opening_number']} not found in project")

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
