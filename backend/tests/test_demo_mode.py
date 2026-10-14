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
from app.errors import ConflictError, DemoModeChangedError, ValidationError
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
    # Refused, not answered with the account's own company (#1633): that answer was a real company's rows
    # under a tab that still believed it was in demo mode.
    with pytest.raises(DemoModeChangedError):
        tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", header=DEMO_COMPANY))


def test_an_admin_in_demo_mode_works_in_it_by_header():
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], demo=True, header=DEMO_COMPANY)) == DEMO_COMPANY


def test_an_admin_out_of_demo_mode_is_refused_the_demo_company():
    # Its own code, so a tab still sending DEMO after demo mode was turned off elsewhere reloads (#1633).
    with pytest.raises(DemoModeChangedError, match="turned off"):
        tenant_scope(_Info([NEXUS_ADMIN_ROLE], header=DEMO_COMPANY))


def test_a_scoped_tab_left_in_demo_mode_is_refused_rather_than_shown_the_real_company():
    # #1633: the account left demo mode in another tab; this one still shows the banner and sends DEMO.
    # Before, the header was ignored and the real company's rows came back under the demo banner.
    with pytest.raises(DemoModeChangedError, match="turned off"):
        tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", header=DEMO_COMPANY))


def test_a_scoped_tab_that_missed_demo_mode_turning_on_is_refused():
    with pytest.raises(DemoModeChangedError, match="turned on"):
        tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", demo=True, header="TUBC"))


def test_a_scoped_tab_on_the_right_side_of_demo_mode_is_answered():
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", header="TUBC")) == "TUBC"
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", demo=True, header=DEMO_COMPANY)) == DEMO_COMPANY
    # No header at all (a script, an old tab) is answered by the account alone, as before.
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", demo=True)) == DEMO_COMPANY


def test_the_demo_company_is_refused_while_a_reset_runs_except_to_the_seed(monkeypatch):
    # #1635: half a company is not shown or written to; the seed itself goes through.
    from app import demo
    from app.auth import DEMO_SEEDING_KEY

    monkeypatch.setattr(demo, "_reset_running", SimpleNamespace(is_set=lambda: True))
    with pytest.raises(ConflictError, match="being reset"):
        tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", demo=True))
    with pytest.raises(ConflictError, match="being reset"):
        tenant_scope(_Info([NEXUS_ADMIN_ROLE], demo=True, header=DEMO_COMPANY))
    seeding = _Info([TENANT_OWNER_ROLE], company=DEMO_COMPANY, demo=True)
    seeding.context[DEMO_SEEDING_KEY] = True
    assert tenant_scope(seeding) == DEMO_COMPANY
    # A real company is never held up by a demo reset.
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC")) == "TUBC"


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


@pytest.mark.parametrize("enabled", [True, False])
def test_any_account_turns_demo_mode_on_and_off_for_itself(monkeypatch, enabled):
    # #1629: no admin role needed either way - a Warehouse Manager is enough.
    from app.schemas import demo as demo_schema
    from main import schema

    resets, writes = [], []

    async def _reset(*, only_if_empty=False):
        resets.append(only_if_empty)
        return True

    def _write(user_id, on):
        writes.append((user_id, on))
        return {
            "id": user_id,
            "first_name": "",
            "last_name": "",
            "email": "",
            "roles": [],
            "image_url": "",
            "demo_mode": on,
        }

    monkeypatch.setattr(demo_schema.demo_reset, "reset", _reset)
    monkeypatch.setattr(demo_schema.user_repository, "update_user_demo_mode", _write)
    result = asyncio.run(
        schema.execute(
            "mutation M($on: Boolean!) { setMyDemoMode(enabled: $on) { demoMode } }",
            variable_values={"on": enabled},
            context_value={"request": None, "_auth_user_id": "u_wm", "_auth_roles": ["Warehouse Manager"]},
        )
    )
    assert result.errors is None
    assert result.data == {"setMyDemoMode": {"demoMode": enabled}}
    assert writes == [("u_wm", enabled)]
    # Turning it on seeds a demo company nobody has seeded yet; turning it off touches nothing.
    assert resets == ([True] if enabled else [])


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
    from app.repositories import demo_snapshot_repository
    from app.services import demo_reset, storage

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(user_repository, "get_user_demo_mode", lambda user_id: False)
        # The made-up seed alone, whatever legacy export this database has stored (#1638 tests that one).
        mp.setattr(demo_snapshot_repository, "rows", lambda session: [])
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


def test_seeded_drafts_carry_a_cost_code_the_job_offers(seeded):
    # #1630: the register dialog matches a draft's code against GP's list as `code-element`; a bare
    # `210-100` matched nothing, so every seeded draft opened in an error state.
    from app.database import SessionLocal
    from app.models.purchase_order import PurchaseOrder
    from app.services.demo_gp import COST_CODE_MASTER

    offered = {f"{c['cost_code']}-{c['cost_element']}" for c in COST_CODE_MASTER}
    with SessionLocal() as session:
        codes = set(session.scalars(select(PurchaseOrder.cost_code).where(PurchaseOrder.company == DEMO_COMPANY)))
    assert codes and codes <= offered


def test_the_waiting_shop_request_can_be_batched_as_it_stands(seeded):
    # #1649: read the way the batch review reads it. Every opening of the request nobody has started has
    # its shop hardware free, so Create batch is open the moment a demo user opens it.
    from app.services.demo_seed import Seeder

    async def _review():
        s = Seeder()
        waiting = (await s.gql("{ shopAssemblyRequests(status: PENDING) { id requestNumber } }"))[
            "shopAssemblyRequests"
        ]
        assert waiting
        review = await s.gql(
            "query R($id: ID!) { shopAssemblyAllocationReview(requestId: $id) { openings { openingNumber"
            " lines { requestedQuantity availableQuantity notShopWorkReason } } } }",
            id=waiting[0]["id"],
        )
        return review["shopAssemblyAllocationReview"]["openings"]

    openings = asyncio.run(_review())
    assert openings
    for opening in openings:
        shop_lines = [ln for ln in opening["lines"] if not ln["notShopWorkReason"]]
        assert shop_lines and all(ln["availableQuantity"] >= ln["requestedQuantity"] for ln in shop_lines), opening


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
            # The seed's GP-first writes left ledger rows for the demo company; a real one stays (#1635).
            from app.models.gp_write import GpWriteIdempotency

            demo_ledger = (
                select(func.count())
                .select_from(GpWriteIdempotency)
                .where(GpWriteIdempotency.relay_result["company"].as_string() == DEMO_COMPANY)
            )
            assert session.scalar(demo_ledger) > 0
            session.add(GpWriteIdempotency(key="real-ledger-row", op="create_po", relay_result={"company": "TUBC"}))
            session.flush()
            demo_reset.wipe(session)
            session.flush()
            assert demo_reset.demo_rows(session) == {}
            assert session.scalar(select(func.count()).select_from(DemoGpRecord)) == 0
            assert session.scalar(demo_ledger) == 0
            assert session.get(GpWriteIdempotency, "real-ledger-row") is not None
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


def test_the_full_reset_is_refused_from_demo_mode(monkeypatch):
    # #1634: it wipes every real company, and from demo mode the reset anybody means is the demo one.
    from fastapi.testclient import TestClient

    import app.config
    import main

    monkeypatch.setattr(app.config, "TESTING_ENABLED", True, raising=False)
    admin = {"user_id": "u_admin", "roles": [NEXUS_ADMIN_ROLE]}
    monkeypatch.setattr(main, "require_admin_request", lambda request: admin)
    monkeypatch.setattr(user_repository, "get_user_demo_mode", lambda user_id: True)
    resp = TestClient(main.app).post("/admin/reset-data")
    assert resp.status_code == 403
    assert "demo mode" in resp.json()["error"]
