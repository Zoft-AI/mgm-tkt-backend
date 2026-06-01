"""
Storage Operations Utilities

File storage using AWS S3 (replaces Supabase Storage).
Handles ticket attachments, temp uploads, and file management.
"""

import os
import time
import logging
from typing import List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# S3 client (initialized lazily)
_s3_client = None

def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            's3',
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "ap-south-1")
        )
    return _s3_client


def _get_bucket() -> str:
    return os.environ.get("AWS_S3_BUCKET", "boa-application-data")


def _get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for an S3 object"""
    s3 = _get_s3_client()
    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': _get_bucket(), 'Key': key},
        ExpiresIn=expires_in
    )


def generate_presigned_download_url(s3_key: str, expires_in: int = 3600) -> str:
    """Public helper to refresh a presigned URL from a stored s3_key."""
    return _get_presigned_url(s3_key, expires_in)


async def check_s3_health() -> bool:
    """Verify connectivity to the configured S3 bucket (HEAD request)."""
    try:
        s3 = _get_s3_client()
        s3.head_bucket(Bucket=_get_bucket())
        return True
    except Exception as e:
        logger.error(f"S3 health check failed: {str(e)}")
        return False


# ============================================================================
# Ticket Attachment Operations
# ============================================================================

async def upload_ticket_attachment(
    workspace_id: str, agent_id: str, request_identifier: str,
    file_content: bytes, file_name: str, content_type: str
) -> Tuple[str, str]:
    """
    Upload ticket attachment to S3.
    Path: {workspace_id}/{agent_id}/requests/{request_identifier}/{timestamp}_{filename}

    ``request_identifier`` should be the human-readable request_number
    (e.g. REQ-2026-00001) when available; falls back to UUID request_id.

    Returns (presigned_url, s3_key).
    """
    try:
        s3 = _get_s3_client()
        bucket = _get_bucket()
        timestamp = int(time.time())
        safe_name = file_name.replace(" ", "_")
        key = f"{workspace_id}/{agent_id}/requests/{request_identifier}/{timestamp}_{safe_name}"

        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=file_content,
            ContentType=content_type
        )

        url = _get_presigned_url(key)
        logger.info(f"Ticket attachment uploaded: {key}")
        return url, key

    except ClientError as e:
        logger.error(f"S3 upload error: {str(e)}")
        raise HTTPException(status_code=500, detail="File upload failed")
    except Exception as e:
        logger.error(f"Ticket attachment upload error: {str(e)}")
        raise


async def upload_temp_ticket_attachment(
    workspace_id: str, agent_id: str,
    file_content: bytes, file_name: str, content_type: str
) -> Tuple[str, str]:
    """
    Upload ticket attachment to a temp path (no request_id needed).
    Path: {workspace_id}/{agent_id}/temp/{timestamp}_{filename}
    Returns (presigned_url, s3_key).
    """
    try:
        s3 = _get_s3_client()
        bucket = _get_bucket()
        timestamp = int(time.time())
        safe_name = file_name.replace(" ", "_")
        key = f"{workspace_id}/{agent_id}/temp/{timestamp}_{safe_name}"

        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=file_content,
            ContentType=content_type
        )

        url = _get_presigned_url(key)
        logger.info(f"Temp ticket attachment uploaded: {key}")
        return url, key

    except ClientError as e:
        logger.error(f"S3 temp upload error: {str(e)}")
        raise HTTPException(status_code=500, detail="File upload failed")
    except Exception as e:
        logger.error(f"Temp ticket attachment upload error: {str(e)}")
        raise


async def move_temp_to_request_attachment(
    temp_path: str, workspace_id: str, agent_id: str, request_identifier: str
) -> Tuple[str, str]:
    """
    Move a temp-uploaded attachment to the proper request folder.
    ``request_identifier`` should be request_number when available.
    Returns (presigned_url, new_s3_key).
    """
    try:
        s3 = _get_s3_client()
        bucket = _get_bucket()
        filename = temp_path.split("/")[-1]
        timestamp = int(time.time())
        new_key = f"{workspace_id}/{agent_id}/requests/{request_identifier}/{timestamp}_{filename}"

        s3.copy_object(
            Bucket=bucket,
            CopySource={'Bucket': bucket, 'Key': temp_path},
            Key=new_key
        )

        s3.delete_object(Bucket=bucket, Key=temp_path)

        new_url = _get_presigned_url(new_key)
        logger.info(f"Attachment moved: {temp_path} -> {new_key}")
        return new_url, new_key

    except ClientError as e:
        logger.error(f"S3 move error: {str(e)}")
        raise HTTPException(status_code=500, detail="File move failed")
    except Exception as e:
        logger.error(f"Attachment move error: {str(e)}")
        raise


async def delete_ticket_attachment(file_url: str) -> bool:
    """
    Delete a ticket attachment from S3.
    Accepts either an S3 key directly or a presigned URL (extracts key from URL).
    Returns True on success.
    """
    try:
        s3 = _get_s3_client()
        bucket = _get_bucket()

        # If it's a full URL, extract the key
        key = file_url
        if "://" in file_url:
            # Handle presigned URL or public URL format
            # Presigned: https://bucket.s3.region.amazonaws.com/key?...
            # Or old supabase format: .../{bucket}/key
            from urllib.parse import urlparse, unquote
            parsed = urlparse(file_url)
            path = unquote(parsed.path)

            # Try to extract key from path
            if path.startswith("/"):
                path = path[1:]

            # Check for old Supabase storage format
            marker = f"object/public/ticket_attachments/"
            if marker in file_url:
                idx = file_url.find(marker)
                key = file_url[idx + len(marker):]
            else:
                key = path

        s3.delete_object(Bucket=bucket, Key=key)
        logger.info(f"Ticket attachment deleted: {key}")
        return True

    except ClientError as e:
        logger.error(f"S3 delete error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Ticket attachment delete error: {str(e)}")
        return False


# ============================================================================
# Legacy functions (kept for backward compatibility with chat agent features)
# These are no-ops or minimal implementations since chat agent storage
# is not the primary use case for the MGM ticket backend.
# ============================================================================

async def download_url_storage(chat_agent_id: str, file_name: str, list_folder: int = 0):
    """Legacy: Get URL for a chat agent file from S3"""
    try:
        if list_folder == 0:
            key = f"chat_files/{chat_agent_id}/{file_name}"
        elif list_folder == 2:
            key = f"chat_files/{chat_agent_id}/logo/{file_name}"
        else:
            key = f"chat_files/{chat_agent_id}/list/{file_name}"

        return _get_presigned_url(key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def upload_storage(chat_agent_id: str, temp_file_path: str, file_name: str, content_type: str, temp_dir: str, list_folder: int = 0):
    """Legacy: Upload chat agent file to S3"""
    try:
        s3 = _get_s3_client()
        bucket = _get_bucket()

        if list_folder == 1:
            key = f"chat_files/{chat_agent_id}/list/{file_name}"
        elif list_folder == 2:
            key = f"chat_files/{chat_agent_id}/logo/{file_name}"
        else:
            key = f"chat_files/{chat_agent_id}/{file_name}"

        with open(temp_file_path, 'rb') as file:
            file_content = file.read()

        s3.put_object(Bucket=bucket, Key=key, Body=file_content, ContentType=content_type)
        logger.info(f"File uploaded to S3: {key}")

    except Exception as e:
        logger.error(f"File upload error: {str(e)}")


async def delete_storage(chat_agent_id: str, file_name_list: List[str], list_folder: int = 0):
    """Legacy: Delete chat agent files from S3"""
    s3 = _get_s3_client()
    bucket = _get_bucket()

    for file_name in file_name_list:
        try:
            if list_folder == 0:
                key = f"chat_files/{chat_agent_id}/{file_name}"
            else:
                key = f"chat_files/{chat_agent_id}/list/{file_name}"
            s3.delete_object(Bucket=bucket, Key=key)
            logger.info(f"File deleted from S3: {key}")
        except Exception as e:
            logger.error(f"File delete error: {str(e)}")


async def remove_storage(chat_agent_id: str):
    """Legacy: Remove entire chat agent folder from S3"""
    try:
        s3 = _get_s3_client()
        bucket = _get_bucket()
        prefix = f"chat_files/{chat_agent_id}/"

        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        if 'Contents' in response:
            objects = [{'Key': obj['Key']} for obj in response['Contents']]
            s3.delete_objects(Bucket=bucket, Delete={'Objects': objects})
            logger.info(f"Storage folder removed: {prefix}")
    except Exception as e:
        logger.error(f"Storage removal error: {str(e)}")
        return e
