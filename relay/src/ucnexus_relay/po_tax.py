"""The tax a PO REGISTRATION writes into GP, worked out the way GP works it out on an office PO
(issue #762).

eConnect never calculates PO tax: a schedule on the header and on every line still stores a tax of 0
and never calls the tax engine (proven on TUBC PO0000137). So the relay does the arithmetic, and the
shape it then writes is the one GP's own PO entry leaves behind - a tax row per line per detail, a
freight row and a misc row per detail, the per-line total on the line, and the totals on the header.
The one row it must NOT write is the ORD 0 summary per detail: taPopIvcTaxInsert builds that itself
by accumulating every row inserted under the detail, so a summary written by the caller is doubled
(TUCSH PO097491), which is also exactly what GP's client does to a PO that has a summary and no line
rows every time the office saves it (8 of 24 live UBC Nexus POs by 2026-09-18).

Everything here is pure arithmetic over Decimals; nothing touches GP. ops.create_po_op reads the
percents off TX00201 and hands them in, then writes the plan through econnect.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# GP's own ordinals for the two header charges in the PO tax table (POP10160). A freight row sits at
# the first and a misc row at the second on every office PO that taxes the charge; the line rows sit
# at the line's own ORD and the summary the proc builds sits at 0.
FREIGHT_TAX_ORD = 2147483646
MISC_TAX_ORD = 2147483645

_CENT = Decimal("0.01")


def to_cents(value: Decimal) -> Decimal:
    """Round the way GP displays money: to the cent, halves away from zero."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TaxDetail:
    """One purchase tax detail (TX00201, TXDTLTYP = 2) the PO user picked, with the percent read off
    GP at write time - never a percent the client sent."""

    tax_detail_id: str
    percent: Decimal


@dataclass(frozen=True)
class LineTax:
    """What one PO line carries: its taxable base net of its share of the trade discount, the tax
    per detail on that base, and the total across details (which is what taPoLine's TAXAMNT takes)."""

    line_ord: int
    taxable_base: Decimal
    tax_by_detail: dict[str, Decimal]

    @property
    def total(self) -> Decimal:
        return sum(self.tax_by_detail.values(), Decimal(0))


@dataclass(frozen=True)
class PoTaxPlan:
    """Every figure the registration writes, in the currency's cents, so the header cross-checks
    eConnect runs (887/888 on TAXAMNT, 892 on FRTTXAMT, 889 on a freight tax with no schedule) hold
    to the cent by construction: the header totals are sums of the rounded rows, never a separate
    rounding of the whole."""

    details: list[TaxDetail]
    lines: list[LineTax]
    freight_amount: Decimal
    misc_amount: Decimal
    freight_tax_by_detail: dict[str, Decimal] = field(default_factory=dict)
    misc_tax_by_detail: dict[str, Decimal] = field(default_factory=dict)

    @property
    def taxed(self) -> bool:
        return bool(self.details)

    @property
    def freight_taxed(self) -> bool:
        """The header's Purchase_Freight_Taxable: 1 when the charge is taxed, 2 when it is not, never
        0. A charge is taxed whenever the PO carries a detail at all, whatever its amount."""
        return self.taxed

    @property
    def misc_taxed(self) -> bool:
        return self.taxed

    @property
    def freight_tax_amount(self) -> Decimal:
        return sum(self.freight_tax_by_detail.values(), Decimal(0))

    @property
    def misc_tax_amount(self) -> Decimal:
        return sum(self.misc_tax_by_detail.values(), Decimal(0))

    @property
    def goods_tax_amount(self) -> Decimal:
        return sum((line.total for line in self.lines), Decimal(0))

    @property
    def tax_amount(self) -> Decimal:
        """Header TAXAMNT: goods plus freight plus misc tax, across every detail."""
        return self.goods_tax_amount + self.freight_tax_amount + self.misc_tax_amount

    def line_total(self, line_ord: int) -> Decimal:
        return next(line.total for line in self.lines if line.line_ord == line_ord)


def spread_trade_discount(extended_costs: list[Decimal], trade_discount: Decimal) -> list[Decimal]:
    """Each line's taxable base once the trade discount is netted off, spread the way GP spreads it
    on an office PO: pro rata by extended cost (UCSH PO032858, a 25 percent discount, carries every
    line's base at exactly 75 percent of its extended cost; PO098214's single line carries the
    subtotal less the whole discount). Every base is rounded to the cent and the last non-zero line
    absorbs the rounding, so the bases add up to the discounted subtotal exactly."""
    subtotal = sum(extended_costs, Decimal(0))
    if not trade_discount or subtotal == 0:
        return [to_cents(cost) for cost in extended_costs]
    bases = [to_cents(cost - cost * trade_discount / subtotal) for cost in extended_costs]
    residue = to_cents(subtotal - trade_discount) - sum(bases, Decimal(0))
    if residue:
        last = max(i for i, cost in enumerate(extended_costs) if cost) if any(extended_costs) else len(bases) - 1
        bases[last] += residue
    return bases


def plan_po_tax(
    *,
    lines: list[tuple[int, Decimal]],
    details: list[TaxDetail],
    trade_discount: Decimal = Decimal(0),
    freight_amount: Decimal = Decimal(0),
    misc_amount: Decimal = Decimal(0),
) -> PoTaxPlan:
    """Work out every tax figure for a PO from its lines ([(line_ord, extended_cost), ...] in ORD
    order), the picked details, and the three header charges.

    Per detail d at percent p: each line's tax is p of the line's discounted base, the freight tax is
    p of the freight, the misc tax is p of the misc - each rounded to the cent on its own, which is
    what GP shows per row. A PO with no detail plans no tax at all: bases still net the discount,
    every tax is 0, and the charges are flagged not taxable."""
    bases = spread_trade_discount([cost for _, cost in lines], trade_discount)
    planned_lines = [
        LineTax(
            line_ord=line_ord,
            taxable_base=base,
            tax_by_detail={d.tax_detail_id: to_cents(base * d.percent / 100) for d in details},
        )
        for (line_ord, _), base in zip(lines, bases)
    ]
    freight_tax = {d.tax_detail_id: to_cents(freight_amount * d.percent / 100) for d in details} if freight_amount else {}
    misc_tax = {d.tax_detail_id: to_cents(misc_amount * d.percent / 100) for d in details} if misc_amount else {}
    return PoTaxPlan(
        details=list(details),
        lines=planned_lines,
        freight_amount=freight_amount,
        misc_amount=misc_amount,
        freight_tax_by_detail=freight_tax,
        misc_tax_by_detail=misc_tax,
    )
