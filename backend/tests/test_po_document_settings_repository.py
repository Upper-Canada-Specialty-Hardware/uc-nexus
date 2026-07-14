"""Tests for the single-row PO-document boilerplate settings repository (issue #230)."""

from datetime import date

from app.repositories import po_document_settings_repository as repo


def test_get_settings_creates_default_on_first_read(db_session):
    settings = repo.get_settings(db_session)

    # Seeded from the guideline doc.
    assert settings.tax_numbers == repo.DEFAULT_TAX_NUMBERS
    assert settings.mandatory_bullets == repo.DEFAULT_MANDATORY_BULLETS
    assert settings.shipping_accounts == repo.DEFAULT_SHIPPING_ACCOUNTS
    assert settings.shipping_methods == repo.DEFAULT_SHIPPING_METHODS
    assert settings.customs_broker_block == repo.DEFAULT_CUSTOMS_BROKER_BLOCK
    assert settings.usa_tariff_effective_until == repo.DEFAULT_USA_TARIFF_EFFECTIVE_UNTIL
    assert settings.company_from_address == repo.DEFAULT_COMPANY_FROM_ADDRESS
    assert settings.signature_note == repo.DEFAULT_SIGNATURE_NOTE


def test_get_settings_is_a_singleton(db_session):
    first = repo.get_settings(db_session)
    second = repo.get_settings(db_session)
    assert first.id == second.id


def test_update_settings_patches_only_supplied_fields(db_session):
    repo.get_settings(db_session)  # seed the row

    updated = repo.update_settings(
        db_session,
        tax_numbers="NEW GST 111",
        mandatory_bullets=["Only bullet"],
    )

    assert updated.tax_numbers == "NEW GST 111"
    assert updated.mandatory_bullets == ["Only bullet"]
    # Untouched fields keep their defaults.
    assert updated.shipping_accounts == repo.DEFAULT_SHIPPING_ACCOUNTS
    assert updated.company_from_address == repo.DEFAULT_COMPANY_FROM_ADDRESS


def test_update_settings_drops_blank_list_entries(db_session):
    updated = repo.update_settings(
        db_session,
        mandatory_bullets=["  keep me  ", "", "   ", "second"],
        shipping_accounts=["acct", None, ""],
        shipping_methods=["  LOCAL DELIVERY ", "", "Pick up"],
    )
    assert updated.mandatory_bullets == ["keep me", "second"]
    assert updated.shipping_accounts == ["acct"]
    assert updated.shipping_methods == ["LOCAL DELIVERY", "Pick up"]


def test_update_settings_can_clear_the_tariff_date(db_session):
    repo.get_settings(db_session)
    updated = repo.update_settings(db_session, usa_tariff_effective_until=None)
    assert updated.usa_tariff_effective_until is None


def test_update_settings_creates_the_row_if_missing(db_session):
    # No prior get_settings call: update must get-or-create first.
    updated = repo.update_settings(db_session, signature_note="Signed")
    assert updated.signature_note == "Signed"
    assert isinstance(updated.usa_tariff_effective_until, date)
