"""#740: every shop assembly request names the GP job it was raised for.

The Shop Assembly Manager works several jobs' requests in one list, and the header used to carry only
the request number. The job is resolved for the whole list in one query, never per row.
"""

import uuid

from app.models.enums import ShopAssemblyRequestStatus
from app.models.project import Project
from app.models.shop_assembly import ShopAssemblyRequest
from app.schemas.shop_assembly import _requests_to_types


def _request(session, project) -> ShopAssemblyRequest:
    req = ShopAssemblyRequest(
        id=uuid.uuid4(),
        request_number=f"SAR-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=ShopAssemblyRequestStatus.PENDING,
        created_by="pm",
    )
    session.add(req)
    session.flush()
    return req


def test_each_request_carries_its_own_jobs_number_and_name(db_session):
    hospital = Project(id=uuid.uuid4(), company="TUBC", project_id="80001", description="Cowichan Dist Hospital")
    terminal = Project(id=uuid.uuid4(), company="TUBC", project_id="80003", description="Sea Bus Terminal")
    db_session.add_all([hospital, terminal])
    db_session.flush()
    reqs = [_request(db_session, hospital), _request(db_session, terminal)]

    types = _requests_to_types(db_session, reqs)

    assert [(t.project_number, t.project_name) for t in types] == [
        ("80001", "Cowichan Dist Hospital"),
        ("80003", "Sea Bus Terminal"),
    ]


def test_an_empty_list_asks_for_nothing(db_session):
    assert _requests_to_types(db_session, []) == []
