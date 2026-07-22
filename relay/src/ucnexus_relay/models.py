"""Pydantic request/response models. The PI<->JOBNUMBR invariant is enforced here,
before any SQL connection is opened."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class NextNumberRequest(BaseModel):
    company: str


class POLine(BaseModel):
    item_number: str = Field(..., max_length=30)
    item_description: str = Field(..., max_length=100)
    quantity: Decimal
    unit_cost: Decimal
    location_code: str = "VANCOUVER"
    uofm: str = "Each"
    product_indicator: int = 1  # 1 = Non-Inventoried, 2 = Job Cost
    job_number: str | None = None
    cost_code: str | None = None  # 'phase-step-type' e.g. '210-200-2'
    # captured manufacturer -> taPoLine USRDEFND1 (POP10110). char(50) in GP; create_po_line RTRIMs +
    # truncates to 50 when binding, so an over-length value is capped there. No max_length guard here:
    # rejecting at the model boundary would fail the whole PO over an optional annotation field.
    manufacturer: str | None = None

    @model_validator(mode="after")
    def check_job_cost_consistency(self):
        if self.product_indicator == 2:
            if not self.job_number or not self.cost_code:
                raise ValueError("Job-cost lines (product_indicator=2) require both job_number and cost_code")
        elif self.product_indicator == 1:
            if self.job_number or self.cost_code:
                raise ValueError("Non-inventoried lines (product_indicator=1) must not have job_number or cost_code")
        else:
            raise ValueError(f"product_indicator must be 1 or 2 (got {self.product_indicator})")
        return self


class POHeader(BaseModel):
    vendor_id: str = Field(..., max_length=15)
    # optional: when omitted, the relay fills BUYERID from the workstation (see buyers.resolve_buyer).
    # an explicit value here overrides the relay's device-based resolution.
    buyer_id: str | None = Field(default=None, max_length=15)
    confirm_with: str = Field(..., max_length=20)
    doc_date: date
    # currency_id is informational only: the relay resolves the PO currency GP-first from the vendor
    # master (PM00200.CURNCYID) at create time and ignores whatever is sent here (issue #257).
    currency_id: str = "CAD"
    vendor_address_code: str = "PRIMARY"
    shipping_method: str = "LOCAL DELIVERY"
    # Issue #257: order-time GP charges. tax_detail_id is a GP purchase tax detail (TX00201,
    # TXDTLTYP=2) the user picked; the relay looks up its rate and computes the tax. The three
    # dollar amounts are entered on the register form. All optional; a PO with none is valid.
    tax_detail_id: str | None = Field(default=None, max_length=15)
    trade_discount: Decimal = Decimal(0)
    freight_amount: Decimal = Decimal(0)
    misc_amount: Decimal = Decimal(0)


class CreatePoRequest(BaseModel):
    company: str
    header: POHeader
    lines: list[POLine] = Field(..., min_length=1)
    # UC Nexus supplies its own PO number (e.g. 'ucnexus...'). GP's PONUMBER is char(17),
    # so max 17 chars. If omitted, the relay reserves GP's next 'PO' number via taGetPONextNumber.
    po_number: str | None = Field(default=None, max_length=17)

    @model_validator(mode="after")
    def normalize_po_number(self):
        if self.po_number is not None:
            self.po_number = self.po_number.strip()
            if not self.po_number:
                raise ValueError("po_number, if provided, must not be blank")
        return self


class CreatePoResponse(BaseModel):
    po_number: str
    company: str
    lines_created: int
    subtotal: Decimal
    doc_date: date
    vendor_id: str
    # Issue #257: resolved GP-first from the vendor master, and the tax the relay computed from the
    # chosen tax detail (0 when none was picked). Returned so the backend can snapshot them.
    currency: str = "CAD"
    tax_amount: Decimal = Decimal(0)


# --- receiving (workflow 2) ---

class ReceiptLine(BaseModel):
    po_line_ord: int  # = POP10110.ORD / POLNENUM of the PO line being received (16384, 32768, ...)
    quantity: Decimal = Field(..., gt=0)
    # rack location the goods were physically shelved at (WHRECLINE101.Location). GP has no field for
    # this; it's the whole reason WHRECLINE101 exists. required (the legacy app rejects a blank rack).
    rack_location: str = Field(..., min_length=1, max_length=255)
    revision_number: str | None = Field(default=None, max_length=255)
    comments: str | None = None


class ReceiptRequest(BaseModel):
    company: str
    po_number: str
    lines: list[ReceiptLine] = Field(..., min_length=1)
    batch_prefix: str = "EC"          # BACHNUMB = f"{batch_prefix}-{yyyy/MM/dd}" (legacy convention)
    receipt_date: date | None = None  # defaults to today
    received_by: str | None = Field(default=None, max_length=255)  # WHRECLINE101.UpdatingUser; default = SQL login


class ReceiptResponse(BaseModel):
    receipt_number: str
    batch_number: str
    po_number: str
    company: str
    lines_received: int
    custom_db_written: bool  # whether the WHRECLINE101 rows were written (false for sandboxes / unmapped companies)


# --- vendor sync (feeds Vendor.gp_vendor_id in UC Nexus) ---

class VendorOut(BaseModel):
    vendor_id: str       # GP VENDORID (char 15)
    vendor_name: str     # GP VENDNAME
    vendor_class: str | None = None  # GP VNDCLSID
    status: int          # GP VENDSTTS (1 = active)
    currency: str = "CAD"  # GP CURNCYID, blank -> 'CAD' (issue #257: vendor dictates PO currency)


class VendorsResponse(BaseModel):
    company: str
    vendors: list[VendorOut]


# --- tax details (per-company, feeds the register-PO tax-detail dropdown - issue #257) ---

class TaxDetailOut(BaseModel):
    tax_detail_id: str          # GP TAXDTLID (purchase detail, TX00201 TXDTLTYP=2)
    description: str | None = None  # GP TXDTLDSC
    percent: float              # GP TXDTLPCT (the rate the relay computes tax with)


class TaxDetailsResponse(BaseModel):
    company: str
    tax_details: list[TaxDetailOut]


class BuyersResponse(BaseModel):
    company: str
    buyers: list[str]  # registered GP buyer IDs (POP00101) for the Create PO buyer dropdown


# --- cost codes (per-job, feeds the Create PO cost-code dropdown) ---

class CostCodeOut(BaseModel):
    cost_code: str                  # two-segment number 'cc1-cc2' e.g. '310-000'
    description: str | None = None  # GP Cost_Code_Description
    cost_element: int               # GP Cost_Element (varies by code: 2/3/5/6/...); the /po trailing digit


class CostCodesResponse(BaseModel):
    company: str
    job: str
    cost_codes: list[CostCodeOut]
