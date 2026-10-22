"""gp_idempotency.validate_key: the GP write key is checked before it can reach the relay (#1860).

The relay matches the key inside GP's note text with LIKE, where `%`, `_` and `[` are pattern syntax,
and holds it to the same letters, digits and hyphens; a key it would refuse is refused here first, as a
clean validation error rather than a relay error mid-write."""

import uuid

import pytest

from app.errors import ValidationError
from app.services import gp_idempotency


@pytest.mark.parametrize(
    "key",
    [
        str(uuid.uuid4()),
        str(uuid.uuid4()).upper(),
        f"demo-seed-register-{uuid.uuid4()}",
        f"demo-seed-approve-{uuid.uuid4()}",
        "k-1",
    ],
)
def test_the_keys_nexus_mints_are_accepted(key):
    assert gp_idempotency.validate_key(f"  {key} ") == key


@pytest.mark.parametrize("key", ["%", "_", "[a-z]", "ab%cd", "key with space", "key'quote", "k\\1", "k.1"])
def test_a_key_carrying_anything_but_letters_digits_and_hyphens_is_refused(key):
    with pytest.raises(ValidationError) as excinfo:
        gp_idempotency.validate_key(key)
    assert excinfo.value.field == "idempotency_key"


def test_a_key_longer_than_the_relay_takes_is_refused():
    gp_idempotency.validate_key("k" * 64)
    with pytest.raises(ValidationError):
        gp_idempotency.validate_key("k" * 65)


@pytest.mark.parametrize("key", ["", "   ", None])
def test_a_missing_key_is_refused(key):
    with pytest.raises(ValidationError):
        gp_idempotency.validate_key(key)
