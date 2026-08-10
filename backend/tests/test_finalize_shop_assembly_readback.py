"""The finalize resolver's shop-assembly read-back.

`finalize_import_session` creates the shop-assembly request and its reservation; the finalize resolver
then re-reads that request to build its response. The read-back called
`shop_assembly_repository.get_request_with_openings`, which does not exist - so every assembly-purpose
finalize crashed with AttributeError *after* the request and its reservation had already been
committed (observed live 2026-08-10). The real reader is `get_shop_assembly_request`, which loads the
request with its flat lines, and `shop_assembly_request_to_type` walks exactly those lines.

This reproduces the two calls the resolver runs post-commit, so a regression to a reader that does not
load the lines (or does not exist) fails here. DB-backed, so it skips where DATABASE_URL is unset, as
local dev is.
"""

from app.repositories import import_repository, shop_assembly_repository
from app.schemas.converters import shop_assembly_request_to_type

from .inventory_fixtures import make_il, make_project


def test_finalize_shop_assembly_request_reads_back_through_the_resolver_path(db_session):
    project = make_project(db_session)
    # The creation gate reserves what the line takes, so the combo has to be genuinely available.
    make_il(db_session, project, quantity=5, category="HINGE", code="HG-100")

    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {
                    "opening_number": "A01",
                    "hardware_category": "HINGE",
                    "product_code": "HG-100",
                    "quantity": 2,
                },
            ],
        },
    )
    sar = result["shop_assembly_request"]
    assert sar is not None

    # Exactly the two calls the finalize resolver makes after commit. The bug was the first one naming
    # a repository function that never existed; the second walks the lines the first must have loaded.
    refreshed = shop_assembly_repository.get_shop_assembly_request(db_session, sar.id)
    typed = shop_assembly_request_to_type(refreshed)

    assert str(typed.id) == str(sar.id)
    assert len(typed.items) == 1
    assert (typed.items[0].hardware_category, typed.items[0].product_code) == ("HINGE", "HG-100")
