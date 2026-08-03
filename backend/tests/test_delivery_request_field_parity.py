"""The Delivery Request header says the same twenty things everywhere it is written down (#453).

The header used to be enumerated longhand roughly seventeen times across the stack - the migration,
the model, the repository tuple, both mutation inputs, the GraphQL type, the converter, two SDL
reference files, the frontend selection and five shapes in the shipping module. A twenty-first field
could then drift in two directions, and neither broke the build or any test:

- missing from `DELIVERY_REQUEST_FIELDS`, so GraphQL accepts the field and the repository never
  persists or clears it. The form saves and the value is gone.
- missing from the frontend field list, so it saves, reads back undefined, and prints blank on the
  paper the site signs.

Most of those copies are gone: the inputs share a Strawberry base, the converter iterates the tuple,
and the frontend derives its shapes and its GraphQL selection from one list. What is left cannot be
collapsed - a SQLAlchemy column and a Strawberry field both need a real annotation - so this file
holds the survivors against each other instead.

It reads across the monorepo into `frontend/`, deliberately. Cross-stack drift is the failure being
guarded against, and a test that only compared the Python copies would have passed through the whole
of the bug it exists to prevent.

No database: everything here is model metadata, the built schema, and one file read.
"""

import re
from pathlib import Path

from app.models.shipping import PackingSlip as PackingSlipModel
from app.repositories.shipping_repository import DELIVERY_REQUEST_FIELDS
from main import schema

_graphql_schema = schema._schema

# What a packing slip records that is NOT the paper form: which shipment it is, and where the truck
# got to. Named rather than derived, because that is the whole point - adding a column to PackingSlip
# fails this file until somebody says which of the two it is, which is the decision that kept being
# skipped.
_SLIP_IDENTITY_COLUMNS = {
    "id",
    "packing_slip_number",
    "project_id",
    "status",
    "shipped_by",
    "shipped_at",
    "created_at",
}
_SLIP_LIFECYCLE_COLUMNS = {"picked_up_at", "picked_up_by", "delivered_at", "delivered_by"}

_FRONTEND_FIELD_LIST = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "deliveryRequestFields.ts"


def _camel(field: str) -> str:
    head, *rest = field.split("_")
    return head + "".join(part.title() for part in rest)


def _input_fields(name: str) -> set[str]:
    return set(_graphql_schema.type_map[name].fields)


def _frontend_fields() -> list[str]:
    source = _FRONTEND_FIELD_LIST.read_text(encoding="utf-8")
    body = re.search(r"DELIVERY_REQUEST_FIELDS = \[(.*?)\] as const;", source, re.S)
    assert body, f"no DELIVERY_REQUEST_FIELDS array in {_FRONTEND_FIELD_LIST}"
    return re.findall(r"'([^']+)'", body.group(1))


def test_the_tuple_names_every_header_column_and_nothing_else():
    """The repository tuple is what writes and clears the header, so a column it does not name is a
    column the form can display and never change."""
    columns = {c.name for c in PackingSlipModel.__table__.columns}
    header = columns - _SLIP_IDENTITY_COLUMNS - _SLIP_LIFECYCLE_COLUMNS

    assert header == set(DELIVERY_REQUEST_FIELDS)


def test_both_mutation_inputs_carry_the_whole_header():
    """`confirmShipment` writes the header and `updateShipmentDetails` rewrites it. A field on one
    and not the other is a field that can be set and never corrected, or corrected and never set.

    Asserted against the built schema rather than the classes: the shared base is flattened into
    each input by Strawberry, and the caller only ever sees the flattened result."""
    header = {_camel(field) for field in DELIVERY_REQUEST_FIELDS}

    assert _input_fields("ConfirmShipmentInput") == header | {"projectId", "packingSlipNumber", "items"}
    assert _input_fields("UpdateShipmentDetailsInput") == header | {"id"}


def test_the_packing_slip_type_returns_the_whole_header():
    """A field the client can write but not read back prints blank on the reprint."""
    header = {_camel(field) for field in DELIVERY_REQUEST_FIELDS}

    assert header <= _input_fields("PackingSlip")


def test_the_frontend_list_agrees_with_the_backend_tuple():
    """Same names, same order. The frontend list drives both the GraphQL selection and every form
    shape, so a name that disagrees here is a box on the form that saves and reads back blank."""
    assert _frontend_fields() == [_camel(field) for field in DELIVERY_REQUEST_FIELDS]
