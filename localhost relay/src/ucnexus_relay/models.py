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
    buyer_id: str = Field(..., max_length=15)
    confirm_with: str = Field(..., max_length=20)
    doc_date: date
    currency_id: str = "CAD"
    vendor_address_code: str = "PRIMARY"
    shipping_method: str = "LOCAL DELIVERY"


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


# --- receiving (workflow 2) ---

class ReceiptLine(BaseModel):
    po_line_ord: int  # = POP10110.ORD / POLNENUM of the PO line being received (16384, 32768, ...)
    quantity: Decimal = Field(..., gt=0)


class ReceiptRequest(BaseModel):
    company: str
    po_number: str
    lines: list[ReceiptLine] = Field(..., min_length=1)
    batch_prefix: str = "EC"          # BACHNUMB = f"{batch_prefix}-{yyyy/MM/dd}" (legacy convention)
    receipt_date: date | None = None  # defaults to today


class ReceiptResponse(BaseModel):
    receipt_number: str
    batch_number: str
    po_number: str
    company: str
    lines_received: int
