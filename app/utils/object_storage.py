import os
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
import uuid
from urllib.parse import urlparse

# Load environment variables
load_dotenv()

def _normalize_bucket_name(bucket_value):
    """Accept plain bucket name or a mistakenly provided URL and normalize it."""
    if not bucket_value:
        return bucket_value

    candidate = str(bucket_value).strip()
    if not candidate:
        return None

    if candidate.startswith("http://") or candidate.startswith("https://"):
        parsed = urlparse(candidate)
        path_segments = [segment for segment in (parsed.path or "").split("/") if segment]
        if path_segments:
            return path_segments[0]
        raise RuntimeError(
            "R2_BUCKET_NAME appears to be a URL but no bucket path segment was found. "
            "Set R2_BUCKET_NAME to the bucket name only (for example: jicm-whatsapp)."
        )

    return candidate


R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET_NAME = _normalize_bucket_name(os.getenv("R2_BUCKET_NAME"))
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL")


def _ensure_r2_config(require_public_url=False):
    """Validate required R2 env vars before calling the SDK."""
    missing = []
    if not R2_ACCOUNT_ID:
        missing.append("R2_ACCOUNT_ID")
    if not R2_ACCESS_KEY:
        missing.append("R2_ACCESS_KEY")
    if not R2_SECRET_KEY:
        missing.append("R2_SECRET_KEY")
    if not R2_BUCKET_NAME:
        missing.append("R2_BUCKET_NAME")
    if require_public_url and not R2_PUBLIC_URL:
        missing.append("R2_PUBLIC_URL")

    if missing:
        raise RuntimeError(
            "Missing required object storage configuration: " + ", ".join(missing)
        )

    if "/" in R2_BUCKET_NAME:
        raise RuntimeError(
            "Invalid R2_BUCKET_NAME format. Set only the bucket name (for example: jicm-whatsapp), "
            "not a URL or path."
        )

# Initialize S3 client for R2
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
)

# ------------------------
# User-aware Operations
# ------------------------

def _generate_key(file, user_id=None, subfolder=None):
    """
    Generate a unique key for a file, optionally inside a user/job folder with subfolder.
    Args:
        file: File object or path string
        user_id: Optional user ID for user-specific files
        subfolder: Optional subfolder (e.g., 'jd', 'assets' for jobs)
    """
    # Handle both regular file objects and Gradio file paths (strings)
    if isinstance(file, str):
        ext = os.path.splitext(file)[1]
    else:
        ext = os.path.splitext(getattr(file, 'filename', getattr(file, 'name', '')))[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    
    path_parts = []
    if user_id:
        path_parts.append(str(user_id))
    if subfolder:
        path_parts.append(subfolder)
    path_parts.append(filename)
    
    return "/".join(path_parts) if path_parts else filename


def upload_file(file, user_id=None, subfolder=None):
    """
    Upload a single file to R2 under a user/job folder with optional subfolder.
    Returns public URL.
    Args:
        file: File object or path string
        user_id: Optional user/job ID for organized storage
        subfolder: Optional subfolder (e.g., 'jd', 'assets')
    """
    _ensure_r2_config(require_public_url=True)

    # Handle Gradio file paths (strings)
    if isinstance(file, str):
        key = _generate_key(file, user_id, subfolder)
        with open(file, 'rb') as f:
            file_content = f.read()
        # Try to guess content type from extension
        import mimetypes
        content_type, _ = mimetypes.guess_type(file)
        content_type = content_type or "application/octet-stream"
    else:
        key = _generate_key(file, user_id, subfolder)
        file_content = file.read()
        content_type = getattr(file, "content_type", "application/octet-stream")
    
    try:
        s3.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=key,
            Body=file_content,
            ContentType=content_type
        )
    except ClientError as e:
        raise Exception(f"Failed to upload file: {e}")
    return f"{R2_PUBLIC_URL}/{key}"


def upload_files(files, user_id=None):
    """
    Upload multiple files under a user folder.
    Returns a list of URLs.
    """
    urls = []
    for f in files:
        urls.append(upload_file(f, user_id))
    return urls


def list_files(user_id=None, prefix=None, max_keys=100):
    """
    List files in bucket. Can filter by user or custom prefix.
    """
    _ensure_r2_config()

    combined_prefix = f"{user_id}/" if user_id else ""
    if prefix:
        combined_prefix += prefix

    try:
        response = s3.list_objects_v2(
            Bucket=R2_BUCKET_NAME,
            Prefix=combined_prefix,
            MaxKeys=max_keys
        )
        files = [obj["Key"] for obj in response.get("Contents", [])]
        return files
    except ClientError as e:
        raise Exception(f"Failed to list files: {e}")


def delete_file(key, user_id=None):
    """
    Delete a file from R2. If user_id is provided, prepends it to the key.
    """
    _ensure_r2_config()

    full_key = f"{user_id}/{key}" if user_id else key
    try:
        s3.delete_object(Bucket=R2_BUCKET_NAME, Key=full_key)
    except ClientError as e:
        raise Exception(f"Failed to delete file: {e}")
    return True


def delete_all_user_files(user_id):
    """
    Delete all files for a specific user.
    """
    keys = list_files(user_id=user_id)
    for key in keys:
        delete_file(key)
    return True


def generate_signed_url(key, user_id=None, expiration_minutes=60):
    """
    Generate a signed URL for a file. Automatically prepends user_id if provided.
    """
    _ensure_r2_config()

    full_key = f"{user_id}/{key}" if user_id else key
    try:
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": full_key},
            ExpiresIn=expiration_minutes * 60
        )
        return url
    except ClientError as e:
        raise Exception(f"Failed to generate signed URL: {e}")


def download_file(key, local_path, user_id=None):
    """
    Download a file from R2 locally. Prepends user_id if provided.
    """
    _ensure_r2_config()

    full_key = f"{user_id}/{key}" if user_id else key
    try:
        s3.download_file(R2_BUCKET_NAME, full_key, local_path)
    except ClientError as e:
        raise Exception(f"Failed to download file: {e}")
    return local_path


def url_to_r2_key(file_url):
    """
    Extract R2 key from a full public URL.
    Args:
        file_url: Full URL like "https://bucket.example.com/jobs/123/jd/uuid.pdf"
    Returns:
        R2 key like "jobs/123/jd/uuid.pdf"
    """
    if not file_url or not R2_PUBLIC_URL:
        return None
    if file_url.startswith(R2_PUBLIC_URL + "/"):
        return file_url[len(R2_PUBLIC_URL) + 1:]
    return None
