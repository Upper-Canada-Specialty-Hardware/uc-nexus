"""S3-compatible storage service for Railway Buckets."""

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import BUCKET_ACCESS_KEY_ID, BUCKET_ENDPOINT, BUCKET_NAME, BUCKET_SECRET_ACCESS_KEY
from app.errors import AppError

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=BUCKET_ENDPOINT,
            aws_access_key_id=BUCKET_ACCESS_KEY_ID,
            aws_secret_access_key=BUCKET_SECRET_ACCESS_KEY,
            config=BotoConfig(signature_version="s3v4"),
        )
    return _client


def upload_file(key: str, data: bytes, content_type: str, *, as_attachment: bool = False) -> str:
    """Store an object. `as_attachment` makes a browser opening its link download it rather than
    render it, for a type nothing vouched for.

    #1935: the bucket refusing or not answering was a raw botocore error, the masked "something went
    wrong" on a PO document or shipment photo. Nothing was stored and no row written, so it says that."""
    extra = {"ContentDisposition": "attachment"} if as_attachment else {}
    try:
        _get_client().put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
            **extra,
        )
    except (BotoCoreError, ClientError) as e:
        raise AppError("The file couldn't be stored - try again.", "STORAGE_UNAVAILABLE") from e
    return key


def download_file(key: str) -> bytes:
    client = _get_client()
    response = client.get_object(Bucket=BUCKET_NAME, Key=key)
    return response["Body"].read()


def delete_file(key: str) -> None:
    client = _get_client()
    client.delete_object(Bucket=BUCKET_NAME, Key=key)


def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )
