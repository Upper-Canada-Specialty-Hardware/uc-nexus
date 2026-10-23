"""A failed upload says the file wasn't stored (#1935).

The bucket refusing a put, or not answering, surfaced the raw botocore error - the masked "something went
wrong on the server" on a PO document or a shipment photo. No real bucket is reached: the client is stubbed.
"""

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.errors import AppError
from app.services import storage


class _Bucket:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.puts: list[dict] = []

    def put_object(self, **kw):
        if self.error is not None:
            raise self.error
        self.puts.append(kw)


@pytest.fixture
def bucket(monkeypatch):
    def _make(**kw):
        fake = _Bucket(**kw)
        monkeypatch.setattr(storage, "_get_client", lambda: fake)
        return fake

    return _make


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObject"),
        EndpointConnectionError(endpoint_url="https://bucket.test"),
    ],
    ids=["refused", "unreachable"],
)
def test_a_failed_upload_says_the_file_was_not_stored(bucket, error):
    bucket(error=error)
    with pytest.raises(AppError) as e:
        storage.upload_file("po-documents/x/y.pdf", b"%PDF", "application/pdf")
    assert e.value.code == "STORAGE_UNAVAILABLE"
    assert e.value.message == "The file couldn't be stored - try again."


def test_an_upload_that_lands_answers_its_key(bucket):
    fake = bucket()
    assert storage.upload_file("k", b"data", "image/png", as_attachment=True) == "k"
    assert fake.puts[0]["ContentDisposition"] == "attachment"
