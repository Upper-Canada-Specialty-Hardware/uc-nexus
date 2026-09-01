"""What of a project edit reaches GP, and what does not (#497).

The job name and the site address live in both systems. Correcting them in Nexus alone left GP with
the old ones - and GP is what purchasing, accounting and the printed PO read, so a stale address
reached the vendor long after somebody had fixed it here.

These pin the payload builder, which is where every decision about the push actually lives: which
fields are GP's to hold, and when there is nothing worth sending.
"""

import uuid

from app.models.project import Project
from app.schemas.project import _gp_site_payload


def _project(**kwargs) -> Project:
    defaults = dict(
        id=uuid.uuid4(),
        project_id="23093",
        description="Cowichan District Hospital",
        address="123 Main St",
        city="Duncan",
        state="BC",
        zip="V9L 1A1",
    )
    defaults.update(kwargs)
    return Project(**defaults, company="TUBC")


def test_the_push_carries_the_job_name_and_the_site_address():
    payload = _gp_site_payload(_project())

    assert payload == {
        "job_number": "23093",
        "job_name": "Cowichan District Hospital",
        "address1": "123 Main St",
        "city": "Duncan",
        "state": "BC",
        "zip_code": "V9L 1A1",
    }


def test_nothing_else_on_the_project_is_pushed():
    """The GC contact, the estimator, the storage agreement are Nexus's alone. Sending them would
    mean inventing a place to put them in GP."""
    payload = _gp_site_payload(
        _project(
            gc_contact_name="Bob Builder",
            gc_phone="250-555-0100",
            contractor="Acme",
            project_manager="Paula",
            off_site_storage_agreement=True,
        )
    )

    assert set(payload) == {"job_number", "job_name", "address1", "city", "state", "zip_code"}


def test_a_half_filled_address_is_not_pushed():
    """A street with no city is not something GP can ship to. Writing it as a partial record would
    put an address on the job that looks filled in and is not."""
    payload = _gp_site_payload(_project(city=None))

    assert "address1" not in payload
    assert "city" not in payload
    # The name still goes - it is a separate field and it is still correct.
    assert payload["job_name"] == "Cowichan District Hospital"


def test_a_project_with_neither_a_name_nor_an_address_pushes_nothing():
    """None means the resolver skips the relay call entirely rather than making a no-op write
    against accounting data."""
    assert _gp_site_payload(_project(description=None, address=None, city=None)) is None


def test_whitespace_only_values_count_as_absent():
    assert _gp_site_payload(_project(description="   ", address="  ", city="  ")) is None


def test_the_optional_address_parts_are_sent_as_blanks_rather_than_dropped():
    """A cleared postcode has to reach GP as a clear, not as "leave what you have" - otherwise the
    old one survives a correction that was meant to remove it."""
    payload = _gp_site_payload(_project(state=None, zip=None))

    assert payload["state"] == ""
    assert payload["zip_code"] == ""
