"""The demo company's starting state (#1608).

The seed is built by running the app's own GraphQL mutations, in-process, as a demo identity - the same
mutations the screens send. So every seeded row is in a state the screens themselves produce, and when a
workflow changes shape the seed stops validating and the seed test fails in CI, instead of the demo
quietly drifting away from the app.

What it leaves behind, by module:

  - GP (simulated): four jobs, adopted as the demo company's projects through the job sync.
  - Warehouse: two buildings with shelf locations, shipment methods, a custom item type with an item,
    doors on hand.
  - Import: a hardware schedule on each project - openings, hardware, classifications, an item by
    others - with its PO requests and a shop assembly request.
  - POs: one in every status - draft, GP registered, vendor confirmed, partially received, closed and
    cancelled.
  - Receiving: drafts approved, waiting for approval and rejected; inventory on the shelf, a deficiency.
  - Shop assembly: requests waiting, batched with a pull being picked, batched and pulled, rejected.
  - Shipping: requests waiting, rejected and accepted; shipments scheduled, picked up, delivered and
    cancelled; a return.

The demo identity is not a Clerk account: its roles, company and demo flag are written straight into the
request context's memos, which is where `app.auth` would have put them after asking Clerk.
"""

import asyncio
import base64
import logging
from datetime import date, timedelta

from app.auth import TENANT_OWNER_ROLE, remember_display_name
from app.demo import DEMO_BUYER_ID, DEMO_COMPANY

logger = logging.getLogger(__name__)

SEED_USER_ID = "demo-seed"
SEED_USER_NAME = "Demo Seed"


class SeedError(Exception):
    """A seed step was refused. Carries the operation and the GraphQL errors, which name the step that
    no longer matches the app."""


def seed_context() -> dict:
    """A request context for the demo identity, with every memo `app.auth` would otherwise fill from Clerk."""
    return {
        "request": None,
        "_auth_user_id": SEED_USER_ID,
        "_auth_roles": [TENANT_OWNER_ROLE],
        "_auth_company": DEMO_COMPANY,
        "_auth_demo_mode": True,
    }


class Seeder:
    def __init__(self) -> None:
        # Imported here: main builds the schema out of every resolver module, and this module is imported by
        # one of them.
        from main import schema

        self._schema = schema
        self._context = seed_context()
        remember_display_name(SEED_USER_ID, SEED_USER_NAME)

    async def gql(self, document: str, **variables) -> dict:
        result = await self._schema.execute(document, variable_values=variables, context_value=self._context)
        if result.errors:
            raise SeedError(f"{document.split('(')[0].strip()}: {[e.message for e in result.errors]}")
        return result.data


# --- the catalog the schedules are written from --------------------------------------------------------

# (hardware category, product code, GP vendor, manufacturer, unit cost, classification). A category is
# GP's item number on the PO line; the classification decides whether the item is assembled in the shop
# or shipped loose to site.
HINGE = ("HINGE", "BB1279 4.5X4.5 US26D", "DEMOHAGER", "Hager", 12.5, "SITE_HARDWARE")
STOP = ("STOP", "WS406CVX US26D", "DEMOIVES", "Ives", 9.75, "SITE_HARDWARE")
EXIT = ("EXIT", "98-L-NL 26D", "DEMOVONDUP", "Von Duprin", 690.0, "SITE_HARDWARE")
CLOSER = ("CLOSER", "4040XP RW/PA AL", "DEMOLCN", "LCN", 185.0, "SHOP_HARDWARE")
LOCKSET = ("LOCKSET", "ND50PD RHO 626", "DEMOSCHLAGE", "Schlage", 240.0, "SHOP_HARDWARE")
# Supplied by somebody else, so it is on the schedule and never ordered.
WEATHERSTRIP = ("WSTRIP", "DOOR SEAL SET", None, "Pemko", 35.0, None)

VENDOR_NAMES = {
    "DEMOHAGER": "Demo Hager Hinges",
    "DEMOIVES": "Demo Ives Accessories",
    "DEMOVONDUP": "Demo Von Duprin Exits",
    "DEMOLCN": "Demo LCN Closers",
    "DEMOSCHLAGE": "Demo Schlage Locks",
}

# What each opening of a schedule carries: (item, quantity).
_OPENING_KIT = [(HINGE, 3), (STOP, 1), (CLOSER, 1), (LOCKSET, 1), (WEATHERSTRIP, 1)]
_EXIT_KIT = [(HINGE, 3), (STOP, 1), (EXIT, 1), (CLOSER, 1), (WEATHERSTRIP, 1)]


def _schedule(prefix: str, count: int, exits: int) -> tuple[list[dict], list[dict]]:
    """`count` openings numbered `<prefix>01`.., the last `exits` of them exit doors. Returns the openings
    and their hardware, in the shapes the import wizard sends."""
    openings, hardware = [], []
    for n in range(1, count + 1):
        number = f"{prefix}{n:02d}"
        openings.append(
            {
                "openingNumber": number,
                "building": "Main",
                "floor": str(1 + (n - 1) // 4),
                "location": f"Room {number}",
                "hand": "RH" if n % 2 else "LH",
                "width": "3'0\"",
                "length": "7'0\"",
                "doorType": "HM",
                "frameType": "HM",
                "singlePair": "Single",
                "leafCount": 1,
            }
        )
        for (category, product, vendor, manufacturer, cost, _cls), qty in (
            _EXIT_KIT if n > count - exits else _OPENING_KIT
        ):
            hardware.append(
                {
                    "openingNumber": number,
                    "productCode": product,
                    "hardwareCategory": category,
                    "itemQuantity": qty,
                    "unitCost": cost,
                    "manufacturer": manufacturer,
                    "vendorNo": vendor,
                }
            )
    return openings, hardware


def _po_drafts(hardware: list[dict]) -> list[dict]:
    """One PO request per vendor, claiming every unit of that vendor's hardware on the schedule."""
    by_vendor: dict[str, list[dict]] = {}
    for item in hardware:
        if item["vendorNo"]:
            by_vendor.setdefault(item["vendorNo"], []).append(item)
    return [
        {
            "vendorName": VENDOR_NAMES[vendor],
            "costCode": "210-100",
            "preferredDeliveryDate": (date.today() + timedelta(days=21)).isoformat(),
            "hardwareItemRefs": [
                {
                    "openingNumber": i["openingNumber"],
                    "productCode": i["productCode"],
                    "hardwareCategory": i["hardwareCategory"],
                    "quantity": i["itemQuantity"],
                }
                for i in items
            ],
        }
        for vendor, items in by_vendor.items()
    ]


def _classifications() -> list[dict]:
    return [
        {"hardwareCategory": c, "productCode": p, "unitCost": cost, "classification": cls}
        for c, p, _v, _m, cost, cls in (HINGE, STOP, EXIT, CLOSER, LOCKSET)
    ]


def _shop_items(hardware: list[dict], openings: list[str]) -> list[dict]:
    """The shop hardware of `openings`, as a shop assembly request's items."""
    shop = {CLOSER[0], LOCKSET[0]}
    return [
        {
            "openingNumber": i["openingNumber"],
            "hardwareCategory": i["hardwareCategory"],
            "productCode": i["productCode"],
            "quantity": i["itemQuantity"],
        }
        for i in hardware
        if i["openingNumber"] in openings and i["hardwareCategory"] in shop
    ]


def _pdf(text: str) -> str:
    """A one-page PDF saying `text`, base64-encoded - the packing slip a delivery is received against."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return base64.b64encode(bytes(out)).decode()


_PACKING_SLIP_PDF = _pdf("Demo packing slip - synthesized for demo mode")


# --- the GraphQL the seed sends ------------------------------------------------------------------------

_CREATE_WAREHOUSE = """
mutation CreateWarehouse($input: CreateWarehouseInput!) { createWarehouse(input: $input) { id } }
"""
_CREATE_LOCATION = """
mutation CreateWarehouseLocation($warehouseId: ID!, $aisle: String!, $row: String!, $bay: String!) {
  createWarehouseLocation(warehouseId: $warehouseId, aisle: $aisle, row: $row, bay: $bay) { id }
}
"""
_CREATE_SHIPMENT_METHOD = """
mutation CreateShipmentMethod($name: String!, $sortOrder: Int!) {
  createShipmentMethod(name: $name, sortOrder: $sortOrder) { id }
}
"""
_CREATE_ITEM_TYPE = """
mutation CreateInventoryItemType($name: String!, $code: String) {
  createInventoryItemType(name: $name, code: $code) { id attributes { id name } }
}
"""
_CREATE_ITEM_ATTRIBUTE = """
mutation CreateInventoryItemAttribute($typeId: ID!, $name: String!) {
  createInventoryItemAttribute(typeId: $typeId, name: $name) { id attributes { id name } }
}
"""
_CREATE_CUSTOM_ITEM = """
mutation CreateCustomInventoryItem($typeId: ID!, $productCode: String!, $description: String,
                                   $values: [CustomInventoryItemValueInput!]) {
  createCustomInventoryItem(typeId: $typeId, productCode: $productCode, description: $description,
                            values: $values) { id }
}
"""
_SAVE_DOORS_ON_HAND = """
mutation SaveDoorsOnHand($input: SaveDoorsOnHandInput!) { saveDoorsOnHand(input: $input) { company } }
"""
_SYNC_JOBS = "mutation SyncGpJobs { syncGpJobs { total adopted } }"
_PROJECTS = "query Projects { projects { id projectId } }"
_FINALIZE = """
mutation FinalizeImportSession($input: FinalizeImportSessionInput!) {
  finalizeImportSession(input: $input) {
    purchaseOrders {
      id vendorNameSnapshot
      lineItems { id hardwareCategory productCode orderedQuantity unitCost classification }
    }
    shopAssemblyRequest { id }
  }
}
"""
_REGISTER = """
mutation RegisterPoInGp($input: RegisterPOInput!) {
  registerPoInGp(input: $input) {
    queued
    purchaseOrder { id poNumber status lineItems { id hardwareCategory productCode orderedQuantity } }
  }
}
"""
_CANCEL_PO = "mutation CancelPo($id: ID!) { cancelPo(id: $id) { id status } }"
_UPLOAD_DOCUMENT = """
mutation UploadPoDocument($poId: ID!, $fileName: String!, $contentType: String!, $documentType: PODocumentType!,
                          $fileDataBase64: String!) {
  uploadPoDocument(poId: $poId, fileName: $fileName, contentType: $contentType, documentType: $documentType,
                   fileDataBase64: $fileDataBase64) { id }
}
"""
_CREATE_RECEIVE_DRAFT = """
mutation CreateReceiveDraft($input: CreateReceiveDraftInput!) { createReceiveDraft(input: $input) { id updatedAt } }
"""
_APPROVE_RECEIVE_DRAFT = """
mutation ApproveReceiveDraft($input: ApproveReceiveDraftInput!) {
  approveReceiveDraft(input: $input) { queued draft { status } }
}
"""
_REJECT_RECEIVE_DRAFT = """
mutation RejectReceiveDraft($input: RejectReceiveDraftInput!) { rejectReceiveDraft(input: $input) { status } }
"""
_UPDATE_PO_QUOTE = """
mutation UpdatePo($id: ID!, $vendorQuoteNumber: String, $expectedDeliveryDate: Date) {
  updatePo(id: $id, vendorQuoteNumber: $vendorQuoteNumber, expectedDeliveryDate: $expectedDeliveryDate) {
    id status
  }
}
"""
_CREATE_SHOP_BATCH = """
mutation CreateShopAssemblyBatch($input: CreateShopAssemblyBatchInput!) {
  createShopAssemblyBatch(input: $input) { id batches { id pullRequestId } }
}
"""
_REJECT_SHOP_REQUEST = """
mutation RejectShopAssemblyRequest($id: ID!, $reason: String) {
  rejectShopAssemblyRequest(id: $id, reason: $reason) { id status }
}
"""
_PICK_SHEET = """
query PullPickSheet($pullRequestId: ID!) {
  pullPickSheet(pullRequestId: $pullRequestId) {
    sections { hardwareCategory productCode remainingQuantity locations { inventoryLocationId available } }
  }
}
"""
_START_PICK = "mutation StartPullRequestPick($id: ID!) { startPullRequestPick(id: $id) { id status } }"
_CONFIRM_PICK = """
mutation ConfirmPick($pullRequestId: ID!, $lines: [PickLineInput!]!) {
  confirmPick(pullRequestId: $pullRequestId, lines: $lines) { outcome appliedQuantity }
}
"""
_COMPLETE_PULL = "mutation CompletePullRequest($id: ID!) { completePullRequest(id: $id) { id status } }"
_CREATE_SHIPPING_REQUEST = """
mutation CreateShippingOutRequest($input: CreateShippingOutRequestInput!) {
  createShippingOutRequest(input: $input) { id }
}
"""
_ACCEPT_SHIPPING_REQUEST = """
mutation AcceptShippingOutRequest($id: ID!) { acceptShippingOutRequest(id: $id) { id pullRequestId } }
"""
_REJECT_SHIPPING_REQUEST = """
mutation RejectShippingOutRequest($id: ID!, $reason: String) {
  rejectShippingOutRequest(id: $id, reason: $reason) { id status }
}
"""
_SHIP_READY = """
query ShipReadyItems($projectId: ID) {
  shipReadyItems(projectId: $projectId) { looseItems { openingNumber hardwareCategory productCode availableQuantity } }
}
"""
_CREATE_CONTAINER = """
mutation CreateShipmentContainer($projectId: ID!, $containerType: ShipmentContainerType!, $name: String!) {
  createShipmentContainer(projectId: $projectId, containerType: $containerType, name: $name) { id }
}
"""
_SET_CONTAINER_ITEMS = """
mutation SetContainerItems($input: SetContainerItemsInput!) { setContainerItems(input: $input) { id } }
"""
_CONFIRM_SHIPMENT = """
mutation ConfirmShipmentFromContainers($input: ConfirmShipmentFromContainersInput!) {
  confirmShipmentFromContainers(input: $input) { id packingSlipNumber items { id quantity } }
}
"""
_PICKED_UP = "mutation MarkShipmentPickedUp($id: ID!) { markShipmentPickedUp(id: $id) { id status } }"
_DELIVERED = "mutation MarkShipmentDelivered($id: ID!) { markShipmentDelivered(id: $id) { id status } }"
_INVENTORY_ROWS = """
query InventoryRows($projectId: ID) {
  inventoryRows(projectId: $projectId) { inventoryLocation { id hardwareCategory productCode available aisle } }
}
"""
_REPORT_DEFICIENCY = """
mutation ReportInventoryDeficiency($input: ReportInventoryDeficiencyInput!) {
  reportInventoryDeficiency(input: $input) { id }
}
"""
_MARK_UNLOCATED = """
mutation MarkInventoryUnlocated($id: ID!) { markInventoryUnlocated(inventoryLocationId: $id) { id } }
"""
_DESTOCK = "mutation DestockInventory($input: DestockInventoryInput!) { destockInventory(input: $input) { id } }"
_CREATE_RETURN = """
mutation CreateShipmentReturn($input: CreateShipmentReturnInput!) { createShipmentReturn(input: $input) { id } }
"""


# --- the steps -----------------------------------------------------------------------------------------


class _Demo:
    """The seed's working state: what earlier steps made that later ones act on."""

    def __init__(self, seeder: Seeder) -> None:
        self.s = seeder
        self.warehouse_id: str | None = None
        self.projects: dict[str, str] = {}  # job number -> project id
        self.schedules: dict[str, list[dict]] = {}  # job number -> hardware
        self.pos: dict[str, dict[str, dict]] = {}  # job number -> vendor -> PO
        self.shop_requests: dict[str, str] = {}  # job number -> shop assembly request id

    async def warehouse(self) -> None:
        data = await self.s.gql(
            _CREATE_WAREHOUSE,
            input={
                "name": "Demo Warehouse",
                "code": "DEMOWH",
                "address": "100 Demo Street",
                "city": "Toronto",
                "province": "ON",
                "postalCode": "A1A 1A1",
                "isPrimary": True,
            },
        )
        self.warehouse_id = data["createWarehouse"]["id"]
        for aisle in ("A", "B"):
            for row in ("1", "2"):
                for bay in ("1", "2", "3"):
                    await self.s.gql(_CREATE_LOCATION, warehouseId=self.warehouse_id, aisle=aisle, row=row, bay=bay)
        await self.s.gql(
            _CREATE_WAREHOUSE,
            input={"name": "Demo Overflow Yard", "code": "DEMOYD", "city": "Mississauga", "province": "ON"},
        )
        for n, name in enumerate(("Demo company truck", "Demo courier", "Customer pickup")):
            await self.s.gql(_CREATE_SHIPMENT_METHOD, name=name, sortOrder=n)

    async def catalog(self) -> None:
        item_type = (await self.s.gql(_CREATE_ITEM_TYPE, name="Demo Frames", code="DFRAME"))["createInventoryItemType"]
        for attribute in ("Gauge", "Profile"):
            item_type = (await self.s.gql(_CREATE_ITEM_ATTRIBUTE, typeId=item_type["id"], name=attribute))[
                "createInventoryItemAttribute"
            ]
        picks = {"Gauge": "16", "Profile": "5-3/4 DW"}
        values = [{"attributeId": a["id"], "value": picks[a["name"]]} for a in item_type["attributes"]]
        await self.s.gql(
            _CREATE_CUSTOM_ITEM,
            typeId=item_type["id"],
            productCode="DF-3070-16",
            description="3070 16ga welded frame",
            values=values,
        )

    async def projects_from_gp(self) -> None:
        await self.s.gql(_SYNC_JOBS)
        for project in (await self.s.gql(_PROJECTS))["projects"]:
            self.projects[project["projectId"]] = project["id"]

    async def doors_on_hand(self) -> None:
        await self.s.gql(_SAVE_DOORS_ON_HAND, input={"company": DEMO_COMPANY, "quantity": 40})
        await self.s.gql(
            _SAVE_DOORS_ON_HAND,
            input={"company": DEMO_COMPANY, "quantity": 12, "projectId": self.projects["DEMO-1001"]},
        )

    async def import_schedule(self, job: str, prefix: str, count: int, exits: int, shop_openings: int) -> None:
        openings, hardware = _schedule(prefix, count, exits)
        shop_for = [o["openingNumber"] for o in openings[:shop_openings]]
        data = (
            await self.s.gql(
                _FINALIZE,
                input={
                    "projectId": self.projects[job],
                    "openings": openings,
                    "hardwareItems": hardware,
                    "poDrafts": _po_drafts(hardware),
                    "classifications": _classifications(),
                    "excludedItems": [{"hardwareCategory": WEATHERSTRIP[0], "productCode": WEATHERSTRIP[1]}],
                    "includeShopAssemblyRequest": bool(shop_for),
                    "shopAssemblyItems": _shop_items(hardware, shop_for) if shop_for else None,
                    "scheduleFilename": f"{job}-hardware-schedule.xml",
                },
            )
        )["finalizeImportSession"]
        self.schedules[job] = hardware
        by_name = {name: vendor for vendor, name in VENDOR_NAMES.items()}
        self.pos[job] = {by_name[po["vendorNameSnapshot"]]: po for po in data["purchaseOrders"]}
        if data["shopAssemblyRequest"]:
            self.shop_requests[job] = data["shopAssemblyRequest"]["id"]

    async def register(self, job: str, vendor: str) -> dict:
        po = self.pos[job][vendor]
        data = (
            await self.s.gql(
                _REGISTER,
                input={
                    "poId": po["id"],
                    "gpVendorId": vendor,
                    "gpVendorName": VENDOR_NAMES[vendor],
                    "gpCompany": DEMO_COMPANY,
                    "buyerId": DEMO_BUYER_ID,
                    "projectId": self.projects[job],
                    "costCode": "210-100",
                    "shippingMethod": "LOCAL DELIVERY",
                    "vendorAddressCode": "PRIMARY",
                    "site": "MAIN",
                    "docDate": date.today().isoformat(),
                    "lineItems": [
                        {
                            "id": li["id"],
                            "hardwareCategory": li["hardwareCategory"],
                            "productCode": li["productCode"],
                            "orderedQuantity": li["orderedQuantity"],
                            "unitCost": li["unitCost"],
                            "classification": li["classification"],
                        }
                        for li in po["lineItems"]
                    ],
                    "idempotencyKey": f"demo-seed-register-{po['id']}",
                },
            )
        )["registerPoInGp"]
        self.pos[job][vendor] = {**po, **data["purchaseOrder"]}
        return self.pos[job][vendor]

    async def receive(
        self, job: str, vendor: str, *, fraction: float = 1.0, approve: bool = True, reject: bool = False
    ) -> None:
        """Count a receipt of `fraction` of every line of the PO onto the shelf, then approve or reject it,
        or leave it waiting for a manager."""
        po = self.pos[job][vendor]
        lines = []
        for n, li in enumerate(po["lineItems"]):
            qty = max(1, int(li["orderedQuantity"] * fraction)) if fraction < 1 else li["orderedQuantity"]
            shelf = {"aisle": "A" if n % 2 == 0 else "B", "row": "1", "bay": str(1 + n % 3), "quantity": qty}
            lines.append({"poLineItemId": li["id"], "quantityReceived": qty, "locations": [shelf]})
        slip = (
            await self.s.gql(
                _UPLOAD_DOCUMENT,
                poId=po["id"],
                fileName=f"packing-slip-{po['poNumber']}.pdf",
                contentType="application/pdf",
                documentType="PACKING_SLIP",
                fileDataBase64=_PACKING_SLIP_PDF,
            )
        )["uploadPoDocument"]
        draft = (
            await self.s.gql(
                _CREATE_RECEIVE_DRAFT,
                input={
                    "poId": po["id"],
                    "packingSlipDocumentId": slip["id"],
                    "warehouseId": self.warehouse_id,
                    "lineItems": lines,
                    "idempotencyKey": f"demo-seed-receive-{po['id']}-{fraction}",
                    "notes": "Counted at the dock.",
                },
            )
        )["createReceiveDraft"]
        if reject:
            await self.s.gql(
                _REJECT_RECEIVE_DRAFT,
                input={"draftId": draft["id"], "reason": "Count does not match the packing slip."},
            )
        elif approve:
            await self.s.gql(
                _APPROVE_RECEIVE_DRAFT,
                input={"draftId": draft["id"], "idempotencyKey": f"demo-seed-approve-{draft['id']}"},
            )

    async def vendor_confirm(self, job: str, vendor: str) -> None:
        """A vendor quote number and the vendor's acknowledgement on file: the PO is vendor confirmed."""
        po = self.pos[job][vendor]
        soon = (date.today() + timedelta(days=10)).isoformat()
        await self.s.gql(_UPDATE_PO_QUOTE, id=po["id"], vendorQuoteNumber="Q-DEMO-4471", expectedDeliveryDate=soon)
        await self.s.gql(
            _UPLOAD_DOCUMENT,
            poId=po["id"],
            fileName=f"acknowledgement-{po['poNumber']}.pdf",
            contentType="application/pdf",
            documentType="VENDOR_ACKNOWLEDGEMENT",
            fileDataBase64=_pdf(f"Demo vendor acknowledgement - {po['poNumber']}"),
        )

    async def shop_batch(self, job: str, openings: list[str]) -> str:
        """Batch `openings` of the job's shop assembly request; returns the pull the batch minted."""
        lines = [
            {
                "openingNumber": item["openingNumber"],
                "hardwareCategory": item["hardwareCategory"],
                "productCode": item["productCode"],
                "allocatedQuantity": item["quantity"],
            }
            for item in _shop_items(self.schedules[job], openings)
        ]
        request = (await self.s.gql(_CREATE_SHOP_BATCH, input={"requestId": self.shop_requests[job], "lines": lines}))[
            "createShopAssemblyBatch"
        ]
        return request["batches"][-1]["pullRequestId"]

    async def pick(self, pull_id: str, *, complete: bool = True) -> None:
        """Pick everything a pull asks for off the shelves, and finish it, or leave it being picked."""
        await self.s.gql(_START_PICK, id=pull_id)
        sheet = (await self.s.gql(_PICK_SHEET, pullRequestId=pull_id))["pullPickSheet"]
        lines = []
        for section in sheet["sections"]:
            remaining = section["remainingQuantity"]
            for location in section["locations"]:
                if remaining <= 0:
                    break
                take = min(remaining, location["available"])
                if take > 0:
                    lines.append(
                        {
                            "hardwareCategory": section["hardwareCategory"],
                            "productCode": section["productCode"],
                            "inventoryLocationId": location["inventoryLocationId"],
                            "quantity": take,
                        }
                    )
                    remaining -= take
        if not complete:
            return
        await self.s.gql(_CONFIRM_PICK, pullRequestId=pull_id, lines=lines)
        await self.s.gql(_COMPLETE_PULL, id=pull_id)

    async def shipping_request(self, job: str, openings: list[str]) -> str:
        """Ask for the site hardware of `openings` to be shipped. Returns the request."""
        site = {HINGE[0], STOP[0], EXIT[0]}
        items = [
            {
                "openingNumber": i["openingNumber"],
                "hardwareCategory": i["hardwareCategory"],
                "productCode": i["productCode"],
                "requestedQuantity": i["itemQuantity"],
            }
            for i in self.schedules[job]
            if i["openingNumber"] in openings and i["hardwareCategory"] in site
        ]
        data = await self.s.gql(_CREATE_SHIPPING_REQUEST, input={"projectId": self.projects[job], "items": items})
        return data["createShippingOutRequest"]["id"]

    async def stage(self, job: str, openings: list[str]) -> None:
        """Request, accept and pull the site hardware of `openings`, so it is staged and ready to ship."""
        request_id = await self.shipping_request(job, openings)
        accepted = (await self.s.gql(_ACCEPT_SHIPPING_REQUEST, id=request_id))["acceptShippingOutRequest"]
        await self.pick(accepted["pullRequestId"])

    async def ship(self, job: str, openings: list[str], name: str) -> dict:
        """Load what is staged for `openings` onto a skid and confirm the shipment: a scheduled delivery."""
        project_id = self.projects[job]
        ready = (await self.s.gql(_SHIP_READY, projectId=project_id))["shipReadyItems"]["looseItems"]
        items = [
            {
                "openingNumber": r["openingNumber"],
                "hardwareCategory": r["hardwareCategory"],
                "productCode": r["productCode"],
                "quantity": r["availableQuantity"],
            }
            for r in ready
            if r["openingNumber"] in openings and r["availableQuantity"] > 0
        ]
        container = (await self.s.gql(_CREATE_CONTAINER, projectId=project_id, containerType="SKID", name=name))[
            "createShipmentContainer"
        ]
        await self.s.gql(_SET_CONTAINER_ITEMS, input={"containerId": container["id"], "items": items})
        slip = await self.s.gql(
            _CONFIRM_SHIPMENT,
            input={
                "projectId": project_id,
                "containerIds": [container["id"]],
                "pickupDate": date.today().isoformat(),
                "deliveryDate": (date.today() + timedelta(days=2)).isoformat(),
                "shipmentMethod": "Demo company truck",
                "deliveryAddress": "100 Demo Street, Toronto ON",
                "contractorContactName": "Casey Contractor",
                "contractorContactPhone": "4165550199",
                "specialInstructions": "Deliver to the loading dock.",
            },
        )
        return slip["confirmShipmentFromContainers"]

    async def shelf_work(self, job: str) -> None:
        """What a warehouse does to a job's shelves over time: a unit found damaged, a row nobody can find,
        and an overage taken into the company's own stock."""
        rows = [
            r["inventoryLocation"]
            for r in (await self.s.gql(_INVENTORY_ROWS, projectId=self.projects[job]))["inventoryRows"]
        ]
        with_stock = sorted((r for r in rows if r["available"] >= 2 and r["aisle"]), key=lambda r: -r["available"])
        damaged, lost, overage = with_stock[0], with_stock[1], with_stock[2]
        await self.s.gql(
            _REPORT_DEFICIENCY,
            input={"inventoryLocationId": damaged["id"], "quantity": 1, "reasonText": "Finish scratched in transit."},
        )
        await self.s.gql(_MARK_UNLOCATED, id=lost["id"])
        await self.s.gql(
            _DESTOCK,
            input={
                "inventoryLocationId": overage["id"],
                "quantity": 1,
                "source": "OVERAGE",
                "destockCost": "KEEP",
                "reasonText": "Vendor shipped one extra.",
                "targetAisle": "B",
                "targetRow": "2",
                "targetBay": "3",
            },
        )


async def seed() -> None:
    """Build the demo company's starting state. Assumes it is empty - `demo_reset.reset` wipes it first."""
    demo = _Demo(Seeder())
    await demo.warehouse()
    await demo.catalog()
    await demo.projects_from_gp()
    await demo.doors_on_hand()

    # Tower A: everything ordered and received, then worked through the shop and out the door.
    tower = "DEMO-1001"
    await demo.import_schedule(tower, "A1", 10, 2, 4)
    for vendor in list(demo.pos[tower]):
        await demo.register(tower, vendor)
        await demo.receive(tower, vendor)
    # Shop: two openings batched and pulled to the shop, two batched with the pull still being picked.
    await demo.pick(await demo.shop_batch(tower, ["A101", "A102"]))
    await demo.pick(await demo.shop_batch(tower, ["A103", "A104"]), complete=False)
    # Shipping: a delivery that came back in part, one on the truck, one scheduled, one cancelled.
    await demo.stage(tower, ["A101", "A102"])
    delivered = await demo.ship(tower, ["A101", "A102"], "Skid 1")
    await demo.s.gql(_PICKED_UP, id=delivered["id"])
    await demo.s.gql(_DELIVERED, id=delivered["id"])
    returned = delivered["items"][0]
    await demo.s.gql(
        _CREATE_RETURN,
        input={
            "packingSlipId": delivered["id"],
            "warehouseId": demo.warehouse_id,
            "reference": "Site returned an extra",
            "items": [
                {
                    "packingSlipItemId": returned["id"],
                    "quantity": 1,
                    "disposition": "RETURN_TO_PROJECT",
                    "reasonText": "Delivered one too many.",
                }
            ],
        },
    )
    await demo.stage(tower, ["A103"])
    on_truck = await demo.ship(tower, ["A103"], "Skid 2")
    await demo.s.gql(_PICKED_UP, id=on_truck["id"])
    await demo.stage(tower, ["A104", "A105"])
    await demo.ship(tower, ["A104"], "Skid 3")
    # A scheduled shipment is cancelled by bringing every line back before a truck takes it.
    cancelled = await demo.ship(tower, ["A105"], "Skid 4")
    await demo.s.gql(
        _CREATE_RETURN,
        input={
            "packingSlipId": cancelled["id"],
            "warehouseId": demo.warehouse_id,
            "reference": "Delivery called off",
            "items": [
                {"packingSlipItemId": item["id"], "quantity": item["quantity"], "disposition": "RETURN_TO_PROJECT"}
                for item in cancelled["items"]
            ],
        },
    )
    # What came back off the cancelled delivery is pulled again and staged, waiting to be loaded.
    await demo.stage(tower, ["A105"])
    # A request accepted with its pull not started yet.
    accepted = await demo.shipping_request(tower, ["A109"])
    await demo.s.gql(_ACCEPT_SHIPPING_REQUEST, id=accepted)
    # And requests for the other openings: one waiting on the shipping manager, one turned down. A110 is
    # left for whoever tries a request of their own.
    await demo.shipping_request(tower, ["A106", "A107"])
    rejected = await demo.shipping_request(tower, ["A108"])
    await demo.s.gql(_REJECT_SHIPPING_REQUEST, id=rejected, reason="Site is not ready for this floor yet.")

    await demo.shelf_work(tower)

    # Hospital Wing: POs on their way - partially received, vendor confirmed, a count to approve - and a
    # shop request nobody has started.
    hospital = "DEMO-1002"
    await demo.import_schedule(hospital, "H2", 6, 1, 3)
    for vendor in list(demo.pos[hospital]):
        await demo.register(hospital, vendor)
    await demo.receive(hospital, "DEMOHAGER", fraction=0.5)
    await demo.receive(hospital, "DEMOLCN", approve=False)
    await demo.vendor_confirm(hospital, "DEMOSCHLAGE")

    # East High School: just imported - requests still to register, one cancelled, a rejected count, and
    # its shop request turned down.
    school = "DEMO-1003"
    await demo.import_schedule(school, "S3", 4, 0, 2)
    await demo.register(school, "DEMOHAGER")
    await demo.receive(school, "DEMOHAGER", fraction=0.5, reject=True)
    await demo.s.gql(_CANCEL_PO, id=demo.pos[school]["DEMOIVES"]["id"])
    await demo.s.gql(_REJECT_SHOP_REQUEST, id=demo.shop_requests[school], reason="Openings are being re-specified.")

    # Office Retrofit is left with no schedule: the project to try an import on.


def seed_blocking() -> None:
    """seed() from a thread with no event loop of its own - the test and the command line."""
    asyncio.run(seed())
