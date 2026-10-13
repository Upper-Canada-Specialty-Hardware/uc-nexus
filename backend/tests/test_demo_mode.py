"""Demo mode (#1608): the demo company, its simulated GP, its seed and its reset.

Three groups:

  - who ends up in the demo company, and who never does (tenant scope, the admin header, the company
    list, assigning an account) - no database needed;
  - the simulated GP: a call for the demo company is answered without the relay socket, and a real
    company is never answered by it;
  - the seed and the reset, against the database: the seed runs the app's own mutations, so this is the
    test that fails when a workflow changes shape under it. It checks every module has rows in every
    state its screens act on, that a reset leaves no demo row behind, and that no real company's rows or
    numbering move.
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text

from app.auth import NEXUS_ADMIN_ROLE, TENANT_OWNER_ROLE, tenant_scope
from app.demo import DEMO_COMPANY
from app.errors import ValidationError
from app.repositories import user_repository
from app.schemas import relay as relay_module
from app.services import demo_gp, nexus_companies
from app.services.relay_gateway import RelayGateway

# --- who is in the demo company ------------------------------------------------------------------------


class _Request:
    def __init__(self, company: str | None = None):
        self.headers = {"authorization": "Bearer tok"}
        if company is not None:
            self.headers["X-Nexus-Company"] = company


class _Info:
    def __init__(self, roles, *, company=None, demo=False, header=None):
        self.context = {
            "request": _Request(header),
            "_auth_user_id": "u_test",
            "_auth_roles": roles,
            "_auth_company": company,
            "_auth_demo_mode": demo,
        }


def test_a_scoped_account_in_demo_mode_is_pinned_to_the_demo_company():
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", demo=True)) == DEMO_COMPANY


def test_an_account_out_of_demo_mode_keeps_its_own_company():
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC")) == "TUBC"


def test_the_company_less_tools_keep_the_real_company_in_demo_mode():
    # User management is about whose accounts a tenant owner runs, not about the data.
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", demo=True), cross_tenant=True) == "TUBC"


def test_a_scoped_account_cannot_reach_the_demo_company_by_header():
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", header=DEMO_COMPANY)) == "TUBC"


def test_an_admin_in_demo_mode_works_in_it_by_header():
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], demo=True, header=DEMO_COMPANY)) == DEMO_COMPANY


def test_an_admin_out_of_demo_mode_is_refused_the_demo_company():
    with pytest.raises(ValidationError, match="demo mode"):
        tenant_scope(_Info([NEXUS_ADMIN_ROLE], header=DEMO_COMPANY))


def test_the_demo_company_is_not_in_the_admin_switcher(monkeypatch):
    monkeypatch.setattr(nexus_companies, "relay_gateway", SimpleNamespace(companies=["TUBC"], company_names={}))

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def scalars(self, stmt):
            return ["TUBC", DEMO_COMPANY, "OLDCO"]

    monkeypatch.setattr(nexus_companies, "SessionLocal", _Session)
    assert [code for code, _ in nexus_companies.list_companies()] == ["OLDCO", "TUBC"]
    assert not nexus_companies.is_known_company(DEMO_COMPANY)


def test_the_demo_company_cannot_be_assigned_to_an_account(monkeypatch):
    monkeypatch.setattr(user_repository, "_merge_public_metadata", lambda *a: pytest.fail("must not write"))
    with pytest.raises(ValidationError, match="demo mode"):
        user_repository.update_user_company("u_test", "demo")


def test_only_a_caller_in_demo_mode_reads_the_demo_company_gp():
    with pytest.raises(ValidationError, match="demo mode"):
        relay_module.resolve_gp_company(_Info([TENANT_OWNER_ROLE], company="TUBC"), DEMO_COMPANY)
    assert (
        relay_module.resolve_gp_company(_Info([TENANT_OWNER_ROLE], company="TUBC", demo=True), "demo") == DEMO_COMPANY
    )


# --- the simulated GP ----------------------------------------------------------------------------------


def test_a_demo_call_never_reaches_the_relay_socket(monkeypatch):
    gateway = RelayGateway()  # nothing connected
    calls = []

    async def _fake(op, payload):
        calls.append(op)
        return {"company": DEMO_COMPANY, "vendors": []}

    monkeypatch.setattr(demo_gp, "call", _fake)
    assert asyncio.run(gateway.relay_call(DEMO_COMPANY, "list_vendors")) == {"company": DEMO_COMPANY, "vendors": []}
    assert calls == ["list_vendors"]
    assert gateway.has_feature("create_po_idempotency", DEMO_COMPANY)
    assert not gateway.has_feature("create_po_idempotency", "TUBC")


def test_the_simulated_gp_answers_every_op_the_backend_sends():
    # Every op name the backend passes to the gateway, read off the relay's own op table: the simulation
    # must not be the place a workflow finds an op missing.
    from pathlib import Path

    channel = Path(__file__).resolve().parents[2] / "relay" / "src" / "ucnexus_relay" / "channel.py"
    if not channel.exists():
        pytest.skip("relay sources not present")
    source = channel.read_text(encoding="utf-8")
    table = source[source.index("_OPS = {") : source.index("}", source.index("_OPS = {"))]
    relay_ops = {line.split('"')[1] for line in table.splitlines() if line.strip().startswith('"')}
    assert relay_ops <= demo_gp.OPS, sorted(relay_ops - demo_gp.OPS)


# --- the seed and the reset ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seeded(_migrate_database):
    """Reset the demo company once for the module, with storage stood in for (the packing slips and
    acknowledgements the seed uploads), and wipe it again afterwards."""
    from app.database import SessionLocal
    from app.services import demo_reset, storage

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(user_repository, "get_user_demo_mode", lambda user_id: False)
        mp.setattr(storage, "upload_file", lambda key, data, content_type, **kw: key)
        mp.setattr(storage, "delete_file", lambda key: None)
        with SessionLocal() as session:
            before = _real_numbering(session)
        asyncio.run(demo_reset.reset())
        yield before
        with SessionLocal() as session:
            demo_reset.wipe(session)
            session.commit()


def _real_numbering(session) -> dict:
    return {
        "packing_slip_counter": session.scalar(text("SELECT next_value FROM packing_slip_counter")),
        "po_request_max": session.scalar(
            text("SELECT max(CAST(substring(request_number from '^PO-REQ-([0-9]+)$') AS bigint)) FROM purchase_orders")
        ),
    }


def _states(session, sql: str) -> set:
    return {row[0] for row in session.execute(text(sql))}


def test_the_seed_puts_every_module_in_every_state(seeded):
    from app.database import SessionLocal

    demo = f"'{DEMO_COMPANY}'"
    with SessionLocal() as session:
        assert session.scalar(text(f"SELECT count(*) FROM projects WHERE company = {demo}")) == 4
        assert _states(session, f"SELECT status FROM purchase_orders WHERE company = {demo}") == {
            "DRAFT",
            "GP_REGISTERED",
            "VENDOR_CONFIRMED",
            "PARTIALLY_RECEIVED",
            "CLOSED",
            "CANCELLED",
        }
        assert _states(
            session,
            f"SELECT d.status FROM receive_drafts d JOIN purchase_orders p ON p.id = d.po_id WHERE p.company = {demo}",
        ) == {"PENDING_APPROVAL", "APPROVED", "REJECTED"}
        assert _states(
            session,
            "SELECT s.status FROM shop_assembly_requests s JOIN projects p ON p.id = s.project_id "
            f"WHERE p.company = {demo}",
        ) == {"PENDING", "APPROVED", "REJECTED"}
        assert _states(
            session,
            "SELECT r.source || ':' || r.status FROM pull_requests r JOIN projects p ON p.id = r.project_id "
            f"WHERE p.company = {demo}",
        ) >= {"SHIPPING_OUT:PENDING", "SHIPPING_OUT:COMPLETED", "SHOP_ASSEMBLY:IN_PROGRESS", "SHOP_ASSEMBLY:COMPLETED"}
        assert _states(
            session,
            "SELECT s.status FROM shipping_out_requests s JOIN projects p ON p.id = s.project_id "
            f"WHERE p.company = {demo}",
        ) == {"PENDING", "APPROVED", "REJECTED"}
        assert _states(
            session,
            f"SELECT s.status FROM packing_slips s JOIN projects p ON p.id = s.project_id WHERE p.company = {demo}",
        ) == {"SCHEDULED", "PICKED_UP", "DELIVERED", "CANCELLED"}
        assert session.scalar(
            text(
                "SELECT count(*) FROM shipment_returns r JOIN packing_slips s ON s.id = r.packing_slip_id "
                f"JOIN projects p ON p.id = s.project_id WHERE p.company = {demo}"
            )
        )
        located = _states(
            session,
            "SELECT i.aisle IS NOT NULL FROM inventory_locations i JOIN projects p ON p.id = i.project_id "
            f"WHERE p.company = {demo}",
        )
        assert located == {True, False}
        assert session.scalar(
            text(
                "SELECT count(*) FROM inventory_locations i JOIN projects p ON p.id = i.project_id "
                f"WHERE p.company = {demo} AND i.deficient_quantity > 0"
            )
        )
        stock = "SELECT count(*) FROM stock_items s JOIN warehouses w ON w.id = s.warehouse_id WHERE w.company = "
        assert session.scalar(text(stock + demo))
        for table in ("warehouses", "shipment_methods", "inventory_item_types", "doors_on_hand"):
            assert session.scalar(text(f"SELECT count(*) FROM {table} WHERE company = {demo}")), table


def test_demo_numbering_leaves_the_real_sequences_alone(seeded):
    from app.database import SessionLocal

    with SessionLocal() as session:
        assert _real_numbering(session) == seeded
        numbers = set(
            session.scalars(text(f"SELECT request_number FROM purchase_orders WHERE company = '{DEMO_COMPANY}'"))
        )
        assert numbers and all(n.startswith("PO-REQ-D") for n in numbers)
        slips = set(
            session.scalars(
                text(
                    "SELECT s.packing_slip_number FROM packing_slips s JOIN projects p ON p.id = s.project_id "
                    f"WHERE p.company = '{DEMO_COMPANY}'"
                )
            )
        )
        assert slips and all(n.startswith("PS-D") for n in slips)


def test_the_seed_leaves_hardware_staged_for_shipping(seeded):
    # Read the way the Staging screen reads it, as a caller in the demo company.
    from app.services.demo_seed import Seeder

    async def _staged():
        s = Seeder()
        projects = (await s.gql("{ projects { id projectId } }"))["projects"]
        tower = next(p["id"] for p in projects if p["projectId"] == "DEMO-1001")
        ready = await s.gql(
            "query R($p: ID) { shipReadyItems(projectId: $p) { looseItems { availableQuantity } } }", p=tower
        )
        return sum(i["availableQuantity"] for i in ready["shipReadyItems"]["looseItems"])

    assert asyncio.run(_staged()) > 0


def test_a_reset_leaves_no_demo_row_and_no_real_row_behind(seeded):
    from app.database import SessionLocal
    from app.models.demo_gp_record import DemoGpRecord
    from app.models.project import Project
    from app.services import demo_reset

    with SessionLocal() as session:
        real = Project(company="REALCO", project_id="REAL-1", description="a real job")
        session.add(real)
        session.commit()
        real_id = real.id
        try:
            assert demo_reset.demo_rows(session)
            demo_reset.wipe(session)
            session.flush()
            assert demo_reset.demo_rows(session) == {}
            assert session.scalar(select(func.count()).select_from(DemoGpRecord)) == 0
            assert session.get(Project, real_id) is not None
        finally:
            session.rollback()
            session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": real_id})
            session.commit()


def test_relay_status_tells_demo_from_the_header_alone():
    # Polled by every tab, so it must answer without asking Clerk who is calling: no identity memo here.
    assert relay_module._in_demo(SimpleNamespace(context={"request": _Request(DEMO_COMPANY)}))
    assert not relay_module._in_demo(SimpleNamespace(context={"request": _Request("TUBC")}))
    assert not relay_module._in_demo(SimpleNamespace(context={"request": None}))


def test_a_seed_that_fails_part_way_leaves_nothing_behind(_migrate_database, monkeypatch):
    from app.database import SessionLocal
    from app.models.project import Project
    from app.services import demo_reset, demo_seed

    async def _half_a_seed():
        with SessionLocal() as session:
            session.add(Project(company=DEMO_COMPANY, project_id="DEMO-HALF", description="half"))
            session.commit()
        raise RuntimeError("a workflow changed under the seed")

    monkeypatch.setattr(demo_seed, "seed", _half_a_seed)
    with pytest.raises(RuntimeError):
        asyncio.run(demo_reset.reset())
    # Nothing half-built is left, so the next first entry seeds from the start.
    assert not demo_reset.has_demo_data()
