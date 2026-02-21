"""Storage — MinIO upload and highlights.json write."""

import json
import logging
import os
from pathlib import Path
from minio import Minio

from .config import settings

logger = logging.getLogger(__name__)


def get_minio_client() -> Minio:
    """Create a MinIO client from settings."""
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ROOT_USER,
        secret_key=settings.MINIO_ROOT_PASSWORD,
        secure=settings.MINIO_SECURE,
    )


def upload_clip(
    local_path: str,
    video_id: str,
    filename: str,
) -> str:
    """
    Upload a clip or thumbnail to MinIO via API.
    Used for cross-environment compatibility (local vs remote).

    Returns:
        The MinIO object path (relative to bucket root)
    """
    object_name = f"highlights/{video_id}/{filename}"
    bucket = settings.MINIO_BUCKET
    
    try:
        client = get_minio_client()
        client.fput_object(
            bucket,
            object_name,
            local_path,
            content_type="video/mp4" if filename.endswith(".mp4") else "image/jpeg",
        )
        logger.info(f"Uploaded via API: {local_path} → s3://{bucket}/{object_name}")
    except Exception as e:
        logger.error(f"S3 API upload failed for {filename}: {e}")
        # Volume fallback as last resort (emergency)
        vol = settings.OPENSTREAM_VOL_PATH.rstrip("/")
        direct_path = f"{vol}/{bucket}/{object_name}"
        try:
            import shutil
            os.makedirs(os.path.dirname(direct_path), exist_ok=True)
            shutil.copy2(local_path, direct_path)
            logger.info(f"Emergency volume fallback: {local_path} → {direct_path}")
        except Exception as ve:
            logger.critical(f"All storage methods failed: {ve}")
            raise ve

    return object_name


def upload_highlights_json(
    video_id: str,
    highlights_data: list[dict],
) -> str:
    """
    Write highlights.json to MinIO via API.
    Ensures that metadata is available even if volumes aren't perfectly synced.

    Returns:
        The MinIO object path
    """
    import io
    object_name = f"highlights/{video_id}/highlights.json"
    content = json.dumps(highlights_data, indent=2).encode("utf-8")
    bucket = settings.MINIO_BUCKET
    
    try:
        client = get_minio_client()
        client.put_object(
            bucket,
            object_name,
            io.BytesIO(content),
            length=len(content),
            content_type="application/json",
        )
        logger.info(f"Uploaded highlights.json via API → s3://{bucket}/{object_name}")
    except Exception as e:
        logger.error(f"S3 API JSON upload failed: {e}")
        # Volume fallback as last resort
        vol = settings.OPENSTREAM_VOL_PATH.rstrip("/")
        direct_path = f"{vol}/{bucket}/{object_name}"
        try:
            os.makedirs(os.path.dirname(direct_path), exist_ok=True)
            with open(direct_path, "wb") as f:
                f.write(content)
            logger.info(f"Emergency volume fallback for JSON → {direct_path}")
        except Exception as ve:
            logger.critical(f"All JSON storage methods failed: {ve}")
            raise ve

    return object_name


def upload_all_clips(
    clips: list[dict],
    video_id: str,
) -> list[dict]:
    """
    Upload all extracted clips and thumbnails to MinIO.

    Mutates clip dicts to replace local paths with MinIO URLs.

    Returns:
        Updated clips list
    """

    for clip in clips:
        if "clip_path" in clip and os.path.exists(clip["clip_path"]):
            filename = os.path.basename(clip["clip_path"])
            clip["clipUrl"] = upload_clip(clip["clip_path"], video_id, filename)

        if "thumbnail_path" in clip and os.path.exists(clip["thumbnail_path"]):
            filename = os.path.basename(clip["thumbnail_path"])
            clip["thumbnailUrl"] = upload_clip(
                clip["thumbnail_path"], video_id, filename
            )

    return clips


def cleanup_temp_files(temp_dir: str):
    """Remove temporary extraction directory."""
    import shutil

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"Cleaned up temp dir: {temp_dir}")
