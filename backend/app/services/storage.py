"""S3-compatible storage service for Railway Buckets."""

import boto3
from botocore.config import Config as BotoConfig

from app.config import BUCKET_ACCESS_KEY_ID, BUCKET_ENDPOINT, BUCKET_NAME, BUCKET_SECRET_ACCESS_KEY


def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=BUCKET_ENDPOINT,
        aws_access_key_id=BUCKET_ACCESS_KEY_ID,
        aws_secret_access_key=BUCKET_SECRET_ACCESS_KEY,
        config=BotoConfig(signature_version="s3v4"),
    )


def upload_file(key: str, data: bytes, content_type: str) -> str:
    client = _get_client()
    client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
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
