"""File storage service for S3 uploads and signed URLs."""

import boto3
from botocore.exceptions import ClientError

from app.config import S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL


def _get_s3_client():
    """Get a configured boto3 S3 client."""
    kwargs = {
        "aws_access_key_id": S3_ACCESS_KEY_ID,
        "aws_secret_access_key": S3_SECRET_ACCESS_KEY,
    }
    if S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


def upload_pdf(s3_key: str, pdf_bytes: bytes) -> str:
    """Upload PDF bytes to S3. Returns the S3 key."""
    client = _get_s3_client()
    client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )
    return s3_key


def generate_signed_url(s3_key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for an S3 object."""
    client = _get_s3_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": s3_key},
        ExpiresIn=expires_in,
    )
    return url
