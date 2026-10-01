import os
import uuid
import logging
from django.conf import settings
from django.core.files.storage import default_storage, FileSystemStorage

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg'}
ALLOWED_VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.avi', '.m4v'}
ALLOWED_MEDIA_EXTS = ALLOWED_IMAGE_EXTS | ALLOWED_VIDEO_EXTS


def sign_azure_url(url_or_path, expiration_secs=86400 * 365 * 10):
    """
    Ensures an Azure Blob Storage URL has a valid SAS signature for read access.
    """
    if not url_or_path or not isinstance(url_or_path, str):
        return url_or_path

    url_str = url_or_path.strip()
    if 'blob.core.windows.net' not in url_str:
        return url_str

    if '?sig=' in url_str or '&sig=' in url_str:
        return url_str

    try:
        from urllib.parse import urlparse
        parsed = urlparse(url_str)
        path = parsed.path.lstrip('/')
        container = getattr(settings, 'AZURE_CONTAINER', 'media') or 'media'
        blob_name = path[len(container)+1:] if path.startswith(container + '/') else path
        
        return default_storage.url(blob_name, expire=expiration_secs)
    except Exception as e:
        logger.warning(f"[SignAzureURLError] Could not sign {url_str}: {e}")
        return url_str


def upload_tenant_media(client_id, folder_name, file, allowed_exts=None, max_size_mb=50):
    """
    Safely upload a media file for a specific tenant workspace.
    
    Target Path Structure:
        clients/client_{client_id}/{folder_name}/{uuid}{ext}
    
    Primary storage: Azure Blob Storage (via default_storage when configured).
    Fallback storage: FileSystemStorage under settings.MEDIA_ROOT.
    
    Returns:
        tuple: (public_url, media_type, original_filename)
    """
    if not file:
        raise ValueError("No file provided for upload.")

    max_bytes = max_size_mb * 1024 * 1024
    if file.size > max_bytes:
        raise ValueError(f"File size exceeds maximum allowed limit of {max_size_mb}MB.")

    orig_name = getattr(file, 'name', 'upload.dat')
    ext = os.path.splitext(orig_name)[1].lower()

    valid_exts = allowed_exts if allowed_exts else ALLOWED_MEDIA_EXTS
    if ext not in valid_exts:
        # Default fallback extension
        ext = '.png' if folder_name in ['catalog', 'images'] else '.mp4'

    # Determine media type category
    media_type = 'video' if ext in ALLOWED_VIDEO_EXTS else 'image'

    clean_client_id = str(client_id or 'default').replace(' ', '_')
    clean_folder = str(folder_name or 'uploads').strip().strip('/')
    unique_filename = f"{uuid.uuid4().hex}{ext}"

    # Standardized tenant isolation path
    storage_path = f"clients/client_{clean_client_id}/{clean_folder}/{unique_filename}"

    try:
        # 1. Primary: Use configured default_storage (Azure Blob Storage)
        saved_name = default_storage.save(storage_path, file)
        try:
            file_url = default_storage.url(saved_name, expire=86400 * 365 * 10)
        except TypeError:
            file_url = default_storage.url(saved_name)
        
        # Ensure url is absolute HTTPS
        if file_url and file_url.startswith('http://') and not ('localhost' in file_url or '127.0.0.1' in file_url):
            file_url = 'https://' + file_url[7:]

        logger.info(f"[TenantMediaUpload] Uploaded {file.name} to {file_url} (tenant: {clean_client_id})")
        return file_url, media_type, orig_name

    except Exception as primary_err:
        logger.warning(
            f"[TenantMediaUpload] Primary storage failed ({primary_err}). Falling back to local FileSystemStorage."
        )
        
        # 2. Resilient Fallback: Local FileSystemStorage
        try:
            local_fs = FileSystemStorage(location=settings.MEDIA_ROOT, base_url=settings.MEDIA_URL)
            local_name = local_fs.save(storage_path, file)
            file_url = local_fs.url(local_name)
            return file_url, media_type, orig_name
        except Exception as fallback_err:
            logger.error(f"[TenantMediaUpload] Fallback local storage also failed: {fallback_err}")
            raise RuntimeError(f"Failed to store media file: {fallback_err}")
